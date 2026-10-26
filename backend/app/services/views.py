"""Serialización de elementos del carrito (con precios actuales, promociones y conversión de moneda)."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..currency import RateUnavailable, Rates, convert
from ..models import PriceObservation, Promotion, TrackedProduct
from ..util import D, iso, pct_change

STATE_LABELS = {
    "active": "Seguimiento automático activo",
    "waiting_first_check": "Esperando la primera consulta",
    "temporarily_failed": "Actualización temporalmente fallida",
    "price_unavailable": "Precio no disponible",
    "needs_source": "Requiere una fuente de datos compatible",
    "paused": "Seguimiento pausado",
    "unavailable_in_store": "Producto no disponible en la tienda",
}


def latest_prices(db: Session, listing_ids: list[int]) -> dict[int, PriceObservation]:
    if not listing_ids:
        return {}
    ids = db.execute(select(func.max(PriceObservation.id)).where(
        PriceObservation.listing_id.in_(listing_ids), PriceObservation.price.is_not(None))
        .group_by(PriceObservation.listing_id)).scalars().all()
    if not ids:
        return {}
    rows = db.scalars(select(PriceObservation).where(PriceObservation.id.in_(ids))).all()
    return {r.listing_id: r for r in rows}


def active_promos(db: Session, listing_ids: list[int]) -> dict[int, list[Promotion]]:
    out: dict[int, list[Promotion]] = {}
    if not listing_ids:
        return out
    for p in db.scalars(select(Promotion).where(Promotion.listing_id.in_(listing_ids), Promotion.active.is_(True))):
        out.setdefault(p.listing_id, []).append(p)
    return out


def _s(v) -> str | None:
    return None if v is None else str(v)


def _conv(amount, src, dst, rates: Rates | None):
    if amount is None or not src or not dst or rates is None:
        return None
    try:
        return convert(D(amount), src, dst, rates)
    except RateUnavailable:
        return None


def serialize_alert(a) -> dict:
    return {
        "id": a.id, "kind": a.kind, "threshold": _s(a.threshold), "threshold_currency": a.threshold_currency,
        "active": a.active, "last_triggered_at": iso(a.last_triggered_at),
    }


def serialize_tracked_many(db: Session, items: list[TrackedProduct], rates: Rates | None = None,
                           display_currency: str | None = None) -> list[dict]:
    listing_ids = list({t.listing_id for t in items})
    prices = latest_prices(db, listing_ids)
    promos = active_promos(db, listing_ids)
    out = []
    for t in items:
        li = t.listing
        obs = prices.get(t.listing_id)
        cur_price = D(obs.price) if obs else None
        currency = obs.currency if obs else li.currency
        ps = promos.get(t.listing_id, [])
        store_discount = next((p.discount_pct for p in ps if p.origin == "store" and p.discount_pct is not None), None)
        d = {
            "id": t.id, "listing_id": li.id, "title": li.title or "Producto sin nombre", "title_is_guess": li.title_is_guess,
            "image_url": li.image_url, "store_key": li.store.key, "store_name": li.store.name, "url": li.canonical_url,
            "state": t.state, "state_label": STATE_LABELS.get(t.state, t.state), "state_detail": t.state_detail,
            "price_current": _s(cur_price), "price_initial": _s(t.initial_price), "currency": currency,
            "initial_currency": t.initial_currency,
            "target_price": _s(t.target_price), "target_currency": t.target_currency or currency,
            "change_from_initial_pct": _s(pct_change(D(t.initial_price), cur_price)) if (
                t.initial_price is not None and t.initial_currency == currency) else None,
            "verified_discount_pct": _s(store_discount),  # sólo si la tienda lo anuncia
            "has_promotion": bool(ps),
            "available": obs.available if obs else None,
            "last_checked_at": iso(t.last_checked_at), "priority": t.priority, "notes": t.notes,
            "list_name": t.list_name, "category": t.category, "archived": t.archived, "purchased": t.purchased,
            "purchased_price": _s(t.purchased_price), "paused": t.paused, "created_at": iso(t.created_at),
            "updated_at": iso(t.updated_at), "deleted": t.deleted,
            "alerts": [serialize_alert(a) for a in t.alerts],
        }
        d["converted"] = None
        if display_currency and currency and display_currency.upper() != currency.upper():
            c_cur = _conv(cur_price, currency, display_currency, rates)
            c_ini = _conv(t.initial_price, t.initial_currency or currency, display_currency, rates)
            c_tgt = _conv(t.target_price, t.target_currency or currency, display_currency, rates) \
                if t.target_price is not None else None
            if (cur_price is None or c_cur) and rates is not None and rates.has(display_currency) and rates.has(currency):
                ref = c_cur or c_ini or c_tgt
                d["converted"] = {
                    "currency": display_currency.upper(),
                    "current": _s(c_cur.amount) if c_cur else None,
                    "initial": _s(c_ini.amount) if c_ini else None,
                    "target": _s(c_tgt.amount) if c_tgt else None,
                    "rate": _s(ref.rate) if ref else None,
                    "as_of": iso(rates.fetched_at), "source": rates.source,
                }
            else:
                d["fx_error"] = "No hay tasa de cambio disponible; se muestran los importes en la moneda original."
        out.append(d)
    return out


def serialize_tracked(db: Session, t: TrackedProduct, rates: Rates | None = None, display: str | None = None) -> dict:
    return serialize_tracked_many(db, [t], rates, display)[0]


def potential_saving(t: TrackedProduct, cur: Decimal | None, currency: str | None) -> Decimal | None:
    """Ahorro POTENCIAL (no real): precio registrado al añadir menos el precio actual, si bajó."""
    if cur is None or t.initial_price is None or t.initial_currency != currency:
        return None
    diff = D(t.initial_price) - cur
    return diff if diff > 0 else None
