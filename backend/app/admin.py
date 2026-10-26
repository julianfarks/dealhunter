"""Utilidades de administración.

  python -m app.admin set-tier correo@ejemplo.com premium
  python -m app.admin check https://articulo.mercadolibre.com.co/MCO-123...   # consulta real con tus credenciales
  python -m app.admin init-db                                                  # sólo desarrollo; en producción usa Alembic
"""
from __future__ import annotations

import sys

from sqlalchemy import select

from . import db as db_module
from .connectors import ConnectorError, ListingRef, ProductGone, SourceUnavailable, get_connector
from .models import User
from .services.listings import parse_or_resolve
from .urlutil import InvalidUrl


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "init-db":
        from .db import Base, engine

        Base.metadata.create_all(engine)
        print("Tablas creadas.")
        return 0
    if cmd == "set-tier" and len(argv) == 4:
        db = db_module.SessionLocal()
        try:
            user = db.scalar(select(User).where(User.email == argv[2].strip().lower()))
            if user is None or argv[3] not in ("free", "premium"):
                print("Usuario inexistente o plan inválido (free|premium).")
                return 1
            user.tier = argv[3]
            db.commit()
            print(f"{user.email}: plan {user.tier}")
            return 0
        finally:
            db.close()
    if cmd == "check" and len(argv) == 3:
        try:
            parsed = parse_or_resolve(argv[2])
        except (InvalidUrl, Exception) as e:  # noqa: BLE001
            print("URL no válida:", e)
            return 1
        conn = get_connector(parsed.store_key)
        print(f"Tienda: {parsed.store_key} · id: {parsed.external_id} · variante: {parsed.variant_key or '-'}")
        print(f"Conector: {conn.name} · estado: {conn.status()}")
        try:
            info = conn.fetch(ListingRef(parsed.external_id, parsed.variant_key, parsed.canonical_url))
        except SourceUnavailable as e:
            print("Sin fuente disponible:", e)
            return 3
        except ProductGone as e:
            print("Producto inexistente:", e)
            return 4
        except ConnectorError as e:
            print("Error temporal:", e)
            return 5
        print(f"Título: {info.title}\nPrecio: {info.price} {info.currency}\nDisponible: {info.available}\n"
              f"Envío: {info.shipping_cost}\nFuente: {info.source}\nPromos: {[p.description for p in info.promotions]}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
