"""Cliente HTTP compartido por los conectores (inyectable en pruebas) y utilidades de parsing."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

import httpx

from ..config import get_settings
from .base import ConnectorError

_client: httpx.Client | None = None
_override: httpx.Client | None = None


def set_client_for_tests(client: httpx.Client | None) -> None:
    global _override
    _override = client


def get_client() -> httpx.Client:
    global _client
    if _override is not None:
        return _override
    if _client is None:
        s = get_settings()
        _client = httpx.Client(
            timeout=s.http_timeout_seconds,
            headers={"User-Agent": s.user_agent, "Accept": "application/json"},
            follow_redirects=False,
        )
    return _client


def request(method: str, url: str, **kw) -> httpx.Response:
    """Petición con traducción de errores de red a ConnectorError (reintentable)."""
    try:
        resp = get_client().request(method, url, **kw)
    except httpx.TimeoutException as e:
        raise ConnectorError("Tiempo de espera agotado") from e
    except httpx.HTTPError as e:
        raise ConnectorError("Error de red al consultar la tienda") from e
    if resp.status_code == 429:
        ra = resp.headers.get("Retry-After", "")
        raise ConnectorError("La tienda limitó las solicitudes (429)", int(ra) if ra.isdigit() else 900)
    if resp.status_code >= 500:
        raise ConnectorError(f"Error del servidor de la tienda ({resp.status_code})")
    return resp


def to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        d = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    return d if d >= 0 else None
