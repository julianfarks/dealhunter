from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from .currency import quantize

_ZERO_DECIMAL = {"COP", "CLP", "JPY", "KRW", "PYG", "VND", "ISK", "HUF"}


def D(value) -> Decimal:
    """Decimal exacto desde cualquier valor numérico (evita imprecisiones de float)."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def fmt_money(amount: Decimal | None, currency: str | None) -> str:
    """Formato es-CO: $229.900 COP · 19,99 USD."""
    if amount is None:
        return "—"
    cur = (currency or "").upper()
    if cur in _ZERO_DECIMAL or cur == "":
        n = int(quantize(Decimal(amount), 0))
        s = f"{n:,}".replace(",", ".")
        return f"${s} {cur}".strip()
    q = quantize(Decimal(amount), 2)
    whole, frac = f"{q:.2f}".split(".")
    whole = f"{int(whole):,}".replace(",", ".")
    return f"{whole},{frac} {cur}"


def pct_change(old: Decimal | None, new: Decimal | None) -> Decimal | None:
    if old is None or new is None or old == 0:
        return None
    return quantize((new - old) / old * 100, 2)


def iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.isoformat() + "Z"


def local_now(utc_now: datetime, offset_minutes: int) -> datetime:
    return utc_now + timedelta(minutes=offset_minutes)
