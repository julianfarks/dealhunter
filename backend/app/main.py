"""Aplicación FastAPI de DealHunter AI."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .routers import auth, misc, tracked

log = logging.getLogger("dealhunter")


def _secure_headers_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Cache-Control", "no-store")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.secret_key == "cambia-esto-en-produccion":
        log.warning("SECRET_KEY usa el valor por defecto: cámbialo antes de desplegar.")
    stop = threading.Event()
    app.state.stop_worker = stop
    yield
    stop.set()


def create_app() -> FastAPI:
    app = FastAPI(
        title="DealHunter AI API", version="1.0.0", lifespan=lifespan,
        description="Carrito universal con seguimiento automático de precios y alertas.",
    )
    s = get_settings()
    if s.cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
            allow_methods=["*"], allow_headers=["*"],
        )
    _secure_headers_middleware(app)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # no exponer detalles internos ni secretos
        log.exception("Error no controlado en %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "Error interno del servidor"}, status_code=500)

    prefix = "/api/v1"
    app.include_router(auth.router, prefix=prefix)
    app.include_router(tracked.router, prefix=prefix)
    app.include_router(misc.router, prefix=prefix)
    return app


app = create_app()
