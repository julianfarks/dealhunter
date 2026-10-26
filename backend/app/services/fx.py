"""Tipos de cambio persistidos con fecha y procedencia."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..connectors.http import get_client
from ..currency import Rates, parse_rates_payload
from ..models import ExchangeRate, utcnow


def load_rates(db: Session) -> Rates:
    rows = db.scalars(select(ExchangeRate)).all()
    if not rows:
        return Rates()
    newest = max(r.fetched_at for r in rows)
    return Rates({r.code: Decimal(r.per_usd) for r in rows}, newest, rows[0].source)


def refresh_rates(db: Session, force: bool = False) -> bool:
    """Descarga las tasas si están vencidas. Devuelve True si se actualizaron."""
    s = get_settings()
    rates = load_rates(db)
    if not force and rates.fetched_at and utcnow() - rates.fetched_at < timedelta(hours=s.fx_refresh_hours):
        return False
    try:
        resp = get_client().get(s.fx_source_url, headers={"Accept": "application/json"})
        if resp.status_code != 200:
            return False
        parsed = parse_rates_payload(resp.json())
    except Exception:
        return False
    now = utcnow()
    for code, per_usd in parsed.items():
        row = db.get(ExchangeRate, code)
        if row is None:
            db.add(ExchangeRate(code=code, per_usd=per_usd, source=s.fx_source_url, fetched_at=now))
        else:
            row.per_usd, row.source, row.fetched_at = per_usd, s.fx_source_url, now
    db.commit()
    return True
