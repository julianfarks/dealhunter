"""Autenticación, hashing de contraseñas, tokens y límite de peticiones."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

_bearer = HTTPBearer(auto_error=False)
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or "")) and len(email) <= 254


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P, base64.b64encode(salt).decode(), base64.b64encode(dk).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt_b64, dk_b64 = stored.split("$")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(dk_b64)
        dk = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _make_token(user: User, kind: str, ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "typ": kind, "ver": user.token_version, "iat": now, "exp": now + ttl}
    return jwt.encode(payload, get_settings().secret_key, algorithm="HS256")


def create_access_token(user: User) -> str:
    return _make_token(user, "access", timedelta(minutes=get_settings().access_token_minutes))


def create_refresh_token(user: User) -> str:
    return _make_token(user, "refresh", timedelta(days=get_settings().refresh_token_days))


def decode_token(token: str, expected: str) -> dict:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido o vencido") from e
    if data.get("typ") != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Tipo de token incorrecto")
    return data


def user_from_token(db: Session, token: str, expected: str = "access") -> User:
    data = decode_token(token, expected)
    user = db.get(User, int(data["sub"]))
    if user is None or user.token_version != data.get("ver"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión cerrada o cuenta inexistente")
    return user


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta el token de acceso")
    return user_from_token(db, creds.credentials, "access")


# ---- Límite de peticiones en memoria (ventana deslizante por clave) ----
_hits: dict[str, deque] = defaultdict(deque)


def reset_rate_limits() -> None:
    _hits.clear()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limiter(bucket: str, limit_attr: str, window_seconds: int = 60):
    def dep(request: Request) -> None:
        limit = getattr(get_settings(), limit_attr)
        key = f"{bucket}:{_client_ip(request)}"
        now = time.monotonic()
        q = _hits[key]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiadas solicitudes, intenta más tarde")
        q.append(now)

    return dep
