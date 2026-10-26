"""Esquemas de entrada (validación estricta). Las respuestas se arman como dicts JSON."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .models import AlertKind

_CUR = re.compile(r"^[A-Za-z]{3}$")


def _cur(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    if not _CUR.match(v):
        raise ValueError("Código de moneda inválido")
    return v.upper()


class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str


class TrackedCreate(BaseModel):
    url: str = Field(max_length=2048)
    target_price: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    target_currency: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    list_name: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=120)
    priority: int = Field(default=0, ge=0, le=2)

    _c = field_validator("target_currency")(_cur)


class TrackedPatch(BaseModel):
    target_price: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    target_currency: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    list_name: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=120)
    priority: int | None = Field(default=None, ge=0, le=2)
    archived: bool | None = None
    purchased: bool | None = None
    purchased_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    paused: bool | None = None

    _c = field_validator("target_currency")(_cur)


class BulkIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    action: Literal["archive", "restore", "delete", "purchased", "pause", "resume", "set_list", "set_priority"]
    list_name: str | None = Field(default=None, max_length=80)
    priority: int | None = Field(default=None, ge=0, le=2)


class AlertIn(BaseModel):
    kind: AlertKind
    threshold: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    threshold_currency: str | None = None
    active: bool = True

    _c = field_validator("threshold_currency")(_cur)


class AlertPatch(BaseModel):
    threshold: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    threshold_currency: str | None = None
    active: bool | None = None

    _c = field_validator("threshold_currency")(_cur)


class PrefsIn(BaseModel):
    currency: str | None = None
    language: Literal["es", "en"] | None = None
    theme: Literal["dark", "light", "system"] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    utc_offset_minutes: int | None = Field(default=None, ge=-840, le=840)
    quiet_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    clear_quiet_hours: bool = False
    max_notifications_per_day: int | None = Field(default=None, ge=1, le=200)
    daily_digest: bool | None = None
    weekly_digest: bool | None = None
    muted_categories: list[str] | None = Field(default=None, max_length=50)
    muted_kinds: list[str] | None = Field(default=None, max_length=20)

    _c = field_validator("currency")(_cur)


class DeviceIn(BaseModel):
    token: str = Field(min_length=20, max_length=400)
    platform: Literal["android"] = "android"


class AiIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    tracked_id: int | None = None


class DeleteAccountIn(BaseModel):
    password: str = Field(max_length=128)
