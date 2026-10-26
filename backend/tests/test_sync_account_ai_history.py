"""Sincronización, cuenta/privacidad, asistente y historial. Datos de tiendas SIMULADOS (TEST_SIMULATED)."""
from datetime import timedelta

from conftest import ML1, ML2, info, session, signup
from sqlalchemy import func, select

from app.models import PriceObservation, StoreListing, TrackedProduct, User, utcnow
from app.services import tracking

API = "/api/v1"


def add(client, h, url=ML1, **kw):
    r = client.post(f"{API}/tracked", json={"url": url, **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["item"]


def check(now=None, listing_id=None):
    with session() as db:
        lid = listing_id or db.scalar(select(StoreListing.id))
        return tracking.run_job_for_listing(db, lid, now)


def test_salud_y_privacidad_son_publicas(client):
    assert client.get(f"{API}/health").status_code == 200
    r = client.get(f"{API}/privacy")
    assert r.status_code == 200 and r.text.strip()
    stores = client.get(f"{API}/stores").json()
    text = str(stores).lower()
    assert "amazon" in text and "mercadolibre" in text


def test_sync_incremental_y_bajas(client, fake_ml):
    h, _ = signup(client)
    a = add(client, h, ML1)
    first = client.get(f"{API}/sync/changes", headers=h).json()
    assert [i["id"] for i in first["items"]] == [a["id"]] and first["server_time"]
    again = client.get(f"{API}/sync/changes", params={"since": first["server_time"]}, headers=h).json()
    assert again["items"] == []  # nada cambió desde entonces
    b = add(client, h, ML2)
    delta = client.get(f"{API}/sync/changes", params={"since": first["server_time"]}, headers=h).json()
    assert [i["id"] for i in delta["items"]] == [b["id"]]
    client.delete(f"{API}/tracked/{a['id']}", headers=h)
    delta = client.get(f"{API}/sync/changes", params={"since": first["server_time"]}, headers=h).json()
    gone = next(i for i in delta["items"] if i["id"] == a["id"])
    assert gone["deleted"] is True
    assert client.get(f"{API}/tracked", headers=h).json()["count"] == 1
    assert client.get(f"{API}/sync/changes", params={"since": "no-es-fecha"}, headers=h).status_code == 422


def test_exportar_datos_no_incluye_secretos(client, fake_ml):
    h, _ = signup(client)
    add(client, h, ML1, notes="mi nota")
    r = client.get(f"{API}/account/export", headers=h)
    assert r.status_code == 200
    body = r.text
    assert "mi nota" in body and "a@example.com" in body
    assert "password" not in body.lower() and "scrypt" not in body


def test_eliminar_cuenta_borra_todo(client, fake_ml):
    h, _ = signup(client)
    hb, _ = signup(client, "b@example.com")
    add(client, h, ML1)
    add(client, hb, ML1)
    assert client.request("DELETE", f"{API}/account", json={"password": "incorrecta-1"}, headers=h).status_code in (400, 401, 403)
    assert client.request("DELETE", f"{API}/account", json={"password": "Password123"}, headers=h).status_code == 200
    assert client.post(f"{API}/auth/login", json={"email": "a@example.com", "password": "Password123"}).status_code == 401
    assert client.get(f"{API}/auth/me", headers=h).status_code == 401
    with session() as db:
        assert db.scalar(select(func.count(User.id))) == 1
        assert db.scalar(select(func.count(TrackedProduct.id))) == 1  # sólo el del otro usuario
    assert client.get(f"{API}/tracked", headers=hb).json()["count"] == 1  # el otro usuario no se ve afectado


def test_historial_real_con_aviso_de_datos_limitados(client, fake_ml):
    h, _ = signup(client)
    item = add(client, h)
    r = client.get(f"{API}/tracked/{item['id']}/history", headers=h).json()
    assert r["points"] == [] and r["warnings"]  # sin datos: no se inventa nada
    t0 = utcnow() - timedelta(days=2)
    fake_ml.queue[:] = [info(100000)]
    check(now=t0)
    fake_ml.queue[:] = [info(90000)]
    check(now=t0 + timedelta(days=1))
    r = client.get(f"{API}/tracked/{item['id']}/history", params={"range": "7d"}, headers=h).json()
    assert [float(p["price"]) for p in r["points"]] == [100000, 90000]
    assert float(r["stats"]["min"]) == 90000 and float(r["stats"]["max"]) == 100000
    assert r["stats"]["average"] is None  # pocos datos: no se calcula un promedio engañoso
    assert any("limitado" in w for w in r["warnings"])
    assert set(r["available_ranges"]) <= {"7d", "30d", "90d", "6m", "1y"}
    assert client.get(f"{API}/tracked/{item['id']}/history", params={"range": "2y"}, headers=h).status_code == 422
    with session() as db:
        assert db.scalar(select(func.count(PriceObservation.id))) == 2


def test_asistente_requiere_premium_y_ejecuta_sobre_datos_reales(client, fake_ml):
    h, _ = signup(client)
    item = add(client, h)
    r = client.post(f"{API}/ai/command", json={"text": "avísame cuando baje de 200.000", "tracked_id": item["id"]}, headers=h)
    assert r.status_code == 402
    with session() as db:
        u = db.scalar(select(User))
        u.tier = "premium"
        db.commit()
    r = client.post(f"{API}/ai/command", json={"text": "avísame cuando baje de 200.000", "tracked_id": item["id"]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["interpreted_as"]["action"]
    got = client.get(f"{API}/tracked/{item['id']}", headers=h).json()
    assert float(got["target_price"]) == 200000
    r = client.post(f"{API}/ai/command", json={"text": "pausa este producto", "tracked_id": item["id"]}, headers=h)
    assert r.status_code == 200
    assert client.get(f"{API}/tracked/{item['id']}", headers=h).json()["paused"] is True


def test_asistente_no_inventa_cuando_no_entiende(client, fake_ml):
    h, _ = signup(client)
    with session() as db:
        db.scalar(select(User)).tier = "premium"
        db.commit()
    r = client.post(f"{API}/ai/command", json={"text": "blablabla xyz"}, headers=h)
    assert r.status_code == 200 and r.json().get("ok") is False


def test_ofertas_vacias_sin_datos_reales(client, fake_ml):
    h, _ = signup(client)
    add(client, h)
    assert client.get(f"{API}/offers", headers=h).json()["offers"] == []


def test_compartir_misma_publicacion_entre_usuarios_no_filtra_datos(client, fake_ml):
    ha, _ = signup(client, "a@example.com")
    hb, _ = signup(client, "b@example.com")
    add(client, ha, ML1, notes="secreto de A")
    add(client, hb, ML1)
    items = client.get(f"{API}/tracked", headers=hb).json()["items"]
    assert len(items) == 1 and items[0]["notes"] is None
    assert "secreto" not in client.get(f"{API}/account/export", headers=hb).text
