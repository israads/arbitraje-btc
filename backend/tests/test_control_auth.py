"""Auth mínima de los endpoints de control (kill switch / resume / demo / backtest).

Token vacío (default) ⇒ sin protección (los tests existentes siguen pasando). Token set
⇒ los POST de control exigen el header `X-Control-Token`.
"""
from __future__ import annotations

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.router import require_control_token
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


def _control_protected_routes(app) -> list[tuple[str, str]]:
    """(método, path) de TODA ruta declarada con `require_control_token`, por introspección:
    un endpoint mutable nuevo queda cubierto automáticamente sin tocar este test."""
    out: list[tuple[str, str]] = []
    for route in app.routes:
        if isinstance(route, APIRoute) and any(
            dep.call is require_control_token for dep in route.dependant.dependencies
        ):
            out.extend(
                (method, route.path) for method in sorted(route.methods - {"HEAD", "OPTIONS"})
            )
    return out


def test_every_control_endpoint_requires_token(secured_client):
    """Cobertura exhaustiva: cada endpoint de control rechaza sin token y con token erróneo."""
    routes = _control_protected_routes(secured_client.app)
    # Sanity: kill/resume, demo(+escenarios), backtest, params(+reset), config, retención,
    # preflight y test-order — si esto baja, alguien quitó auth de un endpoint mutable.
    assert len(routes) >= 10
    for method, path in routes:
        url = re.sub(r"\{[^}]+\}", "x", path)
        assert secured_client.request(method, url).status_code == 401, (method, url)
        r = secured_client.request(method, url, headers={"X-Control-Token": "nope"})
        assert r.status_code == 401, (method, url)


def test_prod_refuses_empty_control_token():
    """SG-1: con env=prod y token vacío el arranque FALLA — un deploy público sin auth del
    plano de control no debe poder levantarse por accidente."""
    with pytest.raises(ValidationError):
        Settings(env="prod", control_token="")
    assert Settings(env="prod", control_token="tok").control_token == "tok"
