"""Seguimiento de precios: cola de consultas, estados, observaciones, promociones y alertas."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import db as db_module
from ..config import get_settings
from ..connectors import get_connector
from ..connectors.base import (
    Connector, ConnectorError, ListingRef, ProductGone, ProductInfo, SourceUnavailable,
)
from ..currency import quantize
from ..models import (
    AlertKind, PriceAlert, PriceCheckJob, PriceObservation, Promotion, StoreListing, TrackedProduct, TrackingState,
    User, utcnow,
)
from ..urlutil import ParsedUrl
from ..util import D
from .alerts import CheckContext, _to, evaluate_alerts
from .fx import load_rates
from .listings import link_product, upsert_listing
from .notifier import deliver_pending

log = logging.getLogger("dealhunter.tracking")

LOCK_MINUTES = 5
HISTORY_PROMO_MIN_OBS = 3
HISTORY_PROMO_MIN_DAYS = 3
HISTORY_PROMO_MIN_DROP_PCT = Decimal("5")
HISTORY_WINDOW_DAYS = 30
OBSERVATION_REFRESH_HOURS = 24


class TierLimitError(Exception):
    pass


class StoreRateLimiter:
    """Separa las consultas a una misma tienda por un intervalo mínimo (respeta límites de solicitudes)."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self.min_intervals: dict[str, float] = {"mercadolibre": 0.3, "ebay": 0.2, "generic": 2.0}
        self.default_interval = 1.0

    def try_acquire(self, key: str) -> bool:
        now = time.monotonic()
        gap = self.min_intervals.get(key, self.default_interval)
        last = self._last.get(key)
        if last is not None and now - last < gap:
            return False
        self._last[key] = now
        return True

    def reset(self) -> None:
        self._last.clear()


limiter = StoreRateLimiter()


# ---------------------------------------------------------------- límites del plan

def tracked_limit(user: User) -> int:
    s = get_settings()
    return s.premium_tracked_limit if user.tier == "premium" else s.free_tracked_limit


def active_count(db: Session, user_id: int) -> int:
    return db.scalar(select(func.count(TrackedProduct.id)).where(
        TrackedProduct.user_id == user_id, TrackedProduct.deleted.is_(False),
        TrackedProduct.archived.is_(False), TrackedProduct.purchased.is_(False),
    )) or 0


# ---------------------------------------------------------------- alta y estado inicial

def initial_state(connector: Connector) -> tuple[str, str | None]:
    if connector.status() == "unavailable":
        return TrackingState.NEEDS_SOURCE.value, (connector.docs or "")[:300]
    if not connector.configured():
        return TrackingState.NEEDS_SOURCE.value, f"Falta configurar las credenciales de {connector.name} en el servidor"
    return TrackingState.WAITING_FIRST_CHECK.value, None


def ensure_job(db: Session, listing: StoreListing, priority: int = 0, run_at: datetime | None = None) -> PriceCheckJob:
    job = db.scalar(select(PriceCheckJob).where(PriceCheckJob.listing_id == listing.id))
    if job is None:
        job = PriceCheckJob(listing_id=listing.id, next_run_at=run_at or utcnow(), priority=priority)
        db.add(job)
        db.flush()
    else:
        job.priority = max(job.priority, priority)
    return job


def upsert_alert(db: Session, tracked: TrackedProduct, kind: str, threshold: Decimal | None = None,
                 currency: str | None = None, active: bool = True) -> PriceAlert:
    alert = db.scalar(select(PriceAlert).where(PriceAlert.tracked_id == tracked.id, PriceAlert.kind == kind))
    if alert is None:
        alert = PriceAlert(tracked_id=tracked.id, user_id=tracked.user_id, kind=kind)
        db.add(alert)
        tracked.alerts.append(alert)
    alert.threshold, alert.threshold_currency, alert.active = threshold, currency, active
    alert.armed, alert.last_triggered_price = True, None
    db.flush()
    return alert


def set_target(db: Session, tracked: TrackedProduct, price: Decimal | None, currency: str | None) -> None:
    tracked.target_price, tracked.target_currency = price, currency
    if price is not None:
        upsert_alert(db, tracked, AlertKind.TARGET_PRICE.value, None, None)


def add_tracked(
    db: Session, user: User, parsed: ParsedUrl, target_price: Decimal | None = None, target_currency: str | None = None,
    notes: str | None = None, list_name: str | None = None, category: str | None = None, priority: int = 0,
) -> tuple[TrackedProduct, bool]:
    """Devuelve (elemento, creado). Si ya estaba en el carrito, no se duplica (creado=False)."""
    listing, _ = upsert_listing(db, parsed)
    existing = db.scalar(select(TrackedProduct).where(
        TrackedProduct.user_id == user.id, TrackedProduct.listing_id == listing.id))
    if existing is not None and not existing.deleted:
        return existing, False
    if active_count(db, user.id) >= tracked_limit(user):
        raise TierLimitError(
            f"Tu plan permite vigilar hasta {tracked_limit(user)} productos. Archiva alguno o pasa a premium.")
    connector = get_connector(listing.store.key)
    state, detail = initial_state(connector)
    if existing is not None:  # resucitar un elemento eliminado antes
        existing.deleted, existing.archived, existing.purchased, existing.paused = False, False, False, False
        existing.state, existing.state_detail = state, detail
        existing.notes, existing.list_name, existing.category, existing.priority = notes, list_name, category, priority
        existing.initial_price, existing.initial_currency, existing.last_checked_at = None, None, None
        tracked = existing
    else:
        tracked = TrackedProduct(
            user_id=user.id, listing_id=listing.id, state=state, state_detail=detail, notes=notes,
            list_name=list_name, category=category, priority=priority,
        )
        db.add(tracked)
        db.flush()
    tracked.listing = listing
    set_target(db, tracked, target_price, target_currency if target_price is not None else None)
    ensure_job(db, listing, priority=priority * 10)
    last = db.scalar(select(PriceObservation).where(
        PriceObservation.listing_id == listing.id, PriceObservation.price.is_not(None))
        .order_by(PriceObservation.observed_at.desc()).limit(1))
    if last is not None:  # otro usuario ya vigilaba la publicación: hay precio conocido
        tracked.initial_price, tracked.initial_currency = last.price, last.currency
        tracked.state = TrackingState.ACTIVE.value if connector.configured() else tracked.state
    db.flush()
    return tracked, True


def apply_pause(db: Session, tracked: TrackedProduct, paused: bool) -> None:
    tracked.paused = paused
    if paused:
        tracked.state, tracked.state_detail = TrackingState.PAUSED.value, None
    else:
        connector = get_connector(tracked.listing.store.key)
        state, detail = initial_state(connector)
        tracked.state, tracked.state_detail = state, detail
        if not (tracked.archived or tracked.purchased or tracked.deleted):
            ensure_job(db, tracked.listing, priority=tracked.priority * 10)


# ---------------------------------------------------------------- observaciones y metadatos

def latest_obs(db: Session, listing_id: int) -> PriceObservation | None:
    return db.scalar(select(PriceObservation).where(PriceObservation.listing_id == listing_id)
                     .order_by(PriceObservation.observed_at.desc(), PriceObservation.id.desc()).limit(1))


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return D(a) == D(b)


def record_observation(db: Session, listing: StoreListing, info: ProductInfo, now: datetime):
    """Guarda una observación sólo si algo cambió (o pasaron 24 h). Devuelve (observación|None, anterior|None)."""
    prev = latest_obs(db, listing.id)
    changed = (
        prev is None or not _same(prev.price, info.price) or prev.available != info.available
        or prev.currency != info.currency or not _same(prev.shipping_cost, info.shipping_cost)
        or (now - prev.observed_at) >= timedelta(hours=OBSERVATION_REFRESH_HOURS)
    )
    obs = None
    if changed and (info.price is not None or info.available is not None):
        obs = PriceObservation(
            listing_id=listing.id, price=info.price, currency=info.currency, shipping_cost=info.shipping_cost,
            available=info.available, source=info.source, observed_at=now,
        )
        db.add(obs)
        db.flush()
    return obs, prev


def apply_metadata(db: Session, listing: StoreListing, info: ProductInfo) -> None:
    if info.title:
        listing.title, listing.title_is_guess = info.title[:500], False
    if info.image_url:
        listing.image_url = info.image_url[:2000]
    if info.currency:
        listing.currency = info.currency
    if info.seller:
        listing.seller = info.seller[:200]
    if info.condition:
        listing.condition = info.condition
    if info.attributes:
        listing.attributes = info.attributes
    link_product(db, listing, info.brand, info.model, info.gtin, info.title)


def sync_promotions(db: Session, listing: StoreListing, info: ProductInfo, now: datetime) -> list[Promotion]:
    """Promociones anunciadas por la tienda + reducción calculada del historial. Devuelve las NUEVAS de la tienda."""
    new: list[Promotion] = []
    seen: set[str] = set()
    for p in info.promotions:
        fp = f"{p.kind}:{p.previous_price}:{info.price}"
        if fp in seen:
            continue
        seen.add(fp)
        row = db.scalar(select(Promotion).where(Promotion.listing_id == listing.id, Promotion.fingerprint == fp))
        if row is None:
            row = Promotion(
                listing_id=listing.id, kind=p.kind, origin="store", description=p.description[:300],
                previous_price=p.previous_price, current_price=info.price, discount_pct=p.discount_pct,
                currency=info.currency, fingerprint=fp, detected_at=now, checked_at=now, expires_at=p.expires_at,
                conditions=p.conditions,
            )
            db.add(row)
            new.append(row)
        else:
            row.checked_at, row.active = now, True
    for row in db.scalars(select(Promotion).where(
            Promotion.listing_id == listing.id, Promotion.origin == "store", Promotion.active.is_(True))):
        if row.fingerprint not in seen:
            row.active = False
    _sync_history_promo(db, listing, info, now)
    db.flush()
    return new


def _sync_history_promo(db: Session, listing: StoreListing, info: ProductInfo, now: datetime) -> None:
    for row in db.scalars(select(Promotion).where(
            Promotion.listing_id == listing.id, Promotion.origin == "history", Promotion.active.is_(True))):
        row.active = False
    if info.price is None or info.currency is None:
        return
    since = now - timedelta(days=HISTORY_WINDOW_DAYS)
    rows = db.execute(select(PriceObservation.price, PriceObservation.observed_at).where(
        PriceObservation.listing_id == listing.id, PriceObservation.price.is_not(None),
        PriceObservation.currency == info.currency, PriceObservation.observed_at >= since)).all()
    if len(rows) < HISTORY_PROMO_MIN_OBS:
        return
    if (max(r[1] for r in rows) - min(r[1] for r in rows)) < timedelta(days=HISTORY_PROMO_MIN_DAYS):
        return
    top = max(D(r[0]) for r in rows)
    drop = (top - D(info.price)) / top * 100 if top > 0 else Decimal(0)
    if drop < HISTORY_PROMO_MIN_DROP_PCT:
        return
    fp = f"history:{top}:{info.price}"
    row = db.scalar(select(Promotion).where(Promotion.listing_id == listing.id, Promotion.fingerprint == fp))
    desc = (f"{quantize(drop, 1)}% por debajo del precio más alto observado en los últimos {HISTORY_WINDOW_DAYS} días "
            "(calculado por DealHunter con su historial; no es un descuento anunciado por la tienda)")
    if row is None:
        db.add(Promotion(
            listing_id=listing.id, kind="discount", origin="history", description=desc, previous_price=top,
            current_price=info.price, discount_pct=quantize(drop, 2), currency=info.currency, fingerprint=fp,
            detected_at=now, checked_at=now,
        ))
    else:
        row.active, row.checked_at = True, now


# ---------------------------------------------------------------- procesamiento de la cola

def _active_trackers(db: Session, listing_id: int) -> list[TrackedProduct]:
    return list(db.scalars(select(TrackedProduct).where(
        TrackedProduct.listing_id == listing_id, TrackedProduct.deleted.is_(False),
        TrackedProduct.archived.is_(False), TrackedProduct.purchased.is_(False), TrackedProduct.paused.is_(False),
    )))


def _set_states(trackers: list[TrackedProduct], state: TrackingState, detail: str | None, now: datetime) -> None:
    for t in trackers:
        t.state, t.state_detail, t.last_checked_at = state.value, (detail or None) and detail[:300], now


def _near_target(trackers: list[TrackedProduct], listing: StoreListing, price: Decimal | None, rates) -> bool:
    if price is None:
        return False
    thr_pct = Decimal(str(get_settings().near_target_threshold_pct))
    for t in trackers:
        if t.target_price is None:
            continue
        p = _to(price, listing.currency, t.target_currency, rates)
        if p is not None and p <= D(t.target_price) * (1 + thr_pct / 100):
            return True
    return False


def _next_interval(trackers: list[TrackedProduct], listing: StoreListing, price, rates, significant: bool) -> timedelta:
    s = get_settings()
    minutes = s.default_check_interval_minutes
    if any(t.priority >= 1 for t in trackers):
        minutes = max(s.near_target_check_interval_minutes, minutes // 2)
    if _near_target(trackers, listing, price, rates):
        minutes = min(minutes, s.near_target_check_interval_minutes)
    if significant:
        minutes = max(s.near_target_check_interval_minutes // 2, minutes // 2)
    return timedelta(minutes=minutes)


def _register_failure(db: Session, job: PriceCheckJob, trackers: list[TrackedProduct], message: str,
                      retry_after: int | None, now: datetime) -> str:
    s = get_settings()
    job.attempts += 1
    if job.attempts >= s.max_retry_attempts:
        delay = timedelta(minutes=s.default_check_interval_minutes)
        job.attempts = 0
    else:
        delay = timedelta(seconds=retry_after or min(60 * 2 ** job.attempts, 6 * 3600))
    job.next_run_at, job.last_error, job.locked_until, job.last_run_at = now + delay, message[:300], None, now
    _set_states(trackers, TrackingState.TEMPORARILY_FAILED, f"{message}. Se reintentará automáticamente.", now)
    db.commit()
    return "failed"


def process_job(db: Session, job: PriceCheckJob, now: datetime | None = None) -> str:
    """Procesa una publicación. Devuelve: ok | needs_source | gone | failed | rate_limited | no_trackers."""
    now = now or utcnow()
    s = get_settings()
    listing = db.get(StoreListing, job.listing_id)
    trackers = _active_trackers(db, job.listing_id)
    if not trackers:
        db.delete(job)
        db.commit()
        return "no_trackers"
    connector = get_connector(listing.store.key)

    def needs_source(detail: str) -> str:
        job.next_run_at = now + timedelta(minutes=s.unavailable_source_interval_minutes)
        job.attempts, job.last_error, job.locked_until, job.last_run_at = 0, detail[:300], None, now
        _set_states(trackers, TrackingState.NEEDS_SOURCE, detail, now)
        db.commit()
        return "needs_source"

    if connector.status() == "unavailable" or not connector.configured():
        return needs_source(initial_state(connector)[1] or "Sin fuente de datos")
    if not limiter.try_acquire(listing.store.key):
        job.locked_until = None
        db.commit()
        return "rate_limited"

    ref = ListingRef(listing.external_id, listing.variant_key, listing.canonical_url)
    try:
        info = connector.fetch(ref)
    except SourceUnavailable as e:
        return needs_source(str(e))
    except ProductGone as e:
        job.next_run_at = now + timedelta(days=1)
        job.attempts, job.last_error, job.locked_until, job.last_run_at = 0, str(e)[:300], None, now
        _set_states(trackers, TrackingState.UNAVAILABLE_IN_STORE, str(e), now)
        db.commit()
        return "gone"
    except ConnectorError as e:
        return _register_failure(db, job, trackers, str(e), e.retry_after_seconds, now)
    except Exception:
        log.exception("Error inesperado consultando %s", listing.store.key)
        return _register_failure(db, job, trackers, "Error interno al procesar la respuesta de la tienda", None, now)

    apply_metadata(db, listing, info)
    obs, prev = record_observation(db, listing, info, now)
    new_promos = sync_promotions(db, listing, info, now)

    if info.price is None:
        state, detail = TrackingState.PRICE_UNAVAILABLE, "La tienda no publicó un precio que podamos leer"
    elif info.available is False:
        state, detail = TrackingState.UNAVAILABLE_IN_STORE, "La tienda indica que el producto no está disponible"
    else:
        state, detail = TrackingState.ACTIVE, None
    _set_states(trackers, state, detail, now)

    significant = False
    if prev is not None and prev.price is not None and info.price is not None and prev.currency == info.currency:
        change = abs((D(info.price) - D(prev.price)) / D(prev.price) * 100) if D(prev.price) != 0 else Decimal(0)
        significant = change >= Decimal(str(s.significant_change_pct))
    if significant:
        log.info("Cambio significativo en listing %s", listing.id)

    rates = load_rates(db)
    for t in trackers:
        if t.initial_price is None and info.price is not None:
            t.initial_price, t.initial_currency = info.price, info.currency
        user = db.get(User, t.user_id)
        if user is None:
            continue
        evaluate_alerts(db, user, t, CheckContext(
            listing=listing, prev=prev, obs=obs, info=info, new_promos=new_promos, rates=rates, now=now))

    job.attempts, job.last_error, job.last_run_at, job.locked_until = 0, None, now, None
    job.priority = max(t.priority for t in trackers) * 10 + (5 if _near_target(trackers, listing, info.price, rates) else 0)
    job.next_run_at = now + _next_interval(trackers, listing, info.price, rates, significant)
    db.commit()
    return "ok"


def claim_due_jobs(db: Session, now: datetime, limit: int) -> list[int]:
    q = (select(PriceCheckJob).where(
        PriceCheckJob.next_run_at <= now, or_(PriceCheckJob.locked_until.is_(None), PriceCheckJob.locked_until < now))
        .order_by(PriceCheckJob.priority.desc(), PriceCheckJob.next_run_at).limit(limit)
        .with_for_update(skip_locked=True))
    jobs = db.scalars(q).all()
    for j in jobs:
        j.locked_until = now + timedelta(minutes=LOCK_MINUTES)
    db.commit()
    return [j.id for j in jobs]


def run_due_jobs(db: Session, now: datetime | None = None, limit: int | None = None) -> dict[str, int]:
    now = now or utcnow()
    limit = limit or get_settings().worker_batch_size
    counts: dict[str, int] = {}
    for job_id in claim_due_jobs(db, now, limit):
        job = db.get(PriceCheckJob, job_id)
        if job is None:
            continue
        try:
            outcome = process_job(db, job, now)
        except Exception:
            db.rollback()
            log.exception("Fallo procesando el trabajo %s", job_id)
            job = db.get(PriceCheckJob, job_id)
            outcome = "failed"
            if job is not None:
                _register_failure(db, job, _active_trackers(db, job.listing_id), "Error interno", None, now)
        counts[outcome] = counts.get(outcome, 0) + 1
    deliver_pending(db, now)
    return counts


def run_job_for_listing(db: Session, listing_id: int, now: datetime | None = None) -> str:
    """Comprobación inmediata (al añadir un producto o al pedir actualizar). Respeta el bloqueo de la cola."""
    now = now or utcnow()
    job = db.scalar(select(PriceCheckJob).where(PriceCheckJob.listing_id == listing_id))
    if job is None:
        return "no_job"
    if job.locked_until is not None and job.locked_until > now:
        return "locked"
    job.locked_until = now + timedelta(minutes=LOCK_MINUTES)
    db.commit()
    try:
        outcome = process_job(db, job, now)
    except Exception:
        db.rollback()
        log.exception("Fallo en la comprobación inmediata")
        job = db.get(PriceCheckJob, job.id)
        if job is not None:
            _register_failure(db, job, _active_trackers(db, listing_id), "Error interno", None, now)
        outcome = "failed"
    deliver_pending(db, now)
    return outcome


def check_listing_in_background(listing_id: int) -> None:
    """Para BackgroundTasks: abre su propia sesión."""
    db = db_module.SessionLocal()
    try:
        run_job_for_listing(db, listing_id)
    finally:
        db.close()
