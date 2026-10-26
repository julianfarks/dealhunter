"""Pruebas del seguimiento de precios y las alertas. Los precios son DATOS SIMULADOS (TEST_SIMULATED)."""
from datetime import timedelta

from conftest import ML1, ML2, info, session, signup
from sqlalchemy import func, select

from app.connectors.base import ConnectorError, ProductGone, SourceUnavailable
from app.models import PriceCheckJob, PriceObservation, StoreListing, utcnow
from app.services import tracking
from app.services.notifier import SendResult

API = "/api/v1"


def add(client, h, url=ML1, **kw):
    r = client.post(f"{API}/tracked", json={"url": url, **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["item"]


def feed(fake, *items):
    """Sustituye la cola del conector simulado (el último elemento se repite)."""
    fake.queue[:] = list(items)


def check(listing_id=None, now=None):
    with session() as db:
        lid = listing_id or db.scalar(select(StoreListing.id))
        return tracking.run_job_for_listing(db, lid, now)


def notifs(client, h, kind=None):
    rows = client.get(f"{API}/notifications", headers=h).json()["notifications"]
    return [n for n in rows if kind is None or n["kind"] == kind]


def state(client, h, tid):
    return client.get(f"{API}/tracked/{tid}", headers=h).json()


def test_ejemplo_del_enunciado_300000_a_215000_sin_duplicados(client, fake_ml):
    h, _ = signup(client)
    item = add(client, h, target_price="220000")
    client.post(f"{API}/tracked/{item['id']}/alerts", json={"kind": "any_drop"}, headers=h)
    t0 = utcnow()
    fake_ml.push(info(300000), info(215000), info(215000), info(210000))

    assert check(now=t0) == "ok"
    assert notifs(client, h) == []  # primer precio: nada que comparar y por encima del objetivo
    assert float(state(client, h, item["id"])["price_current"]) == 300000

    assert check(now=t0 + timedelta(hours=1)) == "ok"
    ns = notifs(client, h)
    assert {n["kind"] for n in ns} == {"any_drop", "target_price"}
    drop = next(n for n in ns if n["kind"] == "any_drop")
    assert "$300.000 COP" in drop["body"] and "$215.000 COP" in drop["body"] and "$85.000 COP" in drop["body"]
    assert drop["payload"]["current_price"] == "215000.00" and drop["payload"]["previous_price"] == "300000.00"

    check(now=t0 + timedelta(hours=2))  # mismo precio: no se duplica
    assert len(notifs(client, h)) == 2

    check(now=t0 + timedelta(hours=3))  # precio estrictamente mejor: se avisa de nuevo
    assert len(notifs(client, h, "target_price")) == 2
    assert len(notifs(client, h, "any_drop")) == 2


def test_alerta_se_rearma_cuando_el_precio_vuelve_a_subir(client, fake_ml):
    h, _ = signup(client)
    add(client, h, target_price="220000")
    t0 = utcnow()
    fake_ml.push(info(215000), info(215000), info(260000), info(215000))
    check(now=t0)
    assert len(notifs(client, h, "target_price")) == 1
    check(now=t0 + timedelta(hours=1))
    assert len(notifs(client, h, "target_price")) == 1
    check(now=t0 + timedelta(hours=2))  # sube por encima del objetivo: se rearma, sin aviso
    assert len(notifs(client, h, "target_price")) == 1
    check(now=t0 + timedelta(hours=3))  # vuelve a cumplirse: nuevo aviso legítimo
    assert len(notifs(client, h, "target_price")) == 2


def test_porcentaje_respecto_al_precio_registrado(client, fake_ml):
    h, _ = signup(client)
    item = add(client, h)
    client.post(f"{API}/tracked/{item['id']}/alerts", json={"kind": "pct_drop", "threshold": "20"}, headers=h)
    t0 = utcnow()
    fake_ml.push(info(100000), info(90000), info(79000))
    check(now=t0)
    check(now=t0 + timedelta(hours=1))
    assert notifs(client, h, "pct_drop") == []  # 10 % < 20 %
    check(now=t0 + timedelta(hours=2))
    assert len(notifs(client, h, "pct_drop")) == 1


def test_objetivo_en_otra_moneda_sin_tasa_no_dispara_ni_inventa(client, fake_ml):
    h, _ = signup(client)
    add(client, h, target_price="50", target_currency="USD")
    fake_ml.push(info(1000))  # 1.000 COP; sin tasa de cambio guardada no se puede comparar
    check()
    assert notifs(client, h) == []


def test_sin_cambios_no_se_guardan_observaciones_repetidas(client, fake_ml):
    h, _ = signup(client)
    add(client, h)
    t0 = utcnow()
    fake_ml.push(info(100000))
    for i in range(4):
        check(now=t0 + timedelta(hours=i))
    with session() as db:
        assert db.scalar(select(func.count(PriceObservation.id))) == 1
    feed(fake_ml, info(95000))
    check(now=t0 + timedelta(hours=5))
    with session() as db:
        assert db.scalar(select(func.count(PriceObservation.id))) == 2


def test_estados_honestos_ante_cada_resultado(client, fake_ml):
    h, _ = signup(client)
    item = add(client, h)
    tid = item["id"]
    t0 = utcnow()

    feed(fake_ml, ConnectorError("Límite de peticiones"))
    assert check(now=t0) == "failed"
    s = state(client, h, tid)
    assert s["state"] == "temporarily_failed" and s["price_current"] is None

    feed(fake_ml, info(None))
    check(now=t0 + timedelta(hours=1))
    assert state(client, h, tid)["state"] == "price_unavailable"

    feed(fake_ml, ProductGone("La publicación ya no existe"))
    assert check(now=t0 + timedelta(hours=2)) == "gone"
    assert state(client, h, tid)["state"] == "unavailable_in_store"

    feed(fake_ml, SourceUnavailable("Sin permiso de la tienda"))
    assert check(now=t0 + timedelta(hours=3)) == "needs_source"
    assert state(client, h, tid)["state"] == "needs_source"

    feed(fake_ml, info(120000))
    check(now=t0 + timedelta(hours=4))
    s = state(client, h, tid)
    assert s["state"] == "active" and float(s["price_current"]) == 120000


def test_producto_pausado_no_dispara_alertas_y_no_se_consulta(client, fake_ml):
    h, _ = signup(client)
    item = add(client, h, target_price="220000")
    client.post(f"{API}/tracked/bulk", json={"ids": [item["id"]], "action": "pause"}, headers=h)
    fake_ml.push(info(100000))
    check()
    assert notifs(client, h) == []
    assert state(client, h, item["id"])["state"] == "paused"


def test_un_solo_trabajo_por_publicacion_aunque_la_sigan_varios_usuarios(client, fake_ml):
    ha, _ = signup(client, "a@example.com")
    hb, _ = signup(client, "b@example.com")
    add(client, ha, target_price="220000")
    add(client, hb, target_price="300000")
    with session() as db:
        assert db.scalar(select(func.count(PriceCheckJob.id))) == 1
    fake_ml.push(info(250000))
    check()
    assert fake_ml.calls == 1  # una sola consulta a la tienda para ambos
    assert notifs(client, ha) == [] and len(notifs(client, hb, "target_price")) == 1


def test_cola_solo_toma_trabajos_vencidos_y_respeta_el_bloqueo(client, fake_ml):
    h, _ = signup(client)
    add(client, h, ML1)
    add(client, h, ML2)
    fake_ml.push(info(100000))
    now = utcnow() + timedelta(minutes=1)
    with session() as db:
        first = tracking.claim_due_jobs(db, now, 10)
        assert len(first) == 2
        assert tracking.claim_due_jobs(db, now, 10) == []  # ya reclamados: otro worker no los repite
    with session() as db:
        counts = tracking.run_due_jobs(db, now + timedelta(hours=1))
        assert counts == {"ok": 2}
        assert tracking.run_due_jobs(db, now + timedelta(hours=1)) == {}  # reprogramados al futuro


def test_fallos_repetidos_usan_espera_creciente(client, fake_ml):
    h, _ = signup(client)
    add(client, h)
    fake_ml.push(ConnectorError("caído"))
    t0 = utcnow()
    waits = []
    for _ in range(3):
        check(now=t0)
        with session() as db:
            waits.append(db.scalar(select(PriceCheckJob.next_run_at)) - t0)
    assert waits[0] < waits[1] < waits[2]


def test_limitador_por_tienda_difiere_sin_perder_el_trabajo(client, fake_ml):
    h, _ = signup(client)
    add(client, h)
    fake_ml.push(info(100000))
    tracking.limiter.min_intervals["mercadolibre"] = 3600
    tracking.limiter.default_interval = 3600
    tracking.limiter.try_acquire("mercadolibre")
    assert check() == "rate_limited"
    assert fake_ml.calls == 0
    with session() as db:
        assert db.scalar(select(func.count(PriceCheckJob.id))) == 1


def test_precio_inicial_y_ahorro_potencial(client, fake_ml):
    h, _ = signup(client)
    item = add(client, h)
    t0 = utcnow()
    fake_ml.push(info(300000), info(250000))
    check(now=t0)
    check(now=t0 + timedelta(hours=1))
    s = state(client, h, item["id"])
    assert float(s["price_initial"]) == 300000 and float(s["price_current"]) == 250000
    assert round(float(s["change_from_initial_pct"]), 2) == round((250000 - 300000) / 300000 * 100, 2)


def test_paginacion_y_lectura_de_notificaciones(client, fake_ml):
    h, _ = signup(client)
    add(client, h, target_price="220000")
    fake_ml.push(info(215000))
    check()
    n = notifs(client, h)[0]
    assert n["read"] is False
    assert client.post(f"{API}/notifications/{n['id']}/read", headers=h).status_code == 200
    assert notifs(client, h)[0]["read"] is True
    assert client.post(f"{API}/notifications/read-all", headers=h).status_code == 200


# ---- entrega push ----------------------------------------------------------------------------------------------------

TOKEN = "t" * 40


def test_push_se_envia_a_los_dispositivos_registrados(client, fake_ml, sender):
    h, _ = signup(client)
    client.post(f"{API}/devices", json={"token": TOKEN}, headers=h)
    add(client, h, target_price="220000")
    fake_ml.push(info(215000))
    check()
    assert len(sender.sent) == 1
    token, title, body, data = sender.sent[0]
    assert token == TOKEN and "$215.000 COP" in body and data["kind"] == "target_price"
    assert notifs(client, h)[0]["delivery_status"] == "sent"


def test_sin_dispositivos_no_se_finge_el_envio(client, fake_ml, sender):
    h, _ = signup(client)
    add(client, h, target_price="220000")
    fake_ml.push(info(215000))
    check()
    assert sender.sent == [] and notifs(client, h)[0]["delivery_status"] == "no_devices"


def test_fcm_no_configurado_se_reporta(client, fake_ml, sender):
    h, _ = signup(client)
    client.post(f"{API}/devices", json={"token": TOKEN}, headers=h)
    sender.is_configured = False
    add(client, h, target_price="220000")
    fake_ml.push(info(215000))
    check()
    assert notifs(client, h)[0]["delivery_status"] == "not_configured"


def test_token_invalido_se_elimina_y_fallo_temporal_se_reintenta(client, fake_ml, sender):
    h, _ = signup(client)
    client.post(f"{API}/devices", json={"token": TOKEN}, headers=h)
    add(client, h, target_price="220000")
    fake_ml.push(info(215000))
    sender.script = [SendResult.TRANSIENT]
    t0 = utcnow()
    check(now=t0)
    assert notifs(client, h)[0]["delivery_status"] == "pending"
    from app.services.notifier import deliver_pending
    with session() as db:
        assert deliver_pending(db, t0 + timedelta(hours=2)) == 1
    assert notifs(client, h)[0]["delivery_status"] == "sent"

    sender.script = [SendResult.INVALID_TOKEN]
    feed(fake_ml, info(210000))
    check(now=t0 + timedelta(hours=3))
    from app.models import DeviceToken
    with session() as db:
        assert db.scalar(select(func.count(DeviceToken.id))) == 0


def test_horas_de_silencio_difieren_y_luego_entregan(client, fake_ml, sender):
    h, _ = signup(client)
    client.post(f"{API}/devices", json={"token": TOKEN}, headers=h)
    # offset 0 => hora local = UTC; silencio de 00:00 a 23:59 cubre casi todo el día
    client.put(f"{API}/preferences", json={"utc_offset_minutes": 0, "quiet_start": "22:00", "quiet_end": "07:00"}, headers=h)
    add(client, h, target_price="220000")
    fake_ml.push(info(215000))
    night = utcnow().replace(hour=23, minute=0, second=0, microsecond=0)
    check(now=night)
    assert sender.sent == [] and notifs(client, h)[0]["delivery_status"] == "deferred"
    from app.services.notifier import deliver_pending
    with session() as db:
        assert deliver_pending(db, night + timedelta(hours=1)) == 0  # sigue en silencio
        assert deliver_pending(db, night + timedelta(hours=9)) == 1  # 08:00
    assert len(sender.sent) == 1


def test_tipo_silenciado_no_genera_notificacion(client, fake_ml):
    h, _ = signup(client)
    client.put(f"{API}/preferences", json={"muted_kinds": ["target_price"]}, headers=h)
    add(client, h, target_price="220000")
    fake_ml.push(info(215000))
    check()
    assert notifs(client, h) == []


def test_tope_diario_de_notificaciones(client, fake_ml):
    h, _ = signup(client)
    client.put(f"{API}/preferences", json={"max_notifications_per_day": 1}, headers=h)
    item = add(client, h, target_price="220000")
    client.post(f"{API}/tracked/{item['id']}/alerts", json={"kind": "any_drop"}, headers=h)
    t0 = utcnow()
    fake_ml.push(info(300000), info(215000))
    check(now=t0)
    check(now=t0 + timedelta(hours=1))
    statuses = sorted(n["delivery_status"] for n in notifs(client, h))
    assert len(statuses) == 2 and statuses.count("deferred") == 1
