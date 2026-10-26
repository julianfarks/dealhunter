"""Conectores. Las respuestas HTTP son SIMULADAS con la forma documentada por cada API; no prueban la API real."""
import json
from decimal import Decimal

import httpx
import pytest

from app.connectors import ConnectorError, ListingRef, ProductGone, SourceUnavailable, get_connector
from app.connectors.ebay import EbayConnector
from app.connectors.ebay import parse_item as ebay_parse
from app.connectors.generic import GenericConnector, parse_product_html
from app.connectors.mercadolibre import MercadoLibreConnector
from app.connectors.mercadolibre import parse_item as meli_parse

REF = ListingRef("MCO1234567890", "", "https://articulo.mercadolibre.com.co/MCO-1234567890-x-_JM")

ML_ITEM = {  # SIMULADO con la forma de GET /items/{id}
    "id": "MCO1234567890", "title": "Audífonos Sim", "price": 229900, "original_price": 300000, "currency_id": "COP",
    "available_quantity": 5, "status": "active", "condition": "new", "seller_id": 99,
    "pictures": [{"secure_url": "https://img.example/a.jpg"}], "shipping": {"free_shipping": True},
    "attributes": [{"id": "BRAND", "value_name": "Sony"}, {"id": "MODEL", "value_name": "WH-1000XM5"},
                   {"id": "GTIN", "value_name": "4548736134997"}],
    "variations": [{"id": 55, "price": 219900, "available_quantity": 0,
                    "attribute_combinations": [{"name": "Color", "value_name": "Negro"}]}],
}


def test_meli_parse_item_precio_promocion_y_marca():
    info = meli_parse(ML_ITEM)
    assert info.price == Decimal("229900") and info.currency == "COP" and info.available is True
    assert info.brand == "Sony" and info.model == "WH-1000XM5" and info.gtin == "4548736134997"
    kinds = {p.kind for p in info.promotions}
    assert kinds == {"discount", "free_shipping"}
    disc = next(p for p in info.promotions if p.kind == "discount")
    assert disc.previous_price == Decimal("300000") and disc.discount_pct == Decimal("23.37")
    assert info.shipping_cost == Decimal(0)


def test_meli_variante_usa_precio_y_stock_de_la_variante():
    info = meli_parse(ML_ITEM, "55")
    assert info.price == Decimal("219900") and info.available is False and info.attributes == {"Color": "Negro"}


def test_meli_sin_token_no_hay_fuente(monkeypatch):
    monkeypatch.setenv("MELI_ACCESS_TOKEN", "")
    from app.config import get_settings

    get_settings.cache_clear()
    c = MercadoLibreConnector()
    assert not c.configured() and c.status() == "needs_credentials"
    with pytest.raises(SourceUnavailable):
        c.fetch(REF)


def _with_meli_token(monkeypatch):
    monkeypatch.setenv("MELI_ACCESS_TOKEN", "TEST-TOKEN")
    from app.config import get_settings

    get_settings.cache_clear()


def test_meli_fetch_ok_y_envia_bearer(monkeypatch, mock_http):
    _with_meli_token(monkeypatch)
    seen = {}

    def handler(req: httpx.Request):
        seen["auth"] = req.headers.get("authorization")
        seen["path"] = req.url.path
        return httpx.Response(200, json=ML_ITEM)

    mock_http(handler)
    info = MercadoLibreConnector().fetch(REF)
    assert seen == {"auth": "Bearer TEST-TOKEN", "path": "/items/MCO1234567890"} and info.price == Decimal("229900")


@pytest.mark.parametrize("status,exc", [(404, ProductGone), (401, SourceUnavailable), (403, SourceUnavailable),
                                        (500, ConnectorError), (429, ConnectorError)])
def test_meli_errores_http(monkeypatch, mock_http, status, exc):
    _with_meli_token(monkeypatch)
    mock_http(lambda req: httpx.Response(status, json={}, headers={"Retry-After": "120"} if status == 429 else {}))
    with pytest.raises(exc) as e:
        MercadoLibreConnector().fetch(REF)
    if status == 429:
        assert e.value.retry_after_seconds == 120


def test_meli_fallo_de_red_es_error_temporal(monkeypatch, mock_http):
    _with_meli_token(monkeypatch)

    def boom(req):
        raise httpx.ConnectError("sin red")

    mock_http(boom)
    with pytest.raises(ConnectorError):
        MercadoLibreConnector().fetch(REF)


def test_meli_catalogo_no_identifica_publicacion(monkeypatch):
    _with_meli_token(monkeypatch)
    with pytest.raises(SourceUnavailable):
        MercadoLibreConnector().fetch(ListingRef("P:MCO19876543", "", "https://x"))


def test_meli_renueva_token_y_guarda_refresh_rotado(monkeypatch, mock_http, tmp_path):
    tokfile = tmp_path / "meli.json"
    for k, v in {"MELI_ACCESS_TOKEN": "", "MELI_CLIENT_ID": "cid", "MELI_CLIENT_SECRET": "sec",
                 "MELI_REFRESH_TOKEN": "R1", "MELI_TOKEN_FILE": str(tokfile)}.items():
        monkeypatch.setenv(k, v)
    from app.config import get_settings

    get_settings.cache_clear()
    calls = []

    def handler(req: httpx.Request):
        if req.url.path == "/oauth/token":
            body = dict(x.split("=") for x in req.content.decode().split("&"))
            calls.append(body)
            return httpx.Response(200, json={"access_token": "A1", "refresh_token": "R2", "expires_in": 21600})
        assert req.headers["authorization"] == "Bearer A1"
        return httpx.Response(200, json=ML_ITEM)

    mock_http(handler)
    c = MercadoLibreConnector()
    assert c.configured()
    c.fetch(REF)
    c.fetch(REF)  # el token se reutiliza: una sola renovación
    assert len(calls) == 1 and calls[0]["grant_type"] == "refresh_token" and calls[0]["refresh_token"] == "R1"
    assert json.loads(tokfile.read_text())["refresh_token"] == "R2"


EBAY_ITEM = {  # SIMULADO con la forma de la Browse API
    "title": "Sony Sim", "price": {"value": "199.99", "currency": "USD"}, "image": {"imageUrl": "https://i.example/x.jpg"},
    "condition": "New", "seller": {"username": "tienda1"}, "brand": "Sony", "mpn": "WH1000XM5", "gtin": ["4548736134997"],
    "shippingOptions": [{"shippingCost": {"value": "12.50", "currency": "USD"}}, {"shippingCost": {"value": "25.00"}}],
    "estimatedAvailabilities": [{"estimatedAvailabilityStatus": "IN_STOCK"}],
    "marketingPrice": {"originalPrice": {"value": "249.99"}, "discountPercentage": "20"},
}


def test_ebay_parse_item():
    info = ebay_parse(EBAY_ITEM)
    assert info.price == Decimal("199.99") and info.currency == "USD" and info.shipping_cost == Decimal("12.50")
    assert info.available is True and info.gtin == "4548736134997" and info.condition == "new"
    assert info.promotions[0].previous_price == Decimal("249.99")


def test_ebay_token_y_fetch(monkeypatch, mock_http):
    monkeypatch.setenv("EBAY_CLIENT_ID", "id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")
    from app.config import get_settings

    get_settings.cache_clear()
    hits = {"token": 0}

    def handler(req: httpx.Request):
        if "oauth2/token" in req.url.path:
            hits["token"] += 1
            assert req.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "T", "expires_in": 7200})
        assert req.headers["authorization"] == "Bearer T" and req.url.params["legacy_item_id"] == "334455667788"
        return httpx.Response(200, json=EBAY_ITEM)

    mock_http(handler)
    c = EbayConnector()
    ref = ListingRef("334455667788", "", "https://www.ebay.com/itm/334455667788")
    c.fetch(ref)
    c.fetch(ref)
    assert hits["token"] == 1


def test_ebay_sin_credenciales_y_errores(monkeypatch, mock_http):
    c = EbayConnector()
    ref = ListingRef("334455667788", "", "u")
    assert not c.configured()
    with pytest.raises(SourceUnavailable):
        c.fetch(ref)
    monkeypatch.setenv("EBAY_CLIENT_ID", "id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")
    from app.config import get_settings

    get_settings.cache_clear()
    mock_http(lambda req: httpx.Response(401, json={}) if "token" in req.url.path else httpx.Response(404, json={}))
    with pytest.raises(SourceUnavailable):
        c.fetch(ref)


@pytest.mark.parametrize("key", ["amazon", "aliexpress", "temu"])
def test_conectores_pendientes_no_inventan_precios(key):
    c = get_connector(key)
    assert c.status() == "unavailable" and not c.configured()
    with pytest.raises(SourceUnavailable):
        c.fetch(ListingRef("x", "", "https://example.com"))


HTML_LD = """<html><head><title>T</title>
<meta property="og:title" content="OG título"><meta property="og:image" content="https://i.example/og.jpg">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Product","name":"Zapatos Sim",
"image":["https://i.example/z.jpg"],"brand":{"@type":"Brand","name":"Marca"},"mpn":"M-1","gtin13":"1234567890123",
"offers":{"@type":"Offer","price":"89900","priceCurrency":"cop","availability":"https://schema.org/InStock"}}]}</script>
</head><body></body></html>"""

HTML_OG = """<html><head><meta property="og:title" content="Solo OG"><meta property="product:price:amount" content="1,250.50">
<meta property="product:price:currency" content="usd"></head></html>"""


def test_generic_parse_json_ld():
    info = parse_product_html(HTML_LD)
    assert info.title == "Zapatos Sim" and info.price == Decimal("89900") and info.currency == "COP"
    assert info.available is True and info.brand == "Marca" and info.gtin == "1234567890123"


def test_generic_parse_open_graph_y_sin_precio():
    info = parse_product_html(HTML_OG)
    assert info.price == Decimal("1250.50") and info.currency == "USD" and info.title == "Solo OG"
    nada = parse_product_html("<html><head><title>Hola</title></head></html>")
    assert nada.price is None and nada.title == "Hola"  # sin precio publicado: no se inventa
    assert parse_product_html("<html><script type='application/ld+json'>{roto</script>").price is None


def _generic_enabled(monkeypatch):
    monkeypatch.setenv("GENERIC_FETCH_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr("app.connectors.generic.assert_public_host", lambda host, port=None, resolver=None: None)


REF_G = ListingRef("abc", "", "https://tienda.ejemplo.com/p/zapatos")


def test_generic_fetch_respeta_robots(monkeypatch, mock_http):
    _generic_enabled(monkeypatch)

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /p/")
        raise AssertionError("no debe pedir la página si robots.txt lo prohíbe")

    mock_http(handler)
    with pytest.raises(SourceUnavailable):
        GenericConnector().fetch(REF_G)


def test_generic_fetch_ok(monkeypatch, mock_http):
    _generic_enabled(monkeypatch)

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=HTML_LD, headers={"content-type": "text/html; charset=utf-8"})

    mock_http(handler)
    assert GenericConnector().fetch(REF_G).price == Decimal("89900")


def test_generic_bloquea_ssrf_tambien_en_redirecciones(monkeypatch, mock_http):
    monkeypatch.setenv("GENERIC_FETCH_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    from app import urlutil

    def resolver(host, port, type=None):  # DNS SIMULADO: el sitio resuelve a una IP pública
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr("app.connectors.generic.assert_public_host",
                        lambda host, port=None: urlutil.assert_public_host(host, port, resolver=resolver))
    pages = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        pages.append(str(req.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    mock_http(handler)
    with pytest.raises(SourceUnavailable):
        GenericConnector().fetch(REF_G)
    assert len(pages) == 1  # nunca llegó a pedir la dirección interna


def test_generic_bloquea_dominio_que_resuelve_a_ip_privada(monkeypatch, mock_http):
    monkeypatch.setenv("GENERIC_FETCH_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    from app import urlutil

    def resolver(host, port, type=None):  # DNS SIMULADO: apunta a la red interna
        return [(2, 1, 6, "", ("10.1.2.3", port))]

    monkeypatch.setattr("app.connectors.generic.assert_public_host",
                        lambda host, port=None: urlutil.assert_public_host(host, port, resolver=resolver))
    mock_http(lambda req: (_ for _ in ()).throw(AssertionError("no debe hacer ninguna petición")))
    with pytest.raises(SourceUnavailable):
        GenericConnector().fetch(REF_G)


def test_generic_errores_http(monkeypatch, mock_http):
    _generic_enabled(monkeypatch)
    for status, exc in ((404, ProductGone), (429, ConnectorError), (503, ConnectorError), (403, SourceUnavailable)):
        from app.connectors.generic import clear_robots_cache

        clear_robots_cache()
        mock_http(lambda req, s=status: httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(s))
        with pytest.raises(exc):
            GenericConnector().fetch(REF_G)
