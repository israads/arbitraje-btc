"""Auth mínima de los endpoints de control (kill switch / resume / demo / backtest).

Token vacío (default) ⇒ sin protección (los tests existentes siguen pasando). Token set
⇒ los POST de control exigen el header `X-Control-Token`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def secured_client(monkeypatch):
    """App con `control_token` seteado, sin ingesta real (autostart off)."""
    from app import main

    settings = Settings(control_token="s3cret", ingest_autostart=False)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_control_open_when_token_empty(client):
    """Default (token vacío): POST de control sin header → 200 (retrocompatible)."""
    r = client.post("/api/v1/control/kill-switch")
    assert r.status_code == 200
    assert "halted" in r.json()


def test_control_rejects_without_token(secured_client):
    r = secured_client.post("/api/v1/control/kill-switch")
    assert r.status_code == 401


def test_control_rejects_wrong_token(secured_client):
    r = secured_client.post(
        "/api/v1/control/resume", headers={"X-Control-Token": "nope"}
    )
    assert r.status_code == 401


def test_control_accepts_correct_token(secured_client):
    r = secured_client.post(
        "/api/v1/control/kill-switch", headers={"X-Control-Token": "s3cret"}
    )
    assert r.status_code == 200


def test_reads_remain_open_when_secured(secured_client):
    """Los GET (lectura) no requieren token aunque el control esté protegido."""
    assert secured_client.get("/api/v1/control/status").status_code == 200
    assert secured_client.get("/api/v1/quotes").status_code == 200
