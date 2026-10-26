"""Modelo de datos.

Convenciones:
- Todas las fechas se guardan en UTC *sin* zona horaria (naive UTC) para que SQLite y PostgreSQL se comporten igual.
- Los importes son Numeric(14, 2).
- `Product` es el artículo genérico; `StoreListing` es una publicación concreta en una tienda.
  Los datos de la publicación (precio, URL, vendedor) NUNCA se mezclan con los del producto genérico.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TrackingState(str, enum.Enum):
    ACTIVE = "active"  # Seguimiento automático activo
    WAITING_FIRST_CHECK = "waiting_first_check"  # Esperando la primera consulta
    TEMPORARILY_FAILED = "temporarily_failed"  # Actualización temporalmente fallida
    PRICE_UNAVAILABLE = "price_unavailable"  # Precio no disponible
    NEEDS_SOURCE = "needs_source"  # Requiere una fuente de datos compatible
    PAUSED = "paused"  # Seguimiento pausado
    UNAVAILABLE_IN_STORE = "unavailable_in_store"  # Producto no disponible en la tienda


class AlertKind(str, enum.Enum):
    ANY_DROP = "any_drop"
    PCT_DROP = "pct_drop"
    TARGET_PRICE = "target_price"
    HISTORIC_LOW = "historic_low"
    COUPON = "coupon"
    PROMOTION = "promotion"
    BACK_IN_STOCK = "back_in_stock"
    BETTER_ELSEWHERE = "better_elsewhere"
    TOTAL_BUDGET = "total_budget"


PREMIUM_ALERT_KINDS = {AlertKind.BETTER_ELSEWHERE, AlertKind.TOTAL_BUDGET, AlertKind.COUPON}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    tier: Mapped[str] = mapped_column(String(16), default="free")
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # sube al cerrar sesión en todos lados
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    preferences: Mapped["UserPreference"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class Store(Base):
    __tablename__ = "stores"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True)  # amazon, aliexpress, mercadolibre, temu, ebay, generic
    name: Mapped[str] = mapped_column(String(64))


class Product(Base):
    """Artículo genérico (marca/modelo/GTIN) que puede tener varias publicaciones."""

    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(160))
    gtin: Mapped[str | None] = mapped_column(String(14), index=True)
    name: Mapped[str] = mapped_column(String(500))
    category: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    listings: Mapped[list["StoreListing"]] = relationship(back_populates="product")


class StoreListing(Base):
    __tablename__ = "store_listings"
    __table_args__ = (
        UniqueConstraint("store_id", "external_id", "variant_key", name="uq_listing_identity"),
        Index("ix_listing_product", "product_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    external_id: Mapped[str] = mapped_column(String(200))
    variant_key: Mapped[str] = mapped_column(String(200), default="")  # "" = sin variante
    canonical_url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str | None] = mapped_column(String(500))
    image_url: Mapped[str | None] = mapped_column(String(2000))
    currency: Mapped[str | None] = mapped_column(String(3))
    seller: Mapped[str | None] = mapped_column(String(200))
    condition: Mapped[str | None] = mapped_column(String(40))  # new / used / refurbished
    gtin: Mapped[str | None] = mapped_column(String(14), index=True)
    attributes: Mapped[dict | None] = mapped_column(JSON)  # color, capacidad, talla…
    title_is_guess: Mapped[bool] = mapped_column(Boolean, default=True)  # True = deducido de la URL, no de la tienda
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    store: Mapped[Store] = relationship()
    product: Mapped[Product | None] = relationship(back_populates="listings")


class ProductVariant(Base):
    __tablename__ = "product_variants"
    __table_args__ = (UniqueConstraint("product_id", "sku", name="uq_variant_sku"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("store_listings.id", ondelete="SET NULL"))
    sku: Mapped[str] = mapped_column(String(120))
    attributes: Mapped[dict | None] = mapped_column(JSON)


class TrackedProduct(Base):
    """Elemento del carrito universal de un usuario."""

    __tablename__ = "tracked_products"
    __table_args__ = (
        UniqueConstraint("user_id", "listing_id", name="uq_user_listing"),
        Index("ix_tracked_user_updated", "user_id", "updated_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("store_listings.id"))
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    target_currency: Mapped[str | None] = mapped_column(String(3))  # None = moneda de la publicación
    initial_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    initial_currency: Mapped[str | None] = mapped_column(String(3))
    state: Mapped[str] = mapped_column(String(32), default=TrackingState.WAITING_FIRST_CHECK.value)
    state_detail: Mapped[str | None] = mapped_column(String(300))
    priority: Mapped[int] = mapped_column(Integer, default=0)  # 0 normal, 1 alta, 2 urgente
    notes: Mapped[str | None] = mapped_column(Text)
    list_name: Mapped[str | None] = mapped_column(String(80))
    category: Mapped[str | None] = mapped_column(String(120))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    purchased: Mapped[bool] = mapped_column(Boolean, default=False)
    purchased_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)  # tombstone para sincronización
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    listing: Mapped[StoreListing] = relationship()
    alerts: Mapped[list["PriceAlert"]] = relationship(back_populates="tracked", cascade="all, delete-orphan")


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (Index("ix_obs_listing_time", "listing_id", "observed_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("store_listings.id", ondelete="CASCADE"))
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    shipping_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    available: Mapped[bool | None] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(64))  # p. ej. "mercadolibre_api", "ebay_browse_api"
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PriceAlert(Base):
    __tablename__ = "price_alerts"
    __table_args__ = (UniqueConstraint("tracked_id", "kind", name="uq_alert_kind_per_item"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_id: Mapped[int] = mapped_column(ForeignKey("tracked_products.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    threshold: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # % o importe según el tipo
    threshold_currency: Mapped[str | None] = mapped_column(String(3))  # None = moneda de la publicación
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime)
    armed: Mapped[bool] = mapped_column(Boolean, default=True)  # se rearma cuando la condición deja de cumplirse
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    tracked: Mapped[TrackedProduct] = relationship(back_populates="alerts")


class Promotion(Base):
    __tablename__ = "promotions"
    __table_args__ = (UniqueConstraint("listing_id", "fingerprint", name="uq_promo_fp"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("store_listings.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # discount, free_shipping, quantity_discount, limited_time, seller_offer
    origin: Mapped[str] = mapped_column(String(16))  # "store" (anunciada por la tienda) | "history" (calculada)
    description: Mapped[str] = mapped_column(String(300))
    previous_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    fingerprint: Mapped[str] = mapped_column(String(120))
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)  # sólo si la tienda lo confirma
    conditions: Mapped[str | None] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Coupon(Base):
    __tablename__ = "coupons"
    __table_args__ = (UniqueConstraint("store_id", "code", "listing_id", name="uq_coupon"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("store_listings.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(String(300))
    conditions: Mapped[str | None] = mapped_column(String(500))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)  # NULL = no comprobado
    verification_source: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_notification_dedupe"),
        Index("ix_notif_user_created", "user_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tracked_id: Mapped[int | None] = mapped_column(ForeignKey("tracked_products.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(600))
    payload: Mapped[dict | None] = mapped_column(JSON)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    delivery_status: Mapped[str] = mapped_column(String(24), default="pending")
    # pending | deferred (horario de silencio) | sent | failed | no_devices | not_configured
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)


class PriceCheckJob(Base):
    """Cola de consultas de precio. Una sola fila por publicación => no hay consultas duplicadas."""

    __tablename__ = "price_check_jobs"
    __table_args__ = (
        UniqueConstraint("listing_id", name="uq_job_listing"),
        Index("ix_job_due", "next_run_at", "priority"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("store_listings.id", ondelete="CASCADE"))
    next_run_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(String(300))


class UserPreference(Base):
    __tablename__ = "user_preferences"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), default="COP")
    language: Mapped[str] = mapped_column(String(8), default="es")
    theme: Mapped[str] = mapped_column(String(8), default="dark")
    timezone: Mapped[str] = mapped_column(String(64), default="America/Bogota")
    quiet_start: Mapped[str | None] = mapped_column(String(5))  # "22:00" (hora local del usuario)
    quiet_end: Mapped[str | None] = mapped_column(String(5))  # "07:00"
    utc_offset_minutes: Mapped[int] = mapped_column(Integer, default=-300)
    max_notifications_per_day: Mapped[int] = mapped_column(Integer, default=20)
    daily_digest: Mapped[bool] = mapped_column(Boolean, default=False)
    weekly_digest: Mapped[bool] = mapped_column(Boolean, default=False)
    muted_categories: Mapped[list | None] = mapped_column(JSON)  # categorías de producto silenciadas
    muted_kinds: Mapped[list | None] = mapped_column(JSON)  # tipos de alerta silenciados

    user: Mapped[User] = relationship(back_populates="preferences")


class DeviceToken(Base):
    __tablename__ = "device_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(400), unique=True)
    platform: Mapped[str] = mapped_column(String(16), default="android")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)  # sin FK: sobrevive a la eliminación de cuenta
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    per_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8))  # unidades de `code` por 1 USD
    source: Mapped[str] = mapped_column(String(200))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
