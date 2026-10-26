"""Conversión de monedas con tasas explícitas (nunca inventadas) y su fecha de actualización."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal


class RateUnavailable(Exception):
    """No hay tasa disponible para la conversión pedida."""


@dataclass
class Rates:
    per_usd: dict[str, Decimal] = field(default_factory=dict)  # unidades de la moneda por 1 USD
    fetched_at: datetime | None = None
    source: str = ""

    def has(self, code: str) -> bool:
        return code.upper() == "USD" or code.upper() in self.per_usd

    def _r(self, code: str) -> Decimal:
        code = code.upper()
        if code == "USD":
            return Decimal(1)
        try:
            return self.per_usd[code]
        except KeyError as e:
            raise RateUnavailable(f"Sin tasa de cambio para {code}") from e


@dataclass
class Converted:
    amount: Decimal
    rate: Decimal  # unidades de `to` por 1 unidad de `from`
    fetched_at: datetime | None
    source: str


def quantize(amount: Decimal, places: int = 2) -> Decimal:
    q = Decimal(1).scaleb(-places)
    return Decimal(amount).quantize(q, rounding=ROUND_HALF_UP)


def convert(amount: Decimal, src: str, dst: str, rates: Rates) -> Converted:
    src, dst = src.upper(), dst.upper()
    if src == dst:
        return Converted(quantize(amount), Decimal(1), rates.fetched_at, rates.source)
    rate = rates._r(dst) / rates._r(src)
    return Converted(quantize(amount * rate), rate, rates.fetched_at, rates.source)


def parse_rates_payload(payload: dict) -> dict[str, Decimal]:
    """Interpreta la respuesta de open.er-api.com (base USD)."""
    if payload.get("result") != "success":
        raise ValueError("Respuesta de tipos de cambio no válida")
    out: dict[str, Decimal] = {}
    for code, value in (payload.get("rates") or {}).items():
        if isinstance(code, str) and len(code) == 3 and isinstance(value, (int, float)) and value > 0:
            out[code.upper()] = Decimal(str(value))
    if "USD" not in out:
        out["USD"] = Decimal(1)
    return out
