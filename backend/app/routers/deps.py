from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditEvent, TrackedProduct, User, UserPreference
from ..security import get_current_user


def audit(db: Session, user_id: int | None, action: str, detail: str | None = None) -> None:
    db.add(AuditEvent(user_id=user_id, action=action[:64], detail=(detail or "")[:500] or None))


def get_prefs(db: Session, user: User) -> UserPreference:
    p = db.get(UserPreference, user.id)
    if p is None:
        p = UserPreference(user_id=user.id)
        db.add(p)
        db.flush()
    return p


def owned_tracked(tracked_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TrackedProduct:
    """Control de acceso: sólo el dueño ve/modifica su elemento (404 para no revelar existencia)."""
    t = db.scalar(select(TrackedProduct).where(
        TrackedProduct.id == tracked_id, TrackedProduct.user_id == user.id, TrackedProduct.deleted.is_(False)))
    if t is None:
        raise HTTPException(404, "Producto no encontrado")
    return t
