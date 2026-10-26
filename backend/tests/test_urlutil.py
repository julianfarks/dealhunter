import pytest

from app.urlutil import (
    InvalidUrl, assert_public_host, detect_store, extract_url, guess_title, parse_product_url,
)


@pytest.mark.parametrize("url,store", [
    ("https://www.amazon.com/dp/B09XS7JWHH", "amazon"),
    ("https://www.amazon.com.co/gp/product/B09XS7JWHH", "amazon"),
    ("https://es.aliexpress.com/item/1005005123456789.html", "aliexpress"),
    ("https://articulo.mercadolibre.com.co/MCO-1234567890-x-_JM", "mercadolibre"),
    ("https://produto.mercadolivre.com.br/MLB-1234567890-x-_JM", "mercadolibre"),
    ("https://www.temu.com/x-g-601099512345678.html", "temu"),
    ("https://www.ebay.com/itm/334455667788", "ebay"),
    ("https://www.ebay.co.uk/itm/334455667788", "ebay"),
    ("https://tienda.ejemplo.com/producto/uno", "generic"),
])
def test_identifica_tienda(url, store):
    assert parse_product_url(url).store_key == store


def test_no_confunde_dominios_parecidos():
    assert detect_store("notamazon.com") == "generic"
    assert detect_store("amazon.evil.com") == "generic"
    assert detect_store("ebay.fake.net") == "generic"
    assert detect_store("amazon.ev.io") == "generic"
    assert detect_store("evilaliexpress.com") == "generic"
    assert detect_store("aliexpress.evil.com") == "generic"
    assert detect_store("temu.com.evil.io") == "generic"


def test_elimina_parametros_publicitarios_y_conserva_identificadores():
    p = parse_product_url("https://www.amazon.com/Sony/dp/B09XS7JWHH/ref=sr_1_1?crid=1&tag=foo&utm_source=a&psc=1")
    assert p.canonical_url == "https://www.amazon.com/dp/B09XS7JWHH" and p.external_id == "B09XS7JWHH"

    a = parse_product_url("https://es.aliexpress.com/item/1005005123456789.html?spm=a2g0o&sku_id=12000032&aff_fcid=x")
    assert a.variant_key == "12000032" and "spm" not in a.canonical_url and "sku_id=12000032" in a.canonical_url

    m = parse_product_url("https://articulo.mercadolibre.com.co/MCO-1234567890-x-_JM?matt_tool=1&variation=55")
    assert m.external_id == "MCO1234567890" and m.variant_key == "55" and "matt_tool" not in m.canonical_url

    e = parse_product_url("https://www.ebay.com/itm/Sony-Headphones/334455667788?var=5566&mkcid=1&hash=item1")
    assert e.canonical_url == "https://www.ebay.com/itm/334455667788?var=5566"

    g = parse_product_url("https://tienda.ejemplo.com/p/a?color=negro&utm_campaign=x&fbclid=zz#reviews")
    assert g.canonical_url == "https://tienda.ejemplo.com/p/a?color=negro"  # color es variante: se conserva


def test_misma_publicacion_con_distintos_parametros_da_misma_identidad():
    a = parse_product_url("https://www.amazon.com/dp/B09XS7JWHH?tag=x")
    b = parse_product_url("https://www.amazon.com/Sony-Algo/dp/B09XS7JWHH/ref=abc?utm_medium=z")
    assert (a.store_key, a.external_id, a.variant_key) == (b.store_key, b.external_id, b.variant_key)


def test_variantes_distintas_son_identidades_distintas():
    a = parse_product_url("https://es.aliexpress.com/item/1005005123456789.html?sku_id=1")
    b = parse_product_url("https://es.aliexpress.com/item/1005005123456789.html?sku_id=2")
    assert a.variant_key != b.variant_key


def test_enlaces_cortos_requieren_resolucion():
    p = parse_product_url("https://a.co/d/abc123")
    assert p.needs_resolution and p.external_id is None and p.store_key == "amazon"


@pytest.mark.parametrize("bad", [
    "", "   ", "ftp://x.com/a", "javascript:alert(1)", "http://localhost/a", "http://127.0.0.1/a",
    "http://169.254.169.254/latest/meta-data", "http://10.0.0.5/x", "http://192.168.1.1/x", "http://[::1]/x",
    "http://2130706433/", "https://user:pw@amazon.com/dp/B09XS7JWHH", "https://foo.internal/x",
    "http://tienda.com:8080/x", "https://a b.com", "https://amazon.com/sin-asin", "https://nodot/x",
    "https://" + "a" * 3000 + ".com/x", "https://x.com/\r\nHost: evil",
])
def test_rechaza_urls_invalidas_o_inseguras(bad):
    with pytest.raises(InvalidUrl):
        parse_product_url(bad)


def test_extract_url_de_texto_compartido():
    assert extract_url("Mira esto en Amazon: https://a.co/d/xyz123). ¡Genial!") == "https://a.co/d/xyz123"
    assert extract_url("sin enlace") is None
    assert extract_url("") is None


def test_ssrf_resolucion_dns():
    def privado(host, port, type=None):
        return [(2, 1, 6, "", ("10.0.0.7", port))]

    def mixto(host, port, type=None):
        return [(2, 1, 6, "", ("93.184.216.34", port)), (2, 1, 6, "", ("127.0.0.1", port))]

    def mapeado(host, port, type=None):
        return [(10, 1, 6, "", ("::ffff:192.168.1.1", port, 0, 0))]

    def publico(host, port, type=None):
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    for r in (privado, mixto, mapeado):
        with pytest.raises(InvalidUrl):
            assert_public_host("malo.example.com", 443, r)
    assert_public_host("bueno.example.com", 443, publico)
    with pytest.raises(InvalidUrl):
        assert_public_host("100.64.0.1", 443)  # CGNAT


def test_titulo_deducido_de_la_url():
    u = "https://articulo.mercadolibre.com.co/MCO-1234567890-audifonos-bluetooth-_JM"
    assert guess_title(u, "mercadolibre") == "Audifonos bluetooth"
    assert guess_title("https://www.amazon.com/dp/B09XS7JWHH", "amazon") is None
