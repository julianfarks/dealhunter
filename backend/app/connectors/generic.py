"""Tiendas independientes: lectura de datos estructurados públicos de la página del producto.

Sólo se usa en dominios que NO son los grandes marketplaces, respeta robots.txt, aplica protección SSRF
en cada redirección y se limita a metadatos que la propia tienda publica para buscadores
(JSON-LD schema.org/Product, Open Graph, product:price:*). Si la página no los publica, el precio queda
como "no disponible" y no se inventa nada.
"""
from __future__ import annotations

import json
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from ..config import get_settings
from ..urlutil import InvalidUrl, assert_public_host, validate_url
from .base import Connector, ConnectorError, ListingRef, ProductGone, ProductInfo, SourceUnavailable
from .http import get_client, to_decimal

MAX_BYTES = 1_500_000
MAX_REDIRECTS = 3
_robots_cache: dict[str, tuple[float, RobotFileParser | None]] = {}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.jsonld: list[str] = []
        self._in_ld = False
        self._buf: list[str] = []
        self.title_text = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and "content" in a:
                self.meta.setdefault(key, a["content"])
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_ld, self._buf = True, []
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self.jsonld.append("".join(self._buf))
            self._in_ld = False
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_ld:
            self._buf.append(data)
        elif self._in_title:
            self.title_text += data


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _is_type(node: dict, name: str) -> bool:
    t = node.get("@type")
    return name in t if isinstance(t, list) else t == name


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def parse_product_html(html: str) -> ProductInfo:
    ex = _Extractor()
    try:
        ex.feed(html)
    except Exception:  # HTML muy roto: usamos lo que se haya podido leer
        pass
    info = ProductInfo(source="generic_structured_data")
    for raw in ex.jsonld:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for node in _walk(data):
            if not _is_type(node, "Product"):
                continue
            info.title = info.title or node.get("name")
            img = _first(node.get("image"))
            info.image_url = info.image_url or (img.get("url") if isinstance(img, dict) else img)
            brand = node.get("brand")
            info.brand = info.brand or (brand.get("name") if isinstance(brand, dict) else brand)
            info.model = info.model or node.get("mpn") or node.get("model") or node.get("sku")
            info.gtin = info.gtin or node.get("gtin13") or node.get("gtin") or node.get("gtin14") or node.get("gtin12")
            offers = _first(node.get("offers"))
            if isinstance(offers, dict):
                price = offers.get("price")
                if price is None:
                    price = offers.get("lowPrice")
                if price is None and isinstance(offers.get("priceSpecification"), dict):
                    price = offers["priceSpecification"].get("price")
                if info.price is None:
                    info.price = to_decimal(price)
                    info.currency = offers.get("priceCurrency") or info.currency
                av = str(offers.get("availability", ""))
                if av and info.available is None:
                    info.available = av.endswith(("InStock", "LimitedAvailability", "OnlineOnly", "PreOrder"))
                cond = str(offers.get("itemCondition", ""))
                if cond:
                    info.condition = {"NewCondition": "new", "UsedCondition": "used",
                                      "RefurbishedCondition": "refurbished"}.get(cond.rsplit("/", 1)[-1], None)
    m = ex.meta
    info.title = info.title or m.get("og:title") or (ex.title_text.strip() or None)
    info.image_url = info.image_url or m.get("og:image")
    if info.price is None:
        info.price = to_decimal(m.get("product:price:amount") or m.get("og:price:amount") or m.get("price"))
        info.currency = info.currency or m.get("product:price:currency") or m.get("og:price:currency") \
            or m.get("pricecurrency")
    if info.currency:
        info.currency = info.currency.upper()[:3]
    if info.title:
        info.title = info.title.strip()[:500]
    return info


def _robots_allows(url: str) -> bool:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    now = time.time()
    cached = _robots_cache.get(origin)
    if cached is None or now - cached[0] > 3600:
        rp: RobotFileParser | None = RobotFileParser()
        try:
            resp = get_client().get(f"{origin}/robots.txt", headers={"Accept": "text/plain"})
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            elif resp.status_code in (401, 403):
                rp.disallow_all = True  # type: ignore[attr-defined]
            else:
                rp = None  # sin robots.txt => permitido
        except Exception:
            rp = None
        _robots_cache[origin] = (now, rp)
        cached = _robots_cache[origin]
    rp = cached[1]
    return True if rp is None else rp.can_fetch(get_settings().user_agent, url)


def clear_robots_cache() -> None:
    _robots_cache.clear()


class GenericConnector(Connector):
    key = "generic"
    name = "Tienda independiente"
    docs = "Lee datos estructurados públicos (schema.org/Open Graph) respetando robots.txt."

    def configured(self) -> bool:
        return get_settings().generic_fetch_enabled

    def fetch(self, ref: ListingRef) -> ProductInfo:
        if not self.configured():
            raise SourceUnavailable("La lectura de tiendas independientes está desactivada")
        url = ref.canonical_url
        client = get_client()
        for _ in range(MAX_REDIRECTS + 1):
            try:
                url, host = validate_url(url)
                assert_public_host(host, urlsplit(url).port)
            except InvalidUrl as e:
                raise SourceUnavailable(f"Dirección no permitida: {e}") from e
            if not _robots_allows(url):
                raise SourceUnavailable("El sitio no permite consultas automáticas (robots.txt)")
            try:
                with client.stream("GET", url, headers={"Accept": "text/html,application/xhtml+xml"}) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("location")
                        if not loc:
                            raise ConnectorError("Redirección sin destino")
                        url = urljoin(url, loc)
                        continue
                    if resp.status_code == 404 or resp.status_code == 410:
                        raise ProductGone("La página del producto ya no existe")
                    if resp.status_code == 429:
                        raise ConnectorError("El sitio limitó las solicitudes (429)", 1800)
                    if resp.status_code in (401, 403):
                        raise SourceUnavailable("El sitio no permite consultas automáticas")
                    if resp.status_code >= 400:
                        raise ConnectorError(f"Error del sitio ({resp.status_code})")
                    ctype = resp.headers.get("content-type", "")
                    if "html" not in ctype.lower():
                        raise SourceUnavailable("La URL no es una página HTML")
                    chunks, size = [], 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            break
                        chunks.append(chunk)
                    html = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
            except (ConnectorError, SourceUnavailable, ProductGone):
                raise
            except Exception as e:  # red, TLS, etc.
                raise ConnectorError("Error de red al consultar el sitio") from e
            return parse_product_html(html)
        raise ConnectorError("Demasiadas redirecciones")
