"""Esquema inicial

Crea todas las tablas a partir de los modelos de la versión 1.0. Las migraciones posteriores deben ser
incrementales (`alembic revision --autogenerate -m "..."` contra una base ya migrada).

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app import models  # noqa: F401
    from app.db import Base

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app import models  # noqa: F401
    from app.db import Base

    Base.metadata.drop_all(bind=op.get_bind())
