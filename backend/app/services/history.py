"""Historial de precios: rangos adaptados a los datos reales, estadísticas y avisos de historial limitado."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..currency import quantize
from ..models import PriceObservation, Promotion, StoreListing, utcnow
from ..util import D, iso, pct_change

RANGES = {"7d": 7, "30d": 30, "90d": 90, "6m": 182, "1y": 365}
MIN_POINTS_FOR_AVERAGE = 5
LIMITED_POINTS = 5
LIMITED_DAYS = 3


def available_ranges(first_at: datetime | None, now: datetime) -> list[str]:
    """7d siempre; cada rango mayor sólo si los datos son más antiguos que el rango anterior."""
    out = ["7d"]
    if first_at is None:
        return out
    age_days = (now - first_at).total_seconds() / 86400
    prev_days = RANGES["7d"]
    for key in ("30d", "90d", "6m", "1y"):
        if age_days > prev_days:
            out.append(key)
        prev_days = RANGES[key]
    return out


def build_history(db: Session, listing: StoreListing, range_key: str = "30d", now: datetime | None = None) -> dict:
    now = now or utcnow()
    all_rows = db.scalars(select(PriceObservation).where(PriceObservation.listing_id == listing.id)
                          .order_by(PriceObservation.observed_at, PriceObservation.id)).all()
    priced = [o for o in all_rows if o.price is not None]
    first_at = priced[0].observed_at if priced else None
    avail = available_ranges(first_at, now)
    requested = range_key if range_key in RANGES else "30d"
    effective = requested if requested in avail else avail[-1]
    since = now - timedelta(days=RANGES[effective])

    currency = priced[-1].currency if priced else listing.currency
    same_cur = [o for o in priced if o.currency == currency]  # nunca se mezclan monedas en las estadísticas
    window = [o for o in same_cur if o.observed_at >= since]

    points = []
    prev_price: Decimal | None = None
    for o in window:
        p = D(o.price)
        ch = pct_change(prev_price, p) if prev_price is not None else None
        points.append({
            "at": iso(o.observed_at), "price": str(p), "currency": o.currency, "available": o.available,
            "source": o.source, "change_pct": str(ch) if ch is not None else None,
        })
        prev_price = p

    stats: dict = {}
    warnings: list[str] = []
    if same_cur:
        prices = [D(o.price) for o in window] or [D(same_cur[-1].price)]
        current, first = D(same_cur[-1].price), D(same_cur[0].price)
        stats = {
            "current": str(current), "first_observed": str(first), "first_observed_at": iso(same_cur[0].observed_at),
            "min": str(min(prices)), "max": str(max(prices)),
            "min_all_time": str(min(D(o.price) for o in same_cur)), "max_all_time": str(max(D(o.price) for o in same_cur)),
            "average": str(quantize(sum(prices) / len(prices), 2)) if len(prices) >= MIN_POINTS_FOR_AVERAGE else None,
            "change_from_first_pct": str(pct_change(first, current)) if pct_change(first, current) is not None else None,
            "observations_total": len(same_cur), "observations_in_range": len(window),
        }
        span_days = (same_cur[-1].observed_at - same_cur[0].observed_at).total_seconds() / 86400
        if len(same_cur) < LIMITED_POINTS or span_days < LIMITED_DAYS:
            warnings.append(
                "El historial todavía es limitado: sólo incluye observaciones desde que empezamos a vigilar "
                "este producto. Aún no es suficiente para saber si el precio actual es bueno.")
        if stats["average"] is None:
            warnings.append("Aún no hay suficientes datos para calcular un promedio fiable.")
    else:
        warnings.append("Todavía no hay precios registrados para este producto.")
    if effective != requested:
        warnings.append(f"Aún no hay datos suficientes para el periodo {requested}; se muestra {effective}.")

    promos = db.scalars(select(Promotion).where(Promotion.listing_id == listing.id, Promotion.detected_at >= since)
                        .order_by(Promotion.detected_at.desc())).all()
    return {
        "range": effective, "requested_range": requested, "available_ranges": avail, "currency": currency,
        "points": points, "stats": stats, "warnings": warnings,
        "promotions": [{
            "id": p.id, "kind": p.kind, "origin": p.origin, "description": p.description,
            "previous_price": str(p.previous_price) if p.previous_price is not None else None,
            "current_price": str(p.current_price) if p.current_price is not None else None,
            "discount_pct": str(p.discount_pct) if p.discount_pct is not None else None,
            "detected_at": iso(p.detected_at),
        } for p in promos],
    }
