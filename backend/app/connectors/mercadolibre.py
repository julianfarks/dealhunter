"""Mercado Libre — API oficial (https://developers.mercadolibre.com).

La documentación oficial indica que TODAS las llamadas (públicas y privadas) deben llevar un access token.
Configura MELI_ACCESS_TOKEN, o bien MELI_CLIENT_ID + MELI_CLIENT_SECRET + MELI_REFRESH_TOKEN (flujo
authorization_code ya realizado una vez por el dueño de la app). El refresh token rota en cada renovación;
el nuevo se guarda en MELI_TOKEN_FILE para sobrevivir a reinicios.

ESTADO: implementado según la documentación; NO verificado contra la API real desde el entorno de desarrollo
(sin credenciales). Verifícalo con `python -m app.admin check <url>`.
"""
from __future__ import annotations

import json
import os
import time
from decimal import Decimal

from ..config import get_settings
from .base import (
    Connector, ConnectorError, ListingRef, ProductGone, ProductInfo, PromoInfo, SearchHit, SourceUnavailable,
)
from .http import request, to_decimal

API = "https://api.mercadolibre.com"


class _TokenState:
    access_token: str = ""
    expires_at: float = 0.0
    refresh_token: str = ""


_state = _TokenState()


def reset_token_state() -> None:
    _state.access_token, _state.expires_at, _state.refresh_token = "", 0.0, ""


class MercadoLibreConnector(Connector):
    key = "mercadolibre"
    name = "Mercado Libre"
    docs = "API oficial; requiere token de acceso en todas las llamadas."

    def _has_refresh_creds(self) -> bool:
        s = get_settings()
        return bool(s.meli_client_id and s.meli_client_secret and (s.meli_refresh_token or self._saved_refresh()))

    def _saved_refresh(self) -> str:
        path = get_settings().meli_token_file
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f).get("refresh_token", "")
            except Exception:
                return ""
        return ""

    def configured(self) -> bool:
        return bool(get_settings().meli_access_token) or self._has_refresh_creds()

    def _token(self) -> str:
        s = get_settings()
        if s.meli_access_token and not self._has_refresh_creds():
            return s.meli_access_token
        if _state.access_token and time.time() < _state.expires_at - 60:
            return _state.access_token
        if not self._has_refresh_creds():
            raise SourceUnavailable("Mercado Libre requiere un token de acceso (ver docs/stores.md)")
        refresh = _state.refresh_token or self._saved_refresh() or s.meli_refresh_token
        resp = request(
            "POST", f"{API}/oauth/token",
            data={"grant_type": "refresh_token", "client_id": s.meli_client_id,
                  "client_secret": s.meli_client_secret, "refresh_token": refresh},
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code in (400, 401, 403):
            raise SourceUnavailable("Mercado Libre rechazó las credenciales/refresh token configurados")
        if resp.status_code != 200:
            raise ConnectorError(f"No se pudo renovar el token de Mercado Libre ({resp.status_code})")
        data = resp.json()
        _state.access_token = data["access_token"]
        _state.expires_at = time.time() + int(data.get("expires_in", 21600))
        _state.refresh_token = data.get("refresh_token", refresh)
        if s.meli_token_file:
            try:
                with open(s.meli_token_file, "w") as f:
                    json.dump({"refresh_token": _state.refresh_token}, f)
                os.chmod(s.meli_token_file, 0o600)
            except OSError:
                pass
        return _state.access_token

    def _get(self, path: str, params: dict | None = None):
        resp = request("GET", f"{API}{path}", params=params,
                       headers={"Authorization": f"Bearer {self._token()}", "Accept": "application/json"})
        if resp.status_code == 404:
            raise ProductGone("La publicación ya no existe en Mercado Libre")
        if resp.status_code in (401, 403):
            raise SourceUnavailable("Mercado Libre denegó el acceso (token ausente, vencido o sin permisos)")
        if resp.status_code != 200:
            raise ConnectorError(f"Respuesta inesperada de Mercado Libre ({resp.status_code})")
        return resp.json()

    def fetch(self, ref: ListingRef) -> ProductInfo:
        if ref.external_id.startswith("P:"):
            raise SourceUnavailable("Los enlaces de catálogo (/p/…) no identifican una publicación concreta")
        data = self._get(f"/items/{ref.external_id}")
        return parse_item(data, ref.variant_key)

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        s = get_settings()
        data = self._get(f"/sites/{s.meli_site_id}/search", {"q": query, "limit": limit})
        hits = []
        for r in data.get("results", [])[:limit]:
            attrs = {a.get("id"): a.get("value_name") for a in r.get("attributes", []) if a.get("id")}
            hits.append(SearchHit(
                "mercadolibre", r.get("title", ""), r.get("permalink", ""), to_decimal(r.get("price")),
                r.get("currency_id"), r.get("thumbnail"), attrs.get("GTIN"), attrs.get("BRAND"), attrs.get("MODEL"),
            ))
        return hits


def parse_item(data: dict, variant_key: str = "") -> ProductInfo:
    price = to_decimal(data.get("price"))
    qty = data.get("available_quantity")
    attrs = {a.get("id"): a.get("value_name") for a in data.get("attributes", []) if a.get("id")}
    variant_attrs = None
    if variant_key:
        for v in data.get("variations", []) or []:
            if str(v.get("id")) == str(variant_key):
                price = to_decimal(v.get("price")) or price
                qty = v.get("available_quantity", qty)
                variant_attrs = {c.get("name"): c.get("value_name") for c in v.get("attribute_combinations", [])}
                break
    status = data.get("status")
    available = None if qty is None else (qty > 0 and status in (None, "active"))
    pics = data.get("pictures") or []
    image = (pics[0].get("secure_url") if pics else None) or data.get("thumbnail")
    shipping = data.get("shipping") or {}
    info = ProductInfo(
        source="mercadolibre_api", title=data.get("title"), image_url=image, price=price,
        currency=data.get("currency_id"), available=available,
        shipping_cost=Decimal(0) if shipping.get("free_shipping") else None,
        seller=str(data.get("seller_id")) if data.get("seller_id") else None,
        condition=data.get("condition"), brand=attrs.get("BRAND"), model=attrs.get("MODEL"),
        gtin=attrs.get("GTIN"), attributes=variant_attrs,
    )
    original = to_decimal(data.get("original_price"))
    if price is not None and original is not None and original > price:
        pct = ((original - price) / original * 100).quantize(Decimal("0.01"))
        info.promotions.append(PromoInfo(
            "discount", "Descuento anunciado por la tienda (precio original vs. precio actual)",
            previous_price=original, discount_pct=pct))
    if shipping.get("free_shipping"):
        info.promotions.append(PromoInfo(
            "free_shipping", "Envío gratis anunciado por la tienda", conditions="Sujeto al destino y a las condiciones de Mercado Libre"))
    return info
