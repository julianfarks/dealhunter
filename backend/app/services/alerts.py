"""Motor de reglas de alerta con anti-duplicados y rearmado.

Para las reglas basadas en precio (bajada, %, objetivo, mínimo histórico, presupuesto) una alerta se dispara una
vez; no vuelve a dispararse mientras el precio siga igual o peor; si aparece un precio estrictamente mejor se
vuelve a notificar; si el precio deja de cumplir la condición, la alerta se rearma.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..connectors.base import ProductInfo
from ..currency import RateUnavailable, Rates, convert, quantize
from ..models import (
    AlertKind, Coupon, Notification, PriceAlert, PriceObservation, Promotion, StoreListing, TrackedProduct, User,
)
from ..util import D, fmt_money
from .compare import related_offers
from .notifier import create_notification

PRICE_KINDS = {
    AlertKind.ANY_DROP.value, AlertKind.PCT_DROP.value, AlertKind.TARGET_PRICE.value,
    AlertKind.HISTORIC_LOW.value, AlertKind.TOTAL_BUDGET.value,
}


@dataclass
class CheckContext:
    listing: StoreListing
    prev: PriceObservation | None  # última observación ANTES de esta comprobación
    obs: PriceObservation | None  # observación guardada ahora (None si no cambió nada)
    info: ProductInfo
    new_promos: list[Promotion] = field(default_factory=list)
    rates: Rates | None = None
    now: datetime | None = None


def _to(cur: Decimal | None, src: str | None, dst: str | None, rates: Rates | None) -> Decimal | None:
    """Convierte `cur` de `src` a `dst` (None si no hay tasa). Si dst es None se asume la moneda de origen."""
    if cur is None:
        return None
    if not dst or not src or dst == src:
        return cur
    if rates is None:
        return None
    try:
        return convert(cur, src, dst, rates).amount
    except RateUnavailable:
        return None


def _fire_gate(alert: PriceAlert, cond: bool, cur: Decimal, now: datetime) -> bool:
    if not cond:
        alert.armed, alert.last_triggered_price = True, None
        return False
    last = alert.last_triggered_price
    if alert.armed or last is None or cur < D(last):
        alert.armed, alert.last_triggered_price, alert.last_triggered_at = False, cur, now
        return True
    return False


def _payload(tracked: TrackedProduct, listing: StoreListing, kind: str, cur, prev, currency) -> dict:
    c = quantize(D(cur)) if cur is not None else None
    p = quantize(D(prev)) if prev is not None else None
    return {
        "product_id": tracked.id, "kind": kind, "url": listing.canonical_url, "currency": currency,
        "current_price": str(c) if c is not None else None,
        "previous_price": str(p) if p is not None else None,
        "difference": str(quantize(p - c)) if (c is not None and p is not None) else None,
    }


def _name(listing: StoreListing) -> str:
    return listing.title or "Tu producto"


def _saving_suffix(tracked: TrackedProduct, cur: Decimal, currency: str | None) -> str:
    ini = tracked.initial_price
    if ini is not None and tracked.initial_currency == currency and D(ini) > cur:
        return f" Ahorro frente al precio registrado: {fmt_money(D(ini) - cur, currency)}."
    return ""


def evaluate_alerts(db: Session, user: User, tracked: TrackedProduct, ctx: CheckContext) -> list[Notification]:
    now = ctx.now
    listing, info = ctx.listing, ctx.info
    cur = info.price
    currency = info.currency or listing.currency
    prev_price = ctx.prev.price if (ctx.prev is not None and ctx.prev.currency == currency) else None
    prev_price = D(prev_price) if prev_price is not None else None
    created: list[Notification] = []
    ev = ctx.obs.observed_at.isoformat() if ctx.obs is not None else "-"

    def notify(kind: str, title: str, body: str, dedupe: str, prev=None) -> None:
        n = create_notification(
            db, user, tracked, kind, title, body, _payload(tracked, listing, kind, cur, prev, currency),
            f"{kind}:{tracked.id}:{dedupe}", now,
        )
        if n is not None:
            created.append(n)

    for alert in tracked.alerts:
        if not alert.active or tracked.paused or tracked.archived or tracked.deleted:
            continue
        k = alert.kind
        name = _name(listing)

        if k in PRICE_KINDS:
            if cur is None:
                continue
            cur = D(cur)
            if k == AlertKind.ANY_DROP.value:
                cond = prev_price is not None and cur < prev_price
                if _fire_gate(alert, cond, cur, now):
                    notify(k, "¡Oferta detectada!",
                           f"{name} bajó de {fmt_money(prev_price, currency)} a {fmt_money(cur, currency)}."
                           f" Diferencia: {fmt_money(prev_price - cur, currency)}." + _saving_suffix(tracked, cur, currency),
                           f"{alert.id}:{cur}:{ev}", prev_price)
            elif k == AlertKind.PCT_DROP.value:
                ini = tracked.initial_price
                pct = alert.threshold
                cond = False
                drop = None
                if ini is not None and pct is not None and tracked.initial_currency == currency and D(ini) > 0:
                    drop = (D(ini) - cur) / D(ini) * 100
                    cond = drop >= D(pct)
                if _fire_gate(alert, cond, cur, now):
                    notify(k, "¡Bajó el porcentaje que querías!",
                           f"{name} está {quantize(drop, 1)}% por debajo del precio registrado "
                           f"({fmt_money(D(ini), currency)}): ahora {fmt_money(cur, currency)}.",
                           f"{alert.id}:{cur}:{ev}", D(ini))
            elif k == AlertKind.TARGET_PRICE.value:
                thr = alert.threshold if alert.threshold is not None else tracked.target_price
                thr_cur = alert.threshold_currency if alert.threshold is not None else tracked.target_currency
                cmp_price = _to(cur, currency, thr_cur, ctx.rates) if thr is not None else None
                cond = thr is not None and cmp_price is not None and cmp_price <= D(thr)
                if _fire_gate(alert, cond, cur, now):
                    objetivo = fmt_money(D(thr), thr_cur or currency)
                    if prev_price is not None and prev_price > cur:
                        body = (f"{name} bajó de {fmt_money(prev_price, currency)} a {fmt_money(cur, currency)} "
                                f"y alcanzó tu precio objetivo ({objetivo}). "
                                f"Diferencia: {fmt_money(prev_price - cur, currency)}.")
                    else:
                        body = f"{name} está en {fmt_money(cur, currency)}, en o por debajo de tu objetivo ({objetivo})."
                    notify(k, "¡Alcanzó tu precio objetivo!", body + _saving_suffix(tracked, cur, currency),
                           f"{alert.id}:{cur}:{ev}", prev_price)
            elif k == AlertKind.HISTORIC_LOW.value:
                q = select(func.min(PriceObservation.price), func.count(PriceObservation.id)).where(
                    PriceObservation.listing_id == listing.id, PriceObservation.price.is_not(None),
                    PriceObservation.currency == currency,
                )
                if ctx.obs is not None:
                    q = q.where(PriceObservation.id != ctx.obs.id)
                lowest, count = db.execute(q).one()
                cond = lowest is not None and count >= 2 and cur < D(lowest)
                if _fire_gate(alert, cond, cur, now):
                    notify(k, "¡Mínimo histórico registrado!",
                           f"{name} está en {fmt_money(cur, currency)}, el precio más bajo que hemos registrado "
                           f"(anterior mínimo: {fmt_money(D(lowest), currency)}; historial de {count + 1} observaciones).",
                           f"{alert.id}:{cur}:{ev}", D(lowest))
            elif k == AlertKind.TOTAL_BUDGET.value:
                shipping = info.shipping_cost
                total = cur + (D(shipping) if shipping is not None else Decimal(0))
                budget = alert.threshold
                cmp_total = _to(total, currency, alert.threshold_currency, ctx.rates) if budget is not None else None
                cond = budget is not None and cmp_total is not None and cmp_total <= D(budget)
                if _fire_gate(alert, cond, cur, now):
                    ship_txt = (f" (incluye envío {fmt_money(D(shipping), currency)})" if shipping is not None
                                else " (sin costo de envío conocido)")
                    notify(k, "Dentro de tu presupuesto",
                           f"{name}: total estimado {fmt_money(total, currency)}{ship_txt}. "
                           "Es una estimación: el total definitivo lo confirma la tienda al pagar.",
                           f"{alert.id}:{cur}:{ev}", None)

        elif k == AlertKind.PROMOTION.value:
            for p in ctx.new_promos:
                if p.origin != "store":
                    continue
                notify(k, "Promoción detectada", f"{name}: {p.description}"
                       + (f" Precio anterior {fmt_money(D(p.previous_price), currency)}, ahora "
                          f"{fmt_money(D(p.current_price), currency)}." if p.previous_price and p.current_price else ""),
                       f"{p.fingerprint}")

        elif k == AlertKind.COUPON.value:
            coupons = db.scalars(select(Coupon).where(
                Coupon.verified_at.is_not(None),
                (Coupon.listing_id == listing.id) | ((Coupon.listing_id.is_(None)) & (Coupon.store_id == listing.store_id)),
            )).all()
            for c in coupons:
                if c.expires_at is not None and c.expires_at <= now:
                    continue
                notify(k, "Cupón verificado", f"Cupón {c.code} verificado para {name}."
                       + (f" Condiciones: {c.conditions}" if c.conditions else ""), f"{c.id}")

        elif k == AlertKind.BACK_IN_STOCK.value:
            if ctx.prev is not None and ctx.prev.available is False and info.available is True:
                notify(k, "¡Volvió a estar disponible!", f"{name} vuelve a estar disponible"
                       + (f" a {fmt_money(cur, currency)}." if cur is not None else "."),
                       f"{ctx.obs.id if ctx.obs else now.date().isoformat()}")

        elif k == AlertKind.BETTER_ELSEWHERE.value:
            if cur is None:
                continue
            for off in related_offers(db, listing, ctx.rates):
                if off.price_in_base is not None and off.price_in_base < D(cur) * Decimal("0.99"):
                    aprox = " (coincidencia aproximada)" if off.match != "exact" else ""
                    notify(k, "Mejor oferta en otra tienda",
                           f"{off.store_name}{aprox} publica {fmt_money(off.price, off.currency)} frente a "
                           f"{fmt_money(D(cur), currency)} en la tienda que vigilas ({name}). "
                           "Compara costos de envío antes de decidir.",
                           f"{off.listing.id}:{off.price}")
                    break
    return created
