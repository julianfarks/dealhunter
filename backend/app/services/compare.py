"""Comparador entre tiendas: sólo marca como "exacta" la coincidencia confirmada por GTIN."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..connectors import get_connector
from ..connectors.base import ConnectorError, SourceUnavailable
from ..currency import RateUnavailable, Rates, convert
from ..models import PriceObservation, StoreListing

COMPARE_KEYS = ("color", "capacity", "capacidad", "size", "talla", "storage", "memory", "model")


def variant_match(a: dict | None, b: dict | None) -> tuple[str, list[str]]:
    """('same'|'different'|'unknown', claves que difieren)."""
    if not a or not b:
        return "unknown", []
    na = {k.lower(): str(v).strip().lower() for k, v in a.items() if v is not None}
    nb = {k.lower(): str(v).strip().lower() for k, v in b.items() if v is not None}
    shared = [k for k in na if k in nb and k in COMPARE_KEYS]
    if not shared:
        return "unknown", []
    diffs = [k for k in shared if na[k] != nb[k]]
    return ("different" if diffs else "same"), diffs


def latest_observation(db: Session, listing_id: int) -> PriceObservation | None:
    return db.scalar(
        select(PriceObservation).where(PriceObservation.listing_id == listing_id, PriceObservation.price.is_not(None))
        .order_by(PriceObservation.observed_at.desc(), PriceObservation.id.desc()).limit(1)
    )


@dataclass
class Offer:
    listing: StoreListing
    store_key: str
    store_name: str
    price: Decimal | None
    currency: str | None
    shipping: Decimal | None
    total_estimated: Decimal | None
    available: bool | None
    match: str  # exact | approximate
    notes: list[str]
    checked_at: object | None
    price_in_base: Decimal | None  # precio convertido a la moneda de la publicación base (None si no se pudo)


def _estimate_total(price: Decimal | None, shipping: Decimal | None) -> Decimal | None:
    if price is None:
        return None
    return price + (shipping or Decimal(0))


def related_offers(db: Session, base: StoreListing, rates: Rates | None = None) -> list[Offer]:
    """Otras publicaciones de la base de datos vinculadas al mismo producto genérico."""
    if base.product_id is None:
        return []
    others = db.scalars(
        select(StoreListing).where(StoreListing.product_id == base.product_id, StoreListing.id != base.id)
    ).all()
    out: list[Offer] = []
    for o in others:
        obs = latest_observation(db, o.id)
        notes: list[str] = []
        exact = bool(base.gtin and o.gtin and base.gtin == o.gtin)
        vm, diffs = variant_match(base.attributes, o.attributes)
        if vm == "different":
            exact = False
            notes.append("Variante distinta (" + ", ".join(diffs) + "): comparación aproximada")
        elif vm == "unknown":
            notes.append("No se pudo confirmar que la variante sea la misma")
            exact = False if not exact else exact
        if not exact:
            notes.append("No se confirmó que sea exactamente el mismo artículo")
        if o.condition and base.condition and o.condition != base.condition:
            exact = False
            notes.append(f"Estado distinto: {o.condition} vs {base.condition}")
        price = obs.price if obs else None
        cur = obs.currency if obs else None
        shipping = obs.shipping_cost if obs else None
        if shipping is None:
            notes.append("Costo de envío desconocido: el total es sólo estimado")
        in_base = None
        if price is not None and cur and base.currency:
            try:
                in_base = convert(price, cur, base.currency, rates).amount if rates else (
                    price if cur == base.currency else None)
            except RateUnavailable:
                in_base = None
        out.append(Offer(
            listing=o, store_key=o.store.key, store_name=o.store.name, price=price, currency=cur, shipping=shipping,
            total_estimated=_estimate_total(price, shipping), available=obs.available if obs else None,
            match="exact" if exact else "approximate", notes=notes, checked_at=obs.observed_at if obs else None,
            price_in_base=in_base,
        ))
    out.sort(key=lambda x: (x.price_in_base is None, x.price_in_base or Decimal(0)))
    return out


def external_candidates(base: StoreListing, limit: int = 3) -> tuple[list[dict], list[str]]:
    """Búsqueda opcional en conectores con credenciales. Todo resultado se marca como aproximado salvo GTIN igual."""
    query = " ".join(x for x in [(base.title or "")] if x).strip()
    errors: list[str] = []
    hits: list[dict] = []
    if not query:
        return hits, ["Sin título para buscar el mismo artículo en otras tiendas"]
    for key in ("mercadolibre", "ebay"):
        if key == base.store.key:
            continue
        conn = get_connector(key)
        if not conn.configured():
            continue
        try:
            for h in conn.search(query, limit):
                exact = bool(base.gtin and h.gtin and base.gtin == h.gtin)
                hits.append({
                    "store": key, "title": h.title, "url": h.url,
                    "price": str(h.price) if h.price is not None else None, "currency": h.currency,
                    "image_url": h.image_url, "match": "exact" if exact else "approximate",
                    "notes": [] if exact else ["Resultado de búsqueda por título: no confirmado como el mismo artículo"],
                })
        except (ConnectorError, SourceUnavailable) as e:
            errors.append(f"{conn.name}: {e}")
    return hits, errors
