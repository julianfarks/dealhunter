"""Configuración de pruebas.

IMPORTANTE: todos los precios/respuestas de tiendas que aparecen en las pruebas son DATOS SIMULADOS
(fuente "TEST_SIMULATED") y sirven sólo para verificar la lógica; no son precios reales.
"""
import os
import tempfile
from decimal import Decimal

_TMP = tempfile.mkdtemp(prefix="dealhunter-test-")
os.environ.update(
    DATABASE_URL=f"sqlite:///{_TMP}/test.db",
    SECRET_KEY="test-secret-key-test-secret-key-0123456789",
    FREE_TRACKED_LIMIT="5",
    PREMIUM_TRACKED_LIMIT="50",
    RATE_LIMIT_AUTH_PER_MIN="1000",
    RATE_LIMIT_WRITE_PER_MIN="1000",
    GENERIC_FETCH_ENABLED="false",
    MELI_ACCESS_TOKEN="",
    EBAY_CLIENT_ID="",
    EBAY_CLIENT_SECRET="",
    ANTHROPIC_API_KEY="",
    FCM_PROJECT_ID="",
    FCM_SERVICE_ACCOUNT_FILE="",
)

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db as db_module  # noqa: E402
from app import security  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.connectors import registry  # noqa: E402
from app.connectors.base import Connector, ProductInfo  # noqa: E402
from app.connectors.ebay import reset_token_state as reset_ebay  # noqa: E402
from app.connectors.generic import clear_robots_cache  # noqa: E402
from app.connectors.http import set_client_for_tests  # noqa: E402
from app.connectors.mercadolibre import reset_token_state as reset_meli  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User, UserPreference, utcnow  # noqa: E402
from app.services import notifier, tracking  # noqa: E402

ML1 = "https://articulo.mercadolibre.com.co/MCO-1234567890-audifonos-inalambricos-_JM"
ML2 = "https://articulo.mercadolibre.com.co/MCO-2234567890-celular-samsung-_JM"
ML3 = "https://articulo.mercadolibre.com.co/MCO-3234567890-tablet-_JM"
EBAY1 = "https://www.ebay.com/itm/334455667788"
AMAZON1 = "https://www.amazon.com/Sony-WH-1000XM5/dp/B09XS7JWHH"


class FakeConnector(Connector):
    """Conector SIMULADO (sólo pruebas). Entrega, en orden, lo que se le encole; el último se repite."""

    def __init__(self, key="mercadolibre", configured=True):
        self.key, self.name, self._configured = key, f"Simulado {key}", configured
        self.queue: list = []
        self.calls = 0
        self.searches: list = []

    def configured(self):
        return self._configured

    def push(self, *items):
        self.queue.extend(items)
        return self

    def fetch(self, ref):
        self.calls += 1
        item = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def search(self, query, limit=5):
        return self.searches


def info(price, currency="COP", **kw) -> ProductInfo:
    kw.setdefault("title", "Audífonos inalámbricos (simulado)")
    kw.setdefault("available", True)
    return ProductInfo(source="TEST_SIMULATED", price=None if price is None else Decimal(str(price)),
                       currency=currency, **kw)


class FakeSender:
    """Emisor de push SIMULADO."""

    def __init__(self):
        self.sent = []
        self.script: list = []  # resultados a devolver en orden; vacío => OK
        self.is_configured = True

    def configured(self):
        return self.is_configured

    def send(self, token, title, body, data):
        from app.services.notifier import SendResult

        self.sent.append((token, title, body, data))
        return self.script.pop(0) if self.script else SendResult.OK


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    get_settings.cache_clear()
    db_module.Base.metadata.drop_all(db_module.engine)
    db_module.Base.metadata.create_all(db_module.engine)
    security.reset_rate_limits()
    tracking.limiter.reset()
    tracking.limiter.min_intervals.clear()
    tracking.limiter.default_interval = 0
    reset_meli()
    reset_ebay()
    clear_robots_cache()
    set_client_for_tests(None)
    notifier.set_sender_for_tests(FakeSender())
    monkeypatch.setattr(tracking, "check_listing_in_background", lambda listing_id: None)
    yield
    set_client_for_tests(None)
    get_settings.cache_clear()


@pytest.fixture
def fake_ml():
    fc = FakeConnector("mercadolibre")
    prev = registry.register_for_tests(fc)
    yield fc
    registry.unregister_for_tests("mercadolibre", prev)


@pytest.fixture
def fake_ebay():
    fc = FakeConnector("ebay")
    prev = registry.register_for_tests(fc)
    yield fc
    registry.unregister_for_tests("ebay", prev)


@pytest.fixture
def fake_generic():
    fc = FakeConnector("generic")
    prev = registry.register_for_tests(fc)
    yield fc
    registry.unregister_for_tests("generic", prev)


@pytest.fixture
def sender():
    return notifier._sender


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_http():
    """Instala un cliente HTTP con transporte simulado. Uso: mock_http(handler)."""

    def install(handler):
        set_client_for_tests(httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False))

    return install


def session():
    return db_module.SessionLocal()


def make_user(db, email="u@example.com", tier="free", offset=-300) -> User:
    u = User(email=email, password_hash="x", tier=tier)
    db.add(u)
    db.flush()
    db.add(UserPreference(user_id=u.id, utc_offset_minutes=offset))
    db.commit()
    return u


def signup(client, email="a@example.com", password="Password123"):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}, r.json()


def base_time():
    return utcnow() + __import__("datetime").timedelta(minutes=1)
