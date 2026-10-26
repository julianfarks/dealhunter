from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import User, UserPreference
from ..schemas import LoginIn, RefreshIn, RegisterIn
from ..security import (
    create_access_token, create_refresh_token, get_current_user, hash_password, rate_limiter, user_from_token,
    valid_email, verify_password,
)
from .deps import audit

router = APIRouter(prefix="/auth", tags=["auth"])
_auth_limit = rate_limiter("auth", "rate_limit_auth_per_min")
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def _tokens(user: User) -> dict:
    return {
        "access_token": create_access_token(user), "refresh_token": create_refresh_token(user),
        "token_type": "bearer", "expires_in": get_settings().access_token_minutes * 60,
        "user": {"id": user.id, "email": user.email, "tier": user.tier},
    }


@router.post("/register", status_code=201, dependencies=[Depends(_auth_limit)])
def register(body: RegisterIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if not valid_email(email):
        raise HTTPException(422, "Correo electrónico no válido")
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "Ese correo ya está registrado")
    user = User(email=email, password_hash=hash_password(body.password), tier=get_settings().default_tier)
    db.add(user)
    db.flush()
    db.add(UserPreference(user_id=user.id))
    audit(db, user.id, "register")
    db.commit()
    return _tokens(user)


@router.post("/login", dependencies=[Depends(_auth_limit)])
def login(body: LoginIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        audit(db, user.id if user else None, "login_failed")
        db.commit()
        raise HTTPException(401, "Correo o contraseña incorrectos")
    audit(db, user.id, "login")
    db.commit()
    return _tokens(user)


@router.post("/refresh", dependencies=[Depends(_auth_limit)])
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    user = user_from_token(db, body.refresh_token, "refresh")
    return _tokens(user)


@router.post("/logout-all")
def logout_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.token_version += 1
    audit(db, user.id, "logout_all")
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "tier": user.tier}
