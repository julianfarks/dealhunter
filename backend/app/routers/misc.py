from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..connectors import all_connectors
from ..db import get_db
from ..models import (
    AuditEvent, DeviceToken, Notification, PriceAlert, PriceObservation, Promotion, TrackedProduct, User,
    UserPreference, utcnow,
)
from ..schemas import AiIn, DeleteAccountIn, DeviceIn, PrefsIn
from ..security import get_current_user, rate_limiter, verify_password
from ..services import ai as ai_svc
from ..services import offers as offers_svc
from ..services.fx import load_rates
from ..services.tracking import active_count, tracked_limit
from ..services.views import latest_prices, potential_saving, serialize_tracked_many
from ..util import D, iso
from .deps import audit, get_prefs

router = APIRouter(tags=["general"])
_write_limit = rate_limiter("write", "rate_limit_write_per_min")


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok"}


@router.get("/stores")
def stores():
    return {"stores": [{
        "key": c.key, "name": c.name, "status": c.status(), "configured": c.configured(), "docs": c.docs,
        "status_label": {
            "integrated": "Listo (credenciales configuradas)", "needs_credentials": "Faltan credenciales en el servidor",
            "unavailable": "Pendiente / sin fuente disponible",
        }.get(c.status(), c.status()),
    } for c in all_connectors()]}


# ---------------------------------------------------------------- panel principal

@router.get("/dashboard")
def dashboard(currency: str | None = Query(None, min_length=3, max_length=3), user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    now = utcnow()
    prefs = get_prefs(db, user)
    display = (currency or prefs.currency).upper()
    rates = load_rates(db)
    items = list(db.scalars(select(TrackedProduct).where(
        TrackedProduct.user_id == user.id, TrackedProduct.deleted.is_(False),
        TrackedProduct.archived.is_(False), TrackedProduct.purchased.is_(False))))
    views = serialize_tracked_many(db, items, rates, display)
    prices = latest_prices(db, [t.listing_id for t in items])

    at_target = []
    potential: dict[str, Decimal] = {}
    for t, v in zip(items, views):
        o = prices.get(t.listing_id)
        if o is None:
            continue
        cur = D(o.price)
        if t.target_price is not None and (t.target_currency or o.currency) == o.currency and cur <= D(t.target_price):
            at_target.append(v)
        sv = potential_saving(t, cur, o.currency)
        if sv is not None:
            potential[o.currency] = potential.get(o.currency, Decimal(0)) + sv
    potential_converted = None
    if potential and rates.per_usd:
        from ..currency import RateUnavailable, convert

        try:
            total = sum((convert(a, c, display, rates).amount for c, a in potential.items()), Decimal(0))
            potential_converted = {"currency": display, "amount": str(total), "as_of": iso(rates.fetched_at),
                                   "source": rates.source}
        except RateUnavailable:
            potential_converted = None

    week_ago = now - timedelta(days=7)
    listing_ids = [t.listing_id for t in items]
    new_offers = db.scalar(select(func.count(Promotion.id)).where(
        Promotion.listing_id.in_(listing_ids or [-1]), Promotion.active.is_(True), Promotion.detected_at >= week_ago)) or 0

    # Últimas variaciones: comparar las dos observaciones más recientes de cada producto
    changes = []
    for t, v in zip(items, views):
        rows = db.execute(select(PriceObservation.price, PriceObservation.currency, PriceObservation.observed_at)
                          .where(PriceObservation.listing_id == t.listing_id, PriceObservation.price.is_not(None))
                          .order_by(PriceObservation.observed_at.desc(), PriceObservation.id.desc()).limit(2)).all()
        if len(rows) == 2 and rows[0][1] == rows[1][1] and D(rows[0][0]) != D(rows[1][0]):
            old, new = D(rows[1][0]), D(rows[0][0])
            changes.append({
                "tracked_id": t.id, "title": v["title"], "image_url": v["image_url"], "currency": rows[0][1],
                "previous_price": str(old), "current_price": str(new),
                "change_pct": str(((new - old) / old * 100).quantize(Decimal("0.01"))) if old else None,
                "at": iso(rows[0][2]),
            })
    changes.sort(key=lambda c: c["at"], reverse=True)

    realized: dict[str, Decimal] = {}
    for t in db.scalars(select(TrackedProduct).where(
            TrackedProduct.user_id == user.id, TrackedProduct.purchased.is_(True),
            TrackedProduct.deleted.is_(False), TrackedProduct.purchased_price.is_not(None))):
        if t.initial_price is not None and D(t.initial_price) > D(t.purchased_price):
            cur = t.initial_currency or "COP"
            realized[cur] = realized.get(cur, Decimal(0)) + (D(t.initial_price) - D(t.purchased_price))

    recent = db.scalars(select(Notification).where(Notification.user_id == user.id)
                        .order_by(Notification.created_at.desc(), Notification.id.desc()).limit(5)).all()
    unread = db.scalar(select(func.count(Notification.id)).where(
        Notification.user_id == user.id, Notification.read_at.is_(None))) or 0
    return {
        "watched_count": len(items), "limit": tracked_limit(user), "new_offers": new_offers,
        "reached_target": at_target, "reached_target_count": len(at_target),
        "potential_savings": {  # ESTIMADO: no es dinero ahorrado
            "by_currency": {c: str(a) for c, a in potential.items()}, "converted": potential_converted,
            "note": "Ahorro potencial estimado frente al precio registrado al añadir cada producto. No es dinero ahorrado.",
        },
        "realized_savings": {  # sólo compras marcadas con su precio real
            "by_currency": {c: str(a) for c, a in realized.items()},
            "note": "Calculado sólo con productos marcados como comprados e indicando el precio pagado.",
        },
        "latest_changes": changes[:10], "recent_alerts": [_notif(n) for n in recent], "unread_notifications": unread,
        "display_currency": display,
    }


# ---------------------------------------------------------------- ofertas

@router.get("/offers")
def offers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"offers": offers_svc.list_offers(db, user.id)}


# ---------------------------------------------------------------- notificaciones

def _notif(n: Notification) -> dict:
    return {
        "id": n.id, "tracked_id": n.tracked_id, "kind": n.kind, "title": n.title, "body": n.body,
        "payload": n.payload, "delivery_status": n.delivery_status, "created_at": iso(n.created_at),
        "read": n.read_at is not None,
    }


@router.get("/notifications")
def notifications(limit: int = Query(50, ge=1, le=200), before_id: int | None = None,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(Notification).where(Notification.user_id == user.id)
    if before_id:
        q = q.where(Notification.id < before_id)
    rows = db.scalars(q.order_by(Notification.id.desc()).limit(limit)).all()
    return {"notifications": [_notif(n) for n in rows]}


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id))
    if n is None:
        raise HTTPException(404, "Notificación no encontrada")
    n.read_at = n.read_at or utcnow()
    db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for n in db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))):
        n.read_at = utcnow()
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- preferencias y dispositivos

def _prefs_out(p: UserPreference) -> dict:
    return {
        "currency": p.currency, "language": p.language, "theme": p.theme, "timezone": p.timezone,
        "utc_offset_minutes": p.utc_offset_minutes, "quiet_start": p.quiet_start, "quiet_end": p.quiet_end,
        "max_notifications_per_day": p.max_notifications_per_day, "daily_digest": p.daily_digest,
        "weekly_digest": p.weekly_digest, "muted_categories": p.muted_categories or [], "muted_kinds": p.muted_kinds or [],
    }


@router.get("/preferences")
def get_preferences(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = get_prefs(db, user)
    db.commit()
    return _prefs_out(p)


@router.put("/preferences", dependencies=[Depends(_write_limit)])
def put_preferences(body: PrefsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = get_prefs(db, user)
    sent = body.model_fields_set
    for f in ("currency", "language", "theme", "timezone", "utc_offset_minutes", "max_notifications_per_day",
              "daily_digest", "weekly_digest", "muted_categories", "muted_kinds"):
        if f in sent and getattr(body, f) is not None:
            setattr(p, f, getattr(body, f))
    if body.clear_quiet_hours:
        p.quiet_start = p.quiet_end = None
    else:
        if "quiet_start" in sent and body.quiet_start is not None:
            p.quiet_start = body.quiet_start
        if "quiet_end" in sent and body.quiet_end is not None:
            p.quiet_end = body.quiet_end
    db.commit()
    return _prefs_out(p)


@router.post("/devices", status_code=201, dependencies=[Depends(_write_limit)])
def register_device(body: DeviceIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(DeviceToken).where(DeviceToken.token == body.token))
    if row is None:
        db.add(DeviceToken(user_id=user.id, token=body.token, platform=body.platform))
    elif row.user_id != user.id:  # el mismo teléfono cambió de cuenta
        row.user_id = user.id
    db.commit()
    return {"ok": True}


@router.delete("/devices")
def unregister_device(token: str = Query(min_length=20, max_length=400), user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    db.execute(delete(DeviceToken).where(DeviceToken.token == token, DeviceToken.user_id == user.id))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- IA

@router.post("/ai/command", dependencies=[Depends(_write_limit)])
def ai_command(body: AiIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if get_settings().ai_requires_premium and user.tier != "premium":
        raise HTTPException(402, {"message": "El asistente de IA es una función premium", "retryable": False})
    tracked = None
    if body.tracked_id is not None:
        tracked = db.scalar(select(TrackedProduct).where(
            TrackedProduct.id == body.tracked_id, TrackedProduct.user_id == user.id, TrackedProduct.deleted.is_(False)))
        if tracked is None:
            raise HTTPException(404, "Producto no encontrado")
    intent = ai_svc.interpret(body.text)
    result = ai_svc.execute(db, user, intent, tracked)
    result["interpreted_as"] = intent
    audit(db, user.id, "ai_command", intent["action"])
    db.commit()
    return result


# ---------------------------------------------------------------- sincronización

@router.get("/sync/changes")
def sync_changes(since: str | None = None, currency: str | None = Query(None, min_length=3, max_length=3),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Cambios desde `since` (ISO UTC). Incluye elementos eliminados (deleted=true) para propagar bajas."""
    stmt = select(TrackedProduct).where(TrackedProduct.user_id == user.id)
    if since:
        try:
            ts = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as e:
            raise HTTPException(422, "Fecha 'since' inválida") from e
        if ts.tzinfo is not None:  # a UTC "naive", que es como se guarda en la base de datos
            ts = (ts - (ts.utcoffset() or timedelta(0))).replace(tzinfo=None)
        stmt = stmt.where(TrackedProduct.updated_at > ts)
    server_time = utcnow()
    items = list(db.scalars(stmt.order_by(TrackedProduct.updated_at)).all())
    data = serialize_tracked_many(db, items, load_rates(db), (currency or get_prefs(db, user).currency).upper())
    return {"items": data, "server_time": iso(server_time)}


# ---------------------------------------------------------------- cuenta y privacidad

@router.get("/account/export")
def export_account(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = list(db.scalars(select(TrackedProduct).where(TrackedProduct.user_id == user.id)))
    views = serialize_tracked_many(db, items, load_rates(db), None)
    obs = []
    for lid in {t.listing_id for t in items}:
        for o in db.scalars(select(PriceObservation).where(PriceObservation.listing_id == lid)
                            .order_by(PriceObservation.observed_at)):
            obs.append({"listing_id": lid, "price": None if o.price is None else str(o.price), "currency": o.currency,
                        "available": o.available, "source": o.source, "observed_at": iso(o.observed_at)})
    audit(db, user.id, "account_export")
    db.commit()
    return {
        "exported_at": iso(utcnow()),
        "user": {"email": user.email, "tier": user.tier, "created_at": iso(user.created_at)},
        "preferences": _prefs_out(get_prefs(db, user)),
        "tracked_products": views, "price_observations": obs,
        "notifications": [_notif(n) for n in db.scalars(select(Notification).where(Notification.user_id == user.id))],
        "devices": db.scalar(select(func.count(DeviceToken.id)).where(DeviceToken.user_id == user.id)),
    }


@router.delete("/account", dependencies=[Depends(_write_limit)])
def delete_account(body: DeleteAccountIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(403, "Contraseña incorrecta")
    uid = user.id
    for model in (Notification, PriceAlert, DeviceToken):
        db.execute(delete(model).where(model.user_id == uid))
    db.execute(delete(TrackedProduct).where(TrackedProduct.user_id == uid))
    db.execute(delete(UserPreference).where(UserPreference.user_id == uid))
    db.execute(delete(User).where(User.id == uid))
    db.add(AuditEvent(user_id=uid, action="account_deleted"))
    db.commit()
    return {"ok": True}


PRIVACY_TEXT = """Política de privacidad de DealHunter AI

Qué datos guardamos: tu correo, tu contraseña (sólo como hash), los enlaces de productos que añades, tus notas,
alertas y preferencias, los precios observados de esos productos y los tokens de notificación de tus dispositivos.

Qué NO hacemos: no pedimos contraseñas de Amazon, AliExpress ni otras tiendas, no accedemos a tus carritos privados
ni a tus cuentas de compra, no compramos nada por ti y no vendemos tus datos.

Uso: vigilar precios y avisarte. Los precios proceden de APIs oficiales o fuentes públicas permitidas.
Si activas el asistente de IA, tu instrucción de texto se envía al proveedor de IA configurado en el servidor.

Tus derechos: puedes exportar todos tus datos (Ajustes > Exportar datos) y eliminar tu cuenta y todos tus datos
(Ajustes > Eliminar cuenta). Al eliminarla se borran tu carrito, alertas, notificaciones y dispositivos.
"""


@router.get("/privacy")
def privacy():
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(PRIVACY_TEXT)
