"""Creación/obtención de publicaciones y resolución de enlaces cortos."""
from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..connectors.base import ConnectorError
from ..connectors.http import get_client
from ..models import Product, Store, StoreListing
from ..urlutil import (
    SHORT_HOSTS, InvalidUrl, ParsedUrl, assert_public_host, guess_title, parse_product_url, validate_url,
)

STORE_NAMES = {
    "amazon": "Amazon", "aliexpress": "AliExpress", "mercadolibre": "Mercado Libre", "temu": "Temu",
    "ebay": "eBay", "generic": "Tienda independiente",
}


class ShortLinkError(Exception):
    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


def get_or_create_store(db: Session, key: str) -> Store:
    store = db.scalar(select(Store).where(Store.key == key))
    if store:
        return store
    try:
        with db.begin_nested():
            store = Store(key=key, name=STORE_NAMES.get(key, key))
            db.add(store)
            db.flush()
    except IntegrityError:
        store = db.scalar(select(Store).where(Store.key == key))
    return store


def resolve_short_link(url: str) -> ParsedUrl:
    """Sigue (con guardia SSRF en cada salto) un enlace corto de tienda conocida hasta llegar al producto."""
    client = get_client()
    current = url
    for _ in range(6):
        try:
            current, host = validate_url(current)
            assert_public_host(host, urlsplit(current).port)
        except InvalidUrl as e:
            raise ShortLinkError(str(e), retryable=False) from e
        try:
            resp = client.get(current, headers={"Accept": "text/html"}, follow_redirects=False)
        except Exception as e:
            raise ShortLinkError("No se pudo abrir el enlace corto (error de red)", retryable=True) from e
        if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
            current = urljoin(current, resp.headers["location"])
            host = (urlsplit(current).hostname or "").lower()
            if host not in SHORT_HOSTS:
                try:
                    return parse_product_url(current)
                except InvalidUrl as e:
                    raise ShortLinkError(str(e), retryable=False) from e
            continue
        if resp.status_code >= 500 or resp.status_code == 429:
            raise ShortLinkError("La tienda no respondió al resolver el enlace corto", retryable=True)
        break
    raise ShortLinkError("No se pudo resolver el enlace corto", retryable=False)


def parse_or_resolve(raw_url: str) -> ParsedUrl:
    parsed = parse_product_url(raw_url)
    if parsed.needs_resolution:
        return resolve_short_link(parsed.original_url)
    return parsed


def upsert_listing(db: Session, parsed: ParsedUrl) -> tuple[StoreListing, bool]:
    store = get_or_create_store(db, parsed.store_key)
    q = select(StoreListing).where(
        StoreListing.store_id == store.id,
        StoreListing.external_id == parsed.external_id,
        StoreListing.variant_key == parsed.variant_key,
    )
    existing = db.scalar(q)
    if existing:
        return existing, False
    title = guess_title(parsed.original_url, parsed.store_key)
    try:
        with db.begin_nested():
            listing = StoreListing(
                store_id=store.id, external_id=parsed.external_id, variant_key=parsed.variant_key,
                canonical_url=parsed.canonical_url, title=title, title_is_guess=True,
            )
            db.add(listing)
            db.flush()
        return listing, True
    except IntegrityError:
        return db.scalar(q), False


def link_product(db: Session, listing: StoreListing, brand: str | None, model: str | None, gtin: str | None,
                 name: str | None) -> None:
    """Asocia la publicación a un producto genérico por GTIN (exacto) o por marca+modelo (aproximado)."""
    gtin = (gtin or "").strip() or None
    brand_n = (brand or "").strip().lower() or None
    model_n = (model or "").strip().lower() or None
    if gtin:
        listing.gtin = gtin
    product = None
    if gtin:
        product = db.scalar(select(Product).where(Product.gtin == gtin))
    if product is None and brand_n and model_n:
        product = db.scalar(select(Product).where(Product.brand == brand_n, Product.model == model_n))
    if product is None and (gtin or (brand_n and model_n)):
        product = Product(brand=brand_n, model=model_n, gtin=gtin, name=(name or listing.title or "Producto")[:500])
        db.add(product)
        db.flush()
    if product is not None:
        listing.product_id = product.id
