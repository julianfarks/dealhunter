from decimal import Decimal

import pytest

from app.aiparse import classify_intent, parse_amount, parse_percent
from app.currency import RateUnavailable, Rates, convert, parse_rates_payload
from app.util import fmt_money

RATES = Rates({"COP": Decimal("4000"), "EUR": Decimal("0.9")}, None, "TEST_SIMULATED")


def test_conversion_con_tasa_explicita():
    r = convert(Decimal("300000"), "COP", "USD", RATES)
    assert r.amount == Decimal("75.00") and r.rate == Decimal("0.00025") and r.source == "TEST_SIMULATED"
    assert convert(Decimal("10"), "USD", "EUR", RATES).amount == Decimal("9.00")
    assert convert(Decimal("400"), "COP", "COP", RATES).rate == Decimal(1)


def test_sin_tasa_no_se_inventa_nada():
    with pytest.raises(RateUnavailable):
        convert(Decimal("1"), "COP", "XYZ", RATES)
    with pytest.raises(RateUnavailable):
        convert(Decimal("1"), "COP", "USD", Rates())


def test_parse_payload_de_tasas():
    out = parse_rates_payload({"result": "success", "rates": {"USD": 1, "COP": 3900.5, "xx": 3, "BAD": -1}})
    assert out["COP"] == Decimal("3900.5") and "BAD" not in out
    with pytest.raises(ValueError):
        parse_rates_payload({"result": "error"})


def test_formato_de_dinero():
    assert fmt_money(Decimal("229900"), "COP") == "$229.900 COP"
    assert fmt_money(Decimal("19.5"), "USD") == "19,50 USD"
    assert fmt_money(None, "COP") == "—"


@pytest.mark.parametrize("texto,esperado", [
    ("tres millones", 3000000), ("150 mil", 150000), ("$1.200.000", 1200000), ("2,5 millones", 2500000),
    ("150.000 pesos", 150000), ("dos millones quinientos mil", 2500000), ("doscientos veinte mil", 220000),
    ("Avísame cuando este celular baje de tres millones de pesos", 3000000),
    ("Quiero estos audífonos por menos de 150.000 pesos", 150000), ("220000", 220000), ("veinticinco mil", 25000),
])
def test_importes_en_espanol(texto, esperado):
    assert parse_amount(texto) == Decimal(esperado)


def test_porcentajes():
    assert parse_percent("que baje un 20%") == Decimal("20")
    assert parse_percent("sin porcentaje") is None


@pytest.mark.parametrize("texto,accion", [
    ("Avísame cuando este celular baje de tres millones de pesos", "set_target"),
    ("Quiero estos audífonos por menos de 150.000 pesos", "set_target"),
    ("Busca si hay una promoción para este producto", "find_promotions"),
    ("Encuentra el mismo modelo en otras tiendas", "compare"),
    ("Muéstrame los cinco productos de mi carrito con mayor ahorro potencial", "top_savings"),
    ("¿Cuáles de mis productos están cerca del precio objetivo?", "near_target"),
    ("avísame si baja un 20%", "set_pct"),
    ("avísame cuando llegue al mínimo histórico", "set_historic_low"),
    ("¿Qué producto debería revisar primero?", "review_first"),
    ("hola qué tal", "unknown"),
])
def test_intenciones_del_documento(texto, accion):
    assert classify_intent(texto)["action"] == accion


def test_top_n_en_palabras():
    assert classify_intent("Muéstrame los cinco productos de mi carrito con mayor ahorro potencial")["n"] == 5
