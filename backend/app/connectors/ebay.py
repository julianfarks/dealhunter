"""eBay — Browse API oficial (https://developer.ebay.com/api-docs/buy/browse).

Requiere un token de aplicación (client credentials). Configura EBAY_CLIENT_ID / EBAY_CLIENT_SECRET
(y EBAY_MARKETPLACE_ID, p. ej. EBAY_US o EBAY_ES).

ESTADO: implementado según la documentación; NO verificado contra la API real desde el entorno de desarrollo.
Verifícalo con `python -m app.admin check <url>`.
"""
from __future__ import annotations

import base64
import time
from decimal import Decimal

from ..config import get_settings
from .base import (
    Connector, ConnectorError, ListingRef, ProductGone, ProductInfo, PromoInfo, SearchHit, SourceUnavailable,
)
from .http import request, to_decimal

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE = "https://api.ebay.com/buy/browse/v1"
SCOPE = "https://api.ebay.com/oauth/api_scope"

_tok = {"value": "", "exp": 0.0}


def reset_token_state() -> None:
    _tok["value"], _tok["exp"] = "", 0.0


class EbayConnector(Connector):
    key = "ebay"
    name = "eBay"
    docs = "Browse API oficial con token de aplicación (client credentials)."

    def configured(self) -> bool:
        s = get_settings()
        return bool(s.ebay_client_id and s.ebay_client_secret)

    def _token(self) -> str:
        if _tok["value"] and time.time() < _tok["exp"] - 60:
            return _tok["value"]
        s = get_settings()
        if not self.configured():
            raise SourceUnavailable("eBay requiere EBAY_CLIENT_ID y EBAY_CLIENT_SECRET")
        basic = base64.b64encode(f"{s.ebay_client_id}:{s.ebay_client_secret}".encode()).decode()
        resp = request(
            "POST", TOKEN_URL, data={"grant_type": "client_credentials", "scope": SCOPE},
            headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code in (400, 401):
            raise SourceUnavailable("eBay rechazó las credenciales configuradas")
        if resp.status_code != 200:
            raise ConnectorError(f"No se pudo obtener el token de eBay ({resp.status_code})")
        data = resp.json()
        _tok["value"] = data["access_token"]
        _tok["exp"] = time.time() + int(data.get("expires_in", 7200))
        return _tok["value"]

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token()}",
            "X-EBAY-C-MARKETPLACE-ID": get_settings().ebay_marketplace_id,
            "Accept": "application/json",
        }

    def fetch(self, ref: ListingRef) -> ProductInfo:
        params = {"legacy_item_id": ref.external_id}
        if ref.variant_key:
            params["legacy_variation_id"] = ref.variant_key
        resp = request("GET", f"{BROWSE}/item/get_item_by_legacy_id", params=params, headers=self._headers())
        if resp.status_code == 404:
            raise ProductGone("El artículo ya no existe en eBay")
        if resp.status_code in (401, 403):
            raise SourceUnavailable("eBay denegó el acceso (credenciales o permisos)")
        if resp.status_code == 400:
            # eBay responde 400 para IDs legados inválidos o no disponibles en el marketplace configurado
            raise SourceUnavailable("eBay no reconoce el artículo en el marketplace configurado")
        if resp.status_code != 200:
            raise ConnectorError(f"Respuesta inesperada de eBay ({resp.status_code})")
        return parse_item(resp.json())

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        resp = request("GET", f"{BROWSE}/item_summary/search", params={"q": query, "limit": limit},
                       headers=self._headers())
        if resp.status_code != 200:
            return []
        hits = []
        for r in resp.json().get("itemSummaries", [])[:limit]:
            p = r.get("price") or {}
            hits.append(SearchHit(
                "ebay", r.get("title", ""), r.get("itemWebUrl", ""), to_decimal(p.get("value")),
                p.get("currency"), (r.get("image") or {}).get("imageUrl"),
            ))
        return hits


def parse_item(data: dict) -> ProductInfo:
    p = data.get("price") or {}
    price = to_decimal(p.get("value"))
    shipping = None
    for opt in data.get("shippingOptions", []) or []:
        c = to_decimal((opt.get("shippingCost") or {}).get("value"))
        if c is not None and (shipping is None or c < shipping):
            shipping = c
    avail = None
    ests = data.get("estimatedAvailabilities") or []
    if ests:
        st = ests[0].get("estimatedAvailabilityStatus")
        if st:
            avail = st in ("IN_STOCK", "LIMITED_STOCK")
    gtin = data.get("gtin")
    if isinstance(gtin, list):
        gtin = gtin[0] if gtin else None
    seller = (data.get("seller") or {}).get("username")
    info = ProductInfo(
        source="ebay_browse_api", title=data.get("title"), image_url=(data.get("image") or {}).get("imageUrl"),
        price=price, currency=p.get("currency"), available=avail, shipping_cost=shipping, seller=seller,
        condition=(data.get("condition") or "").lower() or None, brand=data.get("brand"),
        model=data.get("mpn"), gtin=gtin,
    )
    mp = data.get("marketingPrice") or {}
    orig = to_decimal((mp.get("originalPrice") or {}).get("value"))
    if price is not None and orig is not None and orig > price:
        pct = to_decimal(mp.get("discountPercentage")) or ((orig - price) / orig * 100).quantize(Decimal("0.01"))
        info.promotions.append(PromoInfo(
            "discount", "Descuento anunciado por el vendedor/eBay (precio de referencia vs. precio actual)",
            previous_price=orig, discount_pct=pct))
    return info
