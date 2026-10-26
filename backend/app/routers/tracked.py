from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import PREMIUM_ALERT_KINDS, AlertKind, PriceAlert, TrackedProduct, TrackingState, User, utcnow
from ..schemas import AlertIn, AlertPatch, BulkIn, TrackedCreate, TrackedPatch
from ..security import get_current_user, rate_limiter
from ..services import compare as compare_svc
from ..services import history as history_svc
from ..services import tracking
from ..services.fx import load_rates
from ..services.listings import ShortLinkError, parse_or_resolve
from ..services.views import serialize_alert, serialize_tracked, serialize_tracked_many
from ..urlutil import InvalidUrl
from ..util import D, iso
from .deps import audit, get_prefs, owned_tracked

router = APIRouter(prefix="/tracked", tags=["carrito"])
_write_limit = rate_limiter("write", "rate_limit_write_per_min")
REFRESH_COOLDOWN_MINUTES = 10


def _display(db: Session, user: User, currency: str | None) -> str:
    return (currency or get_prefs(db, user).currency).upper()


@router.post("", status_code=201, dependencies=[Depends(_write_limit)])
def add_item(body: TrackedCreate, bg: BackgroundTasks, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    try:
        parsed = parse_or_resolve(body.url)
    except InvalidUrl as e:
        raise HTTPException(422, {"message": str(e), "retryable": False}) from e
    except ShortLinkError as e:
        raise HTTPException(503 if e.retryable else 422, {"message": str(e), "retryable": e.retryable}) from e
    prefs_cur = get_prefs(db, user).currency
    try:
        tracked, created = tracking.add_tracked(
            db, user, parsed, target_price=body.target_price,
            target_currency=(body.target_currency or prefs_cur) if body.target_price is not None else None,
            notes=body.notes, list_name=body.list_name, category=body.category, priority=body.priority)
    except tracking.TierLimitError as e:
        raise HTTPException(402, {"message": str(e), "retryable": False}) from e
    audit(db, user.id, "tracked_add" if created else "tracked_duplicate", parsed.store_key)
    db.commit()
    if created:
        bg.add_task(tracking.check_listing_in_background, tracked.listing_id)
    rates = load_rates(db)
    item = serialize_tracked(db, tracked, rates, _display(db, user, None))
    return {
        "item": item, "duplicate": not created,
        "message": "Añadido a tu carrito" if created else "Este producto ya estaba en tu carrito",
    }


@router.get("")
def list_items(
    q: str | None = None, store: str | None = None, state: str | None = None, list_name: str | None = None,
    category: str | None = None, archived: bool = False, purchased: bool = False, include_deleted: bool = False,
    has_discount: bool | None = None, min_price: Decimal | None = None, max_price: Decimal | None = None,
    sort: str = Query("added", pattern="^(added|updated|price|discount|name|priority)$"),
    currency: str | None = Query(None, min_length=3, max_length=3),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    stmt = select(TrackedProduct).where(TrackedProduct.user_id == user.id)
    if not include_deleted:
        stmt = stmt.where(TrackedProduct.deleted.is_(False))
    stmt = stmt.where(TrackedProduct.archived.is_(archived), TrackedProduct.purchased.is_(purchased))
    if list_name:
        stmt = stmt.where(TrackedProduct.list_name == list_name)
    if category:
        stmt = stmt.where(TrackedProduct.category == category)
    if state:
        stmt = stmt.where(TrackedProduct.state == state)
    items = list(db.scalars(stmt).all())
    if store:
        items = [t for t in items if t.listing.store.key == store]
    if q:
        ql = q.lower()
        items = [t for t in items if ql in (t.listing.title or "").lower() or ql in (t.notes or "").lower()]
    rates = load_rates(db)
    data = serialize_tracked_many(db, items, rates, _display(db, user, currency))
    if has_discount is not None:
        data = [d for d in data if (d["has_promotion"] or (d["change_from_initial_pct"] is not None
                                                         and D(d["change_from_initial_pct"]) < 0)) == has_discount]
    if min_price is not None:
        data = [d for d in data if d["price_current"] is not None and D(d["price_current"]) >= min_price]
    if max_price is not None:
        data = [d for d in data if d["price_current"] is not None and D(d["price_current"]) <= max_price]
    keys = {
        "added": (lambda d: d["created_at"], True), "updated": (lambda d: d["updated_at"], True),
        "price": (lambda d: D(d["price_current"]) if d["price_current"] else Decimal("Infinity"), False),
        "discount": (lambda d: D(d["change_from_initial_pct"]) if d["change_from_initial_pct"] else Decimal(0), False),
        "name": (lambda d: d["title"].lower(), False), "priority": (lambda d: d["priority"], True),
    }
    fn, rev = keys[sort]
    data.sort(key=fn, reverse=rev)
    return {"items": data, "count": len(data)}


@router.get("/lists")
def lists(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(TrackedProduct.list_name).where(
        TrackedProduct.user_id == user.id, TrackedProduct.deleted.is_(False),
        TrackedProduct.list_name.is_not(None)).distinct()).all()
    return {"lists": sorted(r for r in rows if r)}


@router.post("/bulk", dependencies=[Depends(_write_limit)])
def bulk(body: BulkIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(TrackedProduct).where(
        TrackedProduct.user_id == user.id, TrackedProduct.id.in_(body.ids), TrackedProduct.deleted.is_(False))).all()
    for t in items:
        _apply_action(db, user, t, body)
    audit(db, user.id, "bulk_" + body.action, f"{len(items)} items")
    db.commit()
    return {"ok": True, "affected": len(items)}


def _apply_action(db: Session, user: User, t: TrackedProduct, body: BulkIn) -> None:
    a = body.action
    if a == "archive":
        t.archived = True
    elif a == "restore":
        if tracking.active_count(db, user.id) >= tracking.tracked_limit(user):
            raise HTTPException(402, {"message": "Alcanzaste el límite de productos vigilados de tu plan"})
        t.archived, t.purchased, t.deleted = False, False, False
        tracking.apply_pause(db, t, t.paused)
    elif a == "delete":
        t.deleted = True
    elif a == "purchased":
        t.purchased = True
    elif a == "pause":
        tracking.apply_pause(db, t, True)
    elif a == "resume":
        tracking.apply_pause(db, t, False)
    elif a == "set_list":
        t.list_name = body.list_name
    elif a == "set_priority" and body.priority is not None:
        t.priority = body.priority
    t.updated_at = utcnow()


@router.get("/{tracked_id}")
def get_item(t: TrackedProduct = Depends(owned_tracked), user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    return serialize_tracked(db, t, load_rates(db), _display(db, user, None))


@router.patch("/{tracked_id}", dependencies=[Depends(_write_limit)])
def patch_item(body: TrackedPatch, t: TrackedProduct = Depends(owned_tracked), user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    sent = body.model_fields_set
    if "target_price" in sent:
        cur = body.target_currency or get_prefs(db, user).currency
        tracking.set_target(db, t, body.target_price, cur if body.target_price is not None else None)
        if body.target_price is None:  # quitar objetivo => desactivar su alerta
            a = db.scalar(select(PriceAlert).where(PriceAlert.tracked_id == t.id,
                                                   PriceAlert.kind == AlertKind.TARGET_PRICE.value))
            if a:
                a.active = False
    for f in ("notes", "list_name", "category"):
        if f in sent:
            setattr(t, f, getattr(body, f))
    if "priority" in sent and body.priority is not None:
        t.priority = body.priority
    if "archived" in sent and body.archived is not None:
        if not body.archived and t.archived and tracking.active_count(db, user.id) >= tracking.tracked_limit(user):
            raise HTTPException(402, {"message": "Alcanzaste el límite de productos vigilados de tu plan"})
        t.archived = body.archived
    if "purchased" in sent and body.purchased is not None:
        t.purchased = body.purchased
        if body.purchased and "purchased_price" in sent:
            t.purchased_price = body.purchased_price
        if not body.purchased:
            t.purchased_price = None
    if "paused" in sent and body.paused is not None:
        tracking.apply_pause(db, t, body.paused)
    if not (t.archived or t.purchased or t.paused):
        tracking.ensure_job(db, t.listing, priority=t.priority * 10)
    t.updated_at = utcnow()
    db.commit()
    return serialize_tracked(db, t, load_rates(db), _display(db, user, None))


@router.delete("/{tracked_id}", dependencies=[Depends(_write_limit)])
def delete_item(t: TrackedProduct = Depends(owned_tracked), user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    t.deleted = True  # tombstone: permite sincronizar la eliminación a otros dispositivos
    t.updated_at = utcnow()
    audit(db, user.id, "tracked_delete")
    db.commit()
    return {"ok": True}


@router.get("/{tracked_id}/history")
def history(range: str = Query("30d", pattern="^(7d|30d|90d|6m|1y)$"), t: TrackedProduct = Depends(owned_tracked),
            db: Session = Depends(get_db)):
    return history_svc.build_history(db, t.listing, range)


@router.post("/{tracked_id}/refresh", dependencies=[Depends(_write_limit)])
def refresh(bg: BackgroundTasks, t: TrackedProduct = Depends(owned_tracked), db: Session = Depends(get_db)):
    if t.paused or t.archived or t.purchased:
        raise HTTPException(409, "Reanuda el seguimiento para actualizar este producto")
    job = tracking.ensure_job(db, t.listing, priority=t.priority * 10)
    from datetime import timedelta

    if job.last_run_at and utcnow() - job.last_run_at < timedelta(minutes=REFRESH_COOLDOWN_MINUTES):
        db.commit()
        return {"queued": False, "message": f"Se actualizó hace menos de {REFRESH_COOLDOWN_MINUTES} minutos"}
    job.next_run_at = utcnow()
    db.commit()
    bg.add_task(tracking.check_listing_in_background, t.listing_id)
    return {"queued": True, "message": "Actualización en curso"}


# ---- alertas ----

def _check_kind_allowed(user: User, kind: AlertKind) -> None:
    if kind in PREMIUM_ALERT_KINDS and user.tier != "premium":
        raise HTTPException(402, {"message": "Este tipo de alerta es de la versión premium", "retryable": False})


def _check_threshold(kind: AlertKind, threshold: Decimal | None) -> None:
    needs = {AlertKind.PCT_DROP, AlertKind.TOTAL_BUDGET}
    if kind in needs and threshold is None:
        raise HTTPException(422, "Esta alerta requiere un valor (porcentaje o presupuesto)")
    if kind == AlertKind.PCT_DROP and threshold is not None and threshold > 99:
        raise HTTPException(422, "El porcentaje debe estar entre 1 y 99")


@router.get("/{tracked_id}/alerts")
def list_alerts(t: TrackedProduct = Depends(owned_tracked)):
    return {"alerts": [serialize_alert(a) for a in t.alerts]}


@router.post("/{tracked_id}/alerts", status_code=201, dependencies=[Depends(_write_limit)])
def create_alert(body: AlertIn, t: TrackedProduct = Depends(owned_tracked), user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    _check_kind_allowed(user, body.kind)
    _check_threshold(body.kind, body.threshold)
    cur = body.threshold_currency or (get_prefs(db, user).currency if body.threshold is not None else None)
    if body.kind == AlertKind.PCT_DROP:
        cur = None
    a = tracking.upsert_alert(db, t, body.kind.value, body.threshold, cur, body.active)
    if body.kind == AlertKind.TARGET_PRICE and body.threshold is not None:
        t.target_price, t.target_currency = body.threshold, cur
    t.updated_at = utcnow()
    db.commit()
    return serialize_alert(a)


def _owned_alert(alert_id: int, t: TrackedProduct, db: Session) -> PriceAlert:
    a = db.scalar(select(PriceAlert).where(PriceAlert.id == alert_id, PriceAlert.tracked_id == t.id))
    if a is None:
        raise HTTPException(404, "Alerta no encontrada")
    return a


@router.patch("/{tracked_id}/alerts/{alert_id}", dependencies=[Depends(_write_limit)])
def patch_alert(alert_id: int, body: AlertPatch, t: TrackedProduct = Depends(owned_tracked),
                db: Session = Depends(get_db)):
    a = _owned_alert(alert_id, t, db)
    sent = body.model_fields_set
    if "threshold" in sent and body.threshold is not None:
        a.threshold = body.threshold
        if "threshold_currency" in sent:
            a.threshold_currency = body.threshold_currency
        a.armed, a.last_triggered_price = True, None
    if "active" in sent and body.active is not None:
        a.active = body.active
        if body.active:
            a.armed, a.last_triggered_price = True, None
    t.updated_at = utcnow()
    db.commit()
    return serialize_alert(a)


@router.delete("/{tracked_id}/alerts/{alert_id}", dependencies=[Depends(_write_limit)])
def delete_alert(alert_id: int, t: TrackedProduct = Depends(owned_tracked), db: Session = Depends(get_db)):
    a = _owned_alert(alert_id, t, db)
    db.delete(a)
    t.updated_at = utcnow()
    db.commit()
    return {"ok": True}


# ---- comparador ----

@router.get("/{tracked_id}/compare")
def compare(t: TrackedProduct = Depends(owned_tracked), user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    rates = load_rates(db)
    base = t.listing
    offers = compare_svc.related_offers(db, base, rates)
    cands, errors = compare_svc.external_candidates(base)
    base_obs = compare_svc.latest_observation(db, base.id)
    note = None
    if base.product_id is None:
        note = ("No hay datos suficientes (GTIN o marca y modelo) para identificar este artículo en otras tiendas; "
                "los resultados de búsqueda son sólo aproximados.")
    return {
        "base": {
            "store": base.store.name, "title": base.title, "url": base.canonical_url,
            "price": str(base_obs.price) if base_obs else None, "currency": base_obs.currency if base_obs else None,
        },
        "offers": [{
            "tracked_listing_id": o.listing.id, "store_key": o.store_key, "store_name": o.store_name,
            "title": o.listing.title, "url": o.listing.canonical_url, "price": None if o.price is None else str(o.price),
            "currency": o.currency, "shipping": None if o.shipping is None else str(o.shipping),
            "total_estimated": None if o.total_estimated is None else str(o.total_estimated),
            "total_is_estimate": True,  # nunca se presenta como precio definitivo de pago
            "total_confirmed": None, "available": o.available, "match": o.match, "notes": o.notes,
            "checked_at": iso(o.checked_at),
        } for o in offers],
        "candidates": cands, "candidate_errors": errors, "note": note,
        "disclaimer": "Los totales son estimaciones: el costo final depende del destino, el vendedor y la disponibilidad.",
    }
