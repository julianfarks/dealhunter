from conftest import ML1, session, signup
from sqlalchemy import select

from app import security
from app.config import get_settings
from app.models import User


def test_registro_login_refresh_y_me(client):
    h, data = signup(client)
    assert data["user"]["email"] == "a@example.com" and data["user"]["tier"] == "free"
    r = client.post("/api/v1/auth/login", json={"email": "A@Example.com", "password": "Password123"})
    assert r.status_code == 200 and r.json()["access_token"]
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me", headers=h).json()["email"] == "a@example.com"


def test_credenciales_incorrectas_no_revelan_si_el_usuario_existe(client):
    signup(client)
    a = client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "mala-clave-1"})
    b = client.post("/api/v1/auth/login", json={"email": "nadie@example.com", "password": "mala-clave-1"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_validaciones_de_registro(client):
    signup(client)
    assert client.post("/api/v1/auth/register", json={"email": "a@example.com", "password": "Password123"}).status_code == 409
    assert client.post("/api/v1/auth/register", json={"email": "no-es-correo", "password": "Password123"}).status_code == 422
    assert client.post("/api/v1/auth/register", json={"email": "b@example.com", "password": "corta"}).status_code == 422


def test_tokens_no_intercambiables_ni_manipulables(client):
    h, data = signup(client)
    # un access token no sirve como refresh, ni un refresh como access
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": data["access_token"]}).status_code == 401
    bad = {"Authorization": "Bearer " + data["refresh_token"]}
    assert client.get("/api/v1/auth/me", headers=bad).status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer basura"}).status_code == 401
    tampered = {"Authorization": "Bearer " + data["access_token"][:-3] + "abc"}
    assert client.get("/api/v1/auth/me", headers=tampered).status_code == 401


def test_cerrar_sesion_en_todos_lados_invalida_tokens(client):
    h, data = signup(client)
    assert client.post("/api/v1/auth/logout-all", headers=h).status_code == 200
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]}).status_code == 401


def test_limite_de_intentos_de_login(client, monkeypatch):
    signup(client)
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MIN", "3")
    get_settings.cache_clear()
    security.reset_rate_limits()
    codes = [client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "x" * 9}).status_code
             for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]


def test_contrasena_se_guarda_con_hash(client):
    signup(client, password="Password123")
    with session() as db:
        u = db.scalar(select(User))
        assert u.password_hash.startswith("scrypt$") and "Password123" not in u.password_hash


def test_aislamiento_entre_usuarios(client, fake_ml):
    ha, _ = signup(client, "a@example.com")
    hb, _ = signup(client, "b@example.com")
    r = client.post("/api/v1/tracked", json={"url": ML1}, headers=ha)
    tid = r.json()["item"]["id"]
    assert client.get(f"/api/v1/tracked/{tid}", headers=hb).status_code == 404
    assert client.patch(f"/api/v1/tracked/{tid}", json={"notes": "hack"}, headers=hb).status_code == 404
    assert client.delete(f"/api/v1/tracked/{tid}", headers=hb).status_code == 404
    assert client.get(f"/api/v1/tracked/{tid}/history", headers=hb).status_code == 404
    assert client.post(f"/api/v1/tracked/{tid}/alerts", json={"kind": "any_drop"}, headers=hb).status_code == 404
    assert client.get("/api/v1/tracked", headers=hb).json()["count"] == 0
    assert client.get(f"/api/v1/tracked/{tid}", headers=ha).status_code == 200
