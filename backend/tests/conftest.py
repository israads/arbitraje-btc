from __future__ import annotations

import os

# Desactiva la ingesta real (ccxt.pro → red) ANTES de importar la app: así el
# lifespan no abre conexiones a exchanges durante los tests. Debe ir antes del
# import de `app.main` (que cachea settings al construir `app`).
os.environ.setdefault("ARB_INGEST_AUTOSTART", "false")
# C12 (STORY-011): usa DB en memoria para tests; evita crear/ensuciar arbitraje.db.
os.environ.setdefault("ARB_DB_URL", "sqlite+aiosqlite:///:memory:")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture
def client():
    """TestClient como context manager ⇒ ejecuta el lifespan (startup/shutdown)."""
    app = create_app()
    with TestClient(app) as c:
        yield c
