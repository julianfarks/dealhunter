import httpx
from conftest import AMAZON1, EBAY1, ML1, ML2, session, signup
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import PriceAlert, PriceCheckJob, StoreListing, TrackedProduct

API = "/api/v1"


def add(client, h, url=ML1, **kw):
    return client.post(f"{API}/tracked", json={"url": url, **kw}, headers=h)


def test_anadir_producto_manualmente(client, fake_ml):
    h, _ = signup(client)
    r = add(client, h)
    assert r.status_code == 201
    body = r.json()
    item = body["item"]
    assert body["duplicate"] is False and body["message"] == "Añadido a tu carrito"
    assert item["store_key"] == "mercadolibre" and item["state"] == "waiting_first_check"
    assert item["title"] == "Audifonos inalambricos" and item["title_is_guess"] is True
    assert item["price_current"] is None  # todavía no hay precio real: no se inventa
    assert item["state_label"] == "Esperando la primera consulta"


def test_evita_duplicados_aunque_cambien_los_parametros(client, fake_ml):
    h, _ = signup(client)
    first = add(client, h).json()["item"]
    r = add(client, h, ML1 + "?matt_tool=123&utm_source=x")
    assert r.status_code == 201  # el endpoint responde 201; el cuerpo indica duplicado
    body = r.json()
    assert body["duplicate"] is True and body["item"]["id"] == first["id"]
    assert client.get(f"{API}/tracked", headers=h).json()["count"] == 1


def test_variantes_distintas_no_son_duplicado(client, fake_ml):
    h, _ = signup(client)
    a = add(client, h, ML1 + "?variation=1").json()
    b = add(client, h, ML1 + "?variation=2").json()
    assert a["item"]["id"] != b["item"]["id"] and b["duplicate"] is False


def test_urls_invalidas(client):
    h, _ = signup(client)
    for bad in ["no es una url", "ftp://x.com/a", "http://127.0.0.1/admin", "http://169.254.169.254/",
                "https://amazon.com/sin-asin"]:
        r = add(client, h, bad)
        assert r.status_code == 422, bad
        assert r.json()["detail"]["retryable"] is False


def test_persistencia_y_recuperacion_del_carrito(client, fake_ml):
    h, data = signup(client)
    add(client, h, ML1, notes="regalo")
    add(client, h, ML2)
    otro = TestClient(app)  # "otro dispositivo" / reinicio: sólo cuenta lo que hay en la base de datos
    login = otro.post(f"{API}/auth/login", json={"email": "a@example.com", "password": "Password123"}).json()
    h2 = {"Authorization": "Bearer " + login["access_token"]}
    items = otro.get(f"{API}/tracked", headers=h2).json()["items"]
    assert len(items) == 2 and {i["notes"] for i in items} == {"regalo", None}
    with session() as db:
        assert db.scalar(select(func.count(TrackedProduct.id))) == 2


def test_limite_del_plan_se_controla_en_el_backend(client, fake_ml):
    h, _ = signup(client)
    for i in range(5):
        assert add(client, h, f"https://articulo.mercadolibre.com.co/MCO-{1000000000 + i}-prod-_JM").status_code == 201
    r = add(client, h, "https://articulo.mercadolibre.com.co/MCO-1999999999-prod-_JM")
    assert r.status_code == 402 and "plan" in r.json()["detail"]["message"].lower()
    # archivar libera cupo
    first = client.get(f"{API}/tracked", headers=h).json()["items"][0]["id"]
    client.post(f"{API}/tracked/bulk", json={"ids": [first], "action": "archive"}, headers=h)
    assert add(client, h, "https://articulo.mercadolibre.com.co/MCO-1999999999-prod-_JM").status_code == 201


def test_tienda_sin_fuente_se_conserva_sin_inventar_precio(client):
    h, _ = signup(client)
    item = add(client, h, AMAZON1).json()["item"]
    assert item["state"] == "needs_source" and item["state_label"] == "Requiere una fuente de datos compatible"
    assert item["price_current"] is None and item["store_name"] == "Amazon"
    assert client.get(f"{API}/tracked", headers=h).json()["count"] == 1


def test_acciones_del_carrito(client, fake_ml):
    h, _ = signup(client)
    a = add(client, h, ML1).json()["item"]["id"]
    b = add(client, h, ML2).json()["item"]["id"]
    r = client.patch(f"{API}/tracked/{a}", json={"notes": "Para mamá", "list_name": "Regalos", "priority": 2}, headers=h)
    assert r.json()["notes"] == "Para mamá" and r.json()["list_name"] == "Regalos" and r.json()["priority"] == 2
    assert client.get(f"{API}/tracked/lists", headers=h).json()["lists"] == ["Regalos"]
    # archivar / restaurar
    client.post(f"{API}/tracked/bulk", json={"ids": [a, b], "action": "archive"}, headers=h)
    assert client.get(f"{API}/tracked", headers=h).json()["count"] == 0
    assert client.get(f"{API}/tracked?archived=true", headers=h).json()["count"] == 2
    client.post(f"{API}/tracked/bulk", json={"ids": [a], "action": "restore"}, headers=h)
    assert [i["id"] for i in client.get(f"{API}/tracked", headers=h).json()["items"]] == [a]
    # comprado
    r = client.patch(f"{API}/tracked/{a}", json={"purchased": True, "purchased_price": "250000"}, headers=h)
    assert r.json()["purchased"] is True and float(r.json()["purchased_price"]) == 250000
    assert client.get(f"{API}/tracked?purchased=true", headers=h).json()["count"] == 1
    assert client.get(f"{API}/tracked", headers=h).json()["count"] == 0
    # eliminar
    assert client.delete(f"{API}/tracked/{a}", headers=h).status_code == 200
    assert client.get(f"{API}/tracked/{a}", headers=h).status_code == 404
    # acciones en grupo sobre ids ajenos/inexistentes no fallan ni afectan a otros
    r = client.post(f"{API}/tracked/bulk", json={"ids": [999999], "action": "delete"}, headers=h)
    assert r.json()["affected"] == 0


def test_filtros_y_orden(client, fake_ml, fake_ebay):
    h, _ = signup(client)
    add(client, h, ML1, notes="negros", priority=1)
    add(client, h, EBAY1, notes="importado")
    assert client.get(f"{API}/tracked?store=ebay", headers=h).json()["count"] == 1
    assert client.get(f"{API}/tracked?q=importado", headers=h).json()["count"] == 1
    assert client.get(f"{API}/tracked?q=nada-coincide", headers=h).json()["count"] == 0
    assert client.get(f"{API}/tracked?state=waiting_first_check", headers=h).json()["count"] == 2
    by_prio = client.get(f"{API}/tracked?sort=priority", headers=h).json()["items"]
    assert by_prio[0]["priority"] == 1
    assert client.get(f"{API}/tracked?sort=invalido", headers=h).status_code == 422


def test_precio_objetivo_crea_y_desactiva_su_alerta(client, fake_ml):
    h, _ = signup(client)
    item = add(client, h, ML1, target_price="220000").json()["item"]
    assert float(item["target_price"]) == 220000 and item["target_currency"] == "COP"
    assert [a["kind"] for a in item["alerts"]] == ["target_price"]
    r = client.patch(f"{API}/tracked/{item['id']}", json={"target_price": None}, headers=h).json()
    assert r["target_price"] is None and r["alerts"][0]["active"] is False


def test_alertas_crud_y_limites_del_plan(client, fake_ml):
    h, _ = signup(client)
    tid = add(client, h).json()["item"]["id"]
    base = f"{API}/tracked/{tid}/alerts"
    assert client.post(base, json={"kind": "coupon"}, headers=h).status_code == 402  # premium
    assert client.post(base, json={"kind": "better_elsewhere"}, headers=h).status_code == 402
    assert client.post(base, json={"kind": "pct_drop"}, headers=h).status_code == 422  # falta el porcentaje
    assert client.post(base, json={"kind": "pct_drop", "threshold": "150"}, headers=h).status_code == 422
    assert client.post(base, json={"kind": "inventada"}, headers=h).status_code == 422
    r = client.post(base, json={"kind": "pct_drop", "threshold": "15"}, headers=h)
    assert r.status_code == 201
    aid = r.json()["id"]
    assert client.post(base, json={"kind": "any_drop"}, headers=h).status_code == 201
    assert client.patch(f"{base}/{aid}", json={"active": False}, headers=h).json()["active"] is False
    assert client.patch(f"{base}/{aid}", json={"active": True}, headers=h).json()["active"] is True
    assert len(client.get(base, headers=h).json()["alerts"]) == 2
    assert client.delete(f"{base}/{aid}", headers=h).status_code == 200
    assert client.delete(f"{base}/{aid}", headers=h).status_code == 404
    with session() as db:
        assert db.scalar(select(func.count(PriceAlert.id))) == 1


def test_enlace_corto_se_resuelve_con_guardia_ssrf(client, fake_ml, mock_http, monkeypatch):
    monkeypatch.setattr("app.services.listings.assert_public_host", lambda host, port=None: None)
    mock_http(lambda req: httpx.Response(302, headers={"location": ML1 + "?utm_source=share"}))
    h, _ = signup(client)
    r = add(client, h, "https://meli.la/2abcDEF")
    assert r.status_code == 201 and r.json()["item"]["store_key"] == "mercadolibre"
    with session() as db:
        assert db.scalar(select(StoreListing.external_id)) == "MCO1234567890"


def test_enlace_corto_con_error_de_red_es_reintentable(client, mock_http, monkeypatch):
    monkeypatch.setattr("app.services.listings.assert_public_host", lambda host, port=None: None)

    def boom(req):
        raise httpx.ConnectError("sin red")

    mock_http(boom)
    h, _ = signup(client)
    r = add(client, h, "https://a.co/d/xyz")
    assert r.status_code == 503 and r.json()["detail"]["retryable"] is True  # la app guarda el enlace y reintenta
    with session() as db:
        assert db.scalar(select(func.count(TrackedProduct.id))) == 0


def test_enlace_corto_que_apunta_a_ip_interna_se_rechaza(client, mock_http, monkeypatch):
    monkeypatch.setattr("app.services.listings.assert_public_host", lambda host, port=None: None)
    mock_http(lambda req: httpx.Response(302, headers={"location": "http://169.254.169.254/latest"}))
    h, _ = signup(client)
    r = add(client, h, "https://a.co/d/xyz")
    assert r.status_code == 422


def test_al_anadir_se_programa_la_primera_consulta(client, fake_ml, monkeypatch):
    calls = []
    monkeypatch.setattr("app.services.tracking.check_listing_in_background", lambda lid: calls.append(lid))
    h, _ = signup(client)
    add(client, h)
    add(client, h)  # duplicado: no se vuelve a consultar
    assert len(calls) == 1
    with session() as db:
        assert db.scalar(select(func.count(PriceCheckJob.id))) == 1


def test_actualizar_manual_tiene_enfriamiento(client, fake_ml, monkeypatch):
    from datetime import timedelta

    from app.models import utcnow

    calls = []
    monkeypatch.setattr("app.services.tracking.check_listing_in_background", lambda lid: calls.append(lid))
    h, _ = signup(client)
    tid = add(client, h).json()["item"]["id"]
    calls.clear()
    assert client.post(f"{API}/tracked/{tid}/refresh", headers=h).json()["queued"] is True
    with session() as db:
        job = db.scalar(select(PriceCheckJob))
        job.last_run_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert client.post(f"{API}/tracked/{tid}/refresh", headers=h).json()["queued"] is False
    assert len(calls) == 1
