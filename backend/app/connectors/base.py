"""Contrato común de los conectores de tiendas.

Reglas del proyecto:
- Sólo APIs oficiales, proveedores autorizados o fuentes públicas cuyo uso esté permitido.
- Nada de eludir autenticación, protecciones anti-bot ni límites de acceso.
- Si un conector no puede dar un precio real, lanza `SourceUnavailable`; nunca se inventan datos.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


class ConnectorError(Exception):
    """Fallo temporal (red, 5xx, límite de peticiones…). Se reintenta con backoff."""

    def __init__(self, message: str, retry_after_seconds: int | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class SourceUnavailable(Exception):
    """No existe una fuente de datos permitida/configurada para esta publicación."""


class ProductGone(Exception):
    """La tienda indica que la publicación ya no existe."""


@dataclass
class PromoInfo:
    kind: str  # discount | free_shipping | quantity_discount | limited_time | seller_offer
    description: str
    previous_price: Decimal | None = None
    discount_pct: Decimal | None = None
    expires_at: datetime | None = None
    conditions: str | None = None


@dataclass
class CouponInfo:
    code: str
    description: str | None = None
    conditions: str | None = None
    verified: bool = False  # sólo True si la API de la tienda lo confirma
    expires_at: datetime | None = None


@dataclass
class ProductInfo:
    source: str  # identificador de la fuente real de los datos, p. ej. "mercadolibre_api"
    title: str | None = None
    image_url: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    available: bool | None = None
    shipping_cost: Decimal | None = None  # None = desconocido (no es lo mismo que 0)
    seller: str | None = None
    condition: str | None = None
    brand: str | None = None
    model: str | None = None
    gtin: str | None = None
    attributes: dict | None = None
    promotions: list[PromoInfo] = field(default_factory=list)
    coupons: list[CouponInfo] = field(default_factory=list)


@dataclass
class ListingRef:
    external_id: str
    variant_key: str
    canonical_url: str


@dataclass
class SearchHit:
    store_key: str
    title: str
    url: str
    price: Decimal | None
    currency: str | None
    image_url: str | None = None
    gtin: str | None = None
    brand: str | None = None
    model: str | None = None


class Connector(ABC):
    key: str = ""
    name: str = ""
    docs: str = ""  # explicación corta del estado real de la integración

    @abstractmethod
    def configured(self) -> bool:
        """¿Hay credenciales/acceso para consultar precios reales?"""

    def status(self) -> str:
        """integrated | needs_credentials | unavailable. 'integrated' = hay credenciales; ver docs/stores.md para el estado de pruebas."""
        return "integrated" if self.configured() else "needs_credentials"

    @abstractmethod
    def fetch(self, ref: ListingRef) -> ProductInfo:
        """Consulta la publicación. Lanza ConnectorError, SourceUnavailable o ProductGone."""

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        """Búsqueda opcional para el comparador. Por defecto no soportada."""
        return []
