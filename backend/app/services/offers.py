"""Sección Ofertas: sólo oportunidades con datos verificables y el origen siempre explícito."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Coupon, PriceObservation, Promotion, TrackedProduct, utcnow
from ..util import D, iso

REF_WINDOW_DAYS = 90
REF_MIN_OBS = 3
REF_MIN_SPAN_DAYS = 3
INFLATED_REFERENCE_FACTOR = Decimal("1.05")

ORIGIN_LABELS = {
    "store": "Descuento anunciado por la tienda",
    "history": "Reducción calculada a partir del historial de DealHunter",
    "coupon": "Cupón",
}


def coupon_status(c: Coupon, now: datetime | None = None) -> str:
    """verified | unverified | expired. Un cupón sin verificación NUNCA se presenta como válido."""
    now = now or utcnow()
    if c.expires_at is not None and c.expires_at <= now:
        return "expired"
    return "verified" if c.verified_at is not None else "unverified"


def reference_check(db: Session, listing_id: int, currency: str | None, previous_price: Decimal | None,
                    now: datetime) -> str:
    """¿El 'precio anterior' que anuncia la tienda coincide con lo que hemos observado?"""
    if previous_price is None or not currency:
        return "insufficient_history"
    since = now - timedelta(days=REF_WINDOW_DAYS)
    rows = db.execute(select(PriceObservation.price, PriceObservation.observed_at).where(
        PriceObservation.listing_id == listing_id, PriceObservation.price.is_not(None),
        PriceObservation.currency == currency, PriceObservation.observed_at >= since)).all()
    if len(rows) < REF_MIN_OBS or (max(r[1] for r in rows) - min(r[1] for r in rows)) < timedelta(days=REF_MIN_SPAN_DAYS):
        return "insufficient_history"
    top = max(D(r[0]) for r in rows)
    return "inflated_reference" if D(previous_price) > top * INFLATED_REFERENCE_FACTOR else "consistent"


REFERENCE_LABELS = {
    "consistent": "El precio anterior es coherente con el historial observado",
    "inflated_reference": "El precio anterior anunciado es mayor que cualquier precio que hayamos observado: "
                          "el descuento real podría ser menor",
    "insufficient_history": "Aún no hay historial suficiente para comprobar el precio anterior",
}


def list_offers(db: Session, user_id: int, now: datetime | None = None) -> list[dict]:
    now = now or utcnow()
    items = db.scalars(select(TrackedProduct).where(
        TrackedProduct.user_id == user_id, TrackedProduct.deleted.is_(False),
        TrackedProduct.archived.is_(False), TrackedProduct.purchased.is_(False))).all()
    out: list[dict] = []
    for t in items:
        li = t.listing
        base = {"tracked_id": t.id, "title": li.title or "Producto", "store_name": li.store.name,
                "store_key": li.store.key, "image_url": li.image_url, "url": li.canonical_url}
        for p in db.scalars(select(Promotion).where(Promotion.listing_id == li.id, Promotion.active.is_(True))):
            entry = {
                **base, "type": "promotion", "kind": p.kind, "origin": p.origin, "origin_label": ORIGIN_LABELS[p.origin],
                "description": p.description, "current_price": None if p.current_price is None else str(p.current_price),
                "previous_price": None if p.previous_price is None else str(p.previous_price),
                "discount_pct": None if p.discount_pct is None else str(p.discount_pct), "currency": p.currency,
                "checked_at": iso(p.checked_at), "expires_at": iso(p.expires_at),  # sólo si la tienda lo confirmó
                "conditions": p.conditions, "verified": p.origin == "store",
            }
            if p.origin == "store" and p.previous_price is not None:
                chk = reference_check(db, li.id, p.currency, p.previous_price, now)
                entry["reference_check"], entry["reference_note"] = chk, REFERENCE_LABELS[chk]
            out.append(entry)
        for c in db.scalars(select(Coupon).where(
                (Coupon.listing_id == li.id) | ((Coupon.listing_id.is_(None)) & (Coupon.store_id == li.store_id)))):
            st = coupon_status(c, now)
            if st == "expired":
                continue
            out.append({
                **base, "type": "coupon", "kind": "coupon", "origin": "coupon", "origin_label": ORIGIN_LABELS["coupon"],
                "code": c.code, "description": c.description or "Cupón", "conditions": c.conditions,
                "verified": st == "verified", "coupon_status": st,
                "verification_note": ("Verificado por " + (c.verification_source or "la tienda")) if st == "verified"
                else "No verificado: no lo marques como válido hasta comprobarlo en la tienda",
                "checked_at": iso(c.verified_at), "expires_at": iso(c.expires_at),
            })
    out.sort(key=lambda e: (e["type"] != "promotion", -float(e.get("discount_pct") or 0)))
    return out
