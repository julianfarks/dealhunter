"""Worker de seguimiento: se ejecuta como proceso independiente (`python -m app.worker`).

Por eso el seguimiento funciona aunque el teléfono esté apagado: sólo depende de que el backend esté en marcha.
Cada ciclo: actualiza tipos de cambio, procesa las consultas vencidas, entrega notificaciones y envía resúmenes.
"""
from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timedelta

from sqlalchemy import select

from . import db as db_module
from .config import get_settings
from .models import Notification, User, UserPreference, utcnow
from .services import fx, tracking
from .services.notifier import create_notification, deliver_pending
from .services.views import latest_prices, potential_saving
from .util import D, fmt_money

log = logging.getLogger("dealhunter.worker")


def send_digests(db, now: datetime | None = None) -> int:
    """Resumen diario (08:00 hora local) y semanal (lunes 08:00) para quienes lo activaron. Sin duplicados."""
    from .models import TrackedProduct

    now = now or utcnow()
    created = 0
    for p in db.scalars(select(UserPreference).where((UserPreference.daily_digest.is_(True)) |
                                                      (UserPreference.weekly_digest.is_(True)))):
        local = now + timedelta(minutes=p.utc_offset_minutes)
        if local.hour != 8:
            continue
        kinds = []
        if p.daily_digest:
            kinds.append(("daily", "Resumen diario"))
        if p.weekly_digest and local.weekday() == 0:
            kinds.append(("weekly", "Resumen semanal"))
        user = db.get(User, p.user_id)
        if user is None or not kinds:
            continue
        items = list(db.scalars(select(TrackedProduct).where(
            TrackedProduct.user_id == user.id, TrackedProduct.deleted.is_(False),
            TrackedProduct.archived.is_(False), TrackedProduct.purchased.is_(False))))
        prices = latest_prices(db, [t.listing_id for t in items])
        at_target, savings = 0, {}
        for t in items:
            o = prices.get(t.listing_id)
            if not o:
                continue
            if t.target_price is not None and (t.target_currency or o.currency) == o.currency \
                    and D(o.price) <= D(t.target_price):
                at_target += 1
            sv = potential_saving(t, D(o.price), o.currency)
            if sv:
                savings[o.currency] = savings.get(o.currency, 0) + sv
        for key, title in kinds:
            sav = ", ".join(fmt_money(a, c) for c, a in savings.items()) or "—"
            body = (f"Vigilas {len(items)} productos; {at_target} en tu precio objetivo. "
                    f"Ahorro potencial estimado (no es dinero ahorrado): {sav}.")
            n = create_notification(db, user, None, "digest", title, body, {"kind": "digest"},
                                    f"digest:{key}:{local.date().isoformat()}", now)
            created += 1 if n else 0
    db.commit()
    return created


def run_cycle(now: datetime | None = None) -> dict:
    db = db_module.SessionLocal()
    try:
        try:
            fx.refresh_rates(db)
        except Exception:
            log.exception("No se pudieron actualizar los tipos de cambio")
            db.rollback()
        counts = tracking.run_due_jobs(db, now)
        digests = send_digests(db, now)
        deliver_pending(db, now)
        return {"jobs": counts, "digests": digests}
    finally:
        db.close()


def main() -> None:  # pragma: no cover - bucle de producción
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = {"flag": False}

    def _stop(*_):
        stop["flag"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    poll = get_settings().worker_poll_seconds
    log.info("Worker iniciado (cada %ss)", poll)
    while not stop["flag"]:
        try:
            result = run_cycle()
            if result["jobs"]:
                log.info("Ciclo: %s", result)
        except Exception:
            log.exception("Error en el ciclo del worker")
        for _ in range(poll):
            if stop["flag"]:
                break
            time.sleep(1)
    log.info("Worker detenido")


if __name__ == "__main__":  # pragma: no cover
    main()
