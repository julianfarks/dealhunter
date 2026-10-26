import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def test_alembic_upgrade_head_crea_el_esquema():
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "DATABASE_URL": f"sqlite:///{d}/m.db"}
        r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        tables = {row[0] for row in sqlite3.connect(f"{d}/m.db").execute("select name from sqlite_master where type='table'")}
        assert {"users", "tracked_products", "price_observations", "price_alerts", "notifications",
                "price_check_jobs", "alembic_version"} <= tables
        r = subprocess.run([sys.executable, "-m", "alembic", "current"], cwd=BACKEND, env=env, capture_output=True, text=True)
        assert "0001" in (r.stdout + r.stderr)
