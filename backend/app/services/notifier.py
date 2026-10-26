"""Notificaciones: creación sin duplicados, preferencias/horario de silencio y entrega push (FCM HTTP v1)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..connectors.http import get_client
from ..models import DeviceToken, Notification, TrackedProduct, User, UserPreference, utcnow

log = logging.getLogger("dealhunter.notifier")

MAX_DELIVERY_ATTEMPTS = 5


class SendResult(str, Enum):
    OK = "ok"
    INVALID_TOKEN = "invalid_token"
    TRANSIENT = "transient"
    ERROR = "error"


class FcmSender:
    """Envía por Firebase Cloud Messaging HTTP v1 con una cuenta de servicio."""

    SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

    def __init__(self) -> None:
        self._creds = None

    def configured(self) -> bool:
        s = get_settings()
        return bool(s.fcm_project_id and s.fcm_service_account_file)

    def _access_token(self) -> str:
        from google.auth.transport.requests import Request  # import perezoso: dependencia opcional
        from google.oauth2 import service_account

        if self._creds is None:
            self._creds = service_account.Credentials.from_service_account_file(
                get_settings().fcm_service_account_file, scopes=[self.SCOPE]
            )
        if not self._creds.valid:
            self._creds.refresh(Request())
        return self._creds.token

    def send(self, token: str, title: str, body: str, data: dict[str, str]) -> SendResult:
        s = get_settings()
        try:
            access = self._access_token()
            resp = get_client().post(
                f"https://fcm.googleapis.com/v1/projects/{s.fcm_project_id}/messages:send",
                headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
                json={"message": {
                    "token": token,
                    "notification": {"title": title, "body": body},
                    "data": data,
                    "android": {"priority": "HIGH", "notification": {"channel_id": "price_alerts"}},
                }},
            )
        except Exception:
            log.warning("FCM: fallo de red o de credenciales")
            return SendResult.TRANSIENT
        if resp.status_code == 200:
            return SendResult.OK
        if resp.status_code in (404, 400):
            try:
                status = resp.json().get("error", {}).get("status", "")
            except Exception:
                status = ""
            if status in ("NOT_FOUND", "UNREGISTERED", "INVALID_ARGUMENT"):
                return SendResult.INVALID_TOKEN
        if resp.status_code in (429, 500, 502, 503, 504):
            return SendResult.TRANSIENT
        return SendResult.ERROR


_sender: FcmSender | object = FcmSender()


def set_sender_for_tests(sender) -> None:
    global _sender
    _sender = sender


def _prefs(db: Session, user_id: int) -> UserPreference:
    p = db.get(UserPreference, user_id)
    if p is None:
        p = UserPreference(user_id=user_id)
        db.add(p)
        db.flush()
    return p


def _parse_hhmm(s: str | None) -> tuple[int, int] | None:
    if not s:
        return None
    try:
        h, m = s.split(":")
        return int(h), int(m)
    except ValueError:
        return None


def quiet_until(prefs: UserPreference, now_utc: datetime) -> datetime | None:
    """Si ahora es horario de silencio, devuelve (en UTC) cuándo termina; si no, None."""
    start, end = _parse_hhmm(prefs.quiet_start), _parse_hhmm(prefs.quiet_end)
    if not start or not end or start == end:
        return None
    local = now_utc + timedelta(minutes=prefs.utc_offset_minutes)
    t = (local.hour, local.minute)
    in_quiet = (start <= t < end) if start < end else (t >= start or t < end)
    if not in_quiet:
        return None
    end_local = local.replace(hour=end[0], minute=end[1], second=0, microsecond=0)
    if end_local <= local:
        end_local += timedelta(days=1)
    return end_local - timedelta(minutes=prefs.utc_offset_minutes)


def create_notification(
    db: Session, user: User, tracked: TrackedProduct | None, kind: str, title: str, body: str,
    payload: dict | None, dedupe_key: str, now: datetime | None = None,
) -> Notification | None:
    """Crea la notificación salvo que sea duplicada o el usuario haya silenciado ese tipo/categoría."""
    now = now or utcnow()
    prefs = _prefs(db, user.id)
    if db.scalar(select(Notification.id).where(Notification.user_id == user.id, Notification.dedupe_key == dedupe_key)):
        return None
    if kind in (prefs.muted_kinds or []):
        return None
    if tracked is not None and tracked.category and tracked.category in (prefs.muted_categories or []):
        return None

    status, next_at = "pending", None
    q_until = quiet_until(prefs, now)
    sent_today = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.created_at >= now - timedelta(hours=24),
            Notification.delivery_status.in_(["pending", "sent", "failed"]),
        )
    ) or 0
    if q_until is not None:
        status, next_at = "deferred", q_until
    elif sent_today >= prefs.max_notifications_per_day:
        status, next_at = "deferred", now + timedelta(hours=6)

    n = Notification(
        user_id=user.id, tracked_id=tracked.id if tracked else None, kind=kind, title=title[:200], body=body[:600],
        payload=payload, dedupe_key=dedupe_key, delivery_status=status, next_attempt_at=next_at, created_at=now,
    )
    try:
        with db.begin_nested():
            db.add(n)
            db.flush()
    except IntegrityError:
        return None
    return n


def deliver_pending(db: Session, now: datetime | None = None, limit: int = 100) -> int:
    """Entrega las notificaciones pendientes/diferidas cuya hora ya llegó. Devuelve cuántas se enviaron."""
    now = now or utcnow()
    rows = db.scalars(
        select(Notification).where(
            Notification.delivery_status.in_(["pending", "deferred"]),
            (Notification.next_attempt_at.is_(None)) | (Notification.next_attempt_at <= now),
        ).order_by(Notification.created_at).limit(limit)
    ).all()
    sent = 0
    for n in rows:
        prefs = _prefs(db, n.user_id)
        q_until = quiet_until(prefs, now)
        if q_until is not None:
            n.delivery_status, n.next_attempt_at = "deferred", q_until
            continue
        tokens = db.scalars(select(DeviceToken).where(DeviceToken.user_id == n.user_id)).all()
        if not tokens:
            n.delivery_status = "no_devices"
            continue
        if not getattr(_sender, "configured", lambda: True)():
            n.delivery_status = "not_configured"
            n.last_error = "FCM no configurado en el servidor"
            continue
        data = {"notification_id": str(n.id), "kind": n.kind}
        if n.tracked_id:
            data["tracked_id"] = str(n.tracked_id)
        if n.payload and n.payload.get("url"):
            data["url"] = str(n.payload["url"])
        results = []
        for t in tokens:
            r = _sender.send(t.token, n.title, n.body, data)
            results.append(r)
            if r == SendResult.INVALID_TOKEN:
                db.delete(t)
        n.attempts += 1
        if any(r == SendResult.OK for r in results):
            n.delivery_status, n.last_error = "sent", None
            sent += 1
        elif any(r == SendResult.TRANSIENT for r in results) and n.attempts < MAX_DELIVERY_ATTEMPTS:
            n.delivery_status = "pending"
            n.next_attempt_at = now + timedelta(minutes=min(2 ** n.attempts, 60))
            n.last_error = "Fallo temporal de entrega; se reintentará"
        elif all(r == SendResult.INVALID_TOKEN for r in results):
            n.delivery_status, n.last_error = "no_devices", "Los dispositivos registrados ya no son válidos"
        else:
            n.delivery_status, n.last_error = "failed", "No se pudo entregar la notificación"
    db.commit()
    return sent
