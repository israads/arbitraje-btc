"""PRD-003: preflight/test-order protegido y apagado por defecto."""
from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def dry_run_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from app import main

    settings = Settings(
        control_token="s3cret",
        ingest_autostart=False,
        execution_mode="dry_run",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def testnet_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from app import main

    settings = Settings(
        control_token="s3cret",
        ingest_autostart=False,
        execution_mode="testnet",
        enable_test_orders=True,
        binance_testnet_api_key="dummy-key",
        binance_testnet_api_secret="dummy-secret",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    app = create_app()
    with TestClient(app) as c:
        yield c


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "venue": "binance",
        "side": "buy",
        "symbol": "BTCUSDT",
        "quantity_btc": 0.001,
        "order_type": "market",
        "reference_price": 70_000.0,
    }
    payload.update(overrides)
    return payload


def _check(body: dict[str, object], name: str) -> dict[str, object]:
    checks = body["checks"]
    assert isinstance(checks, list)
    for item in checks:
        assert isinstance(item, dict)
        if item.get("name") == name:
            return item
    raise AssertionError(f"check not found: {name}")


def test_preflight_disabled_by_default(client: TestClient) -> None:
    status = client.get("/api/v1/execution/status")
    assert status.status_code == 200
    assert status.json()["mode"] == "disabled"
    assert status.json()["enabled"] is False

    r = client.post("/api/v1/execution/preflight", json=_payload())
    assert r.status_code == 409


def test_preflight_requires_control_token(dry_run_client: TestClient) -> None:
    r = dry_run_client.post("/api/v1/execution/preflight", json=_payload())
    assert r.status_code == 401

    ok = dry_run_client.post(
        "/api/v1/execution/preflight",
        headers={"X-Control-Token": "s3cret"},
        json=_payload(),
    )
    assert ok.status_code == 200
    assert ok.json()["accepted"] is True


def test_preflight_rejects_unknown_venue(dry_run_client: TestClient) -> None:
    r = dry_run_client.post(
        "/api/v1/execution/preflight",
        headers={"X-Control-Token": "s3cret"},
        json=_payload(venue="kraken"),
    )
    assert r.status_code == 400


def test_preflight_checks_min_notional(dry_run_client: TestClient) -> None:
    r = dry_run_client.post(
        "/api/v1/execution/preflight",
        headers={"X-Control-Token": "s3cret"},
        json=_payload(quantity_btc=0.00002, reference_price=100.0),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is False
    assert _check(body, "min_notional")["passed"] is False


def test_preflight_checks_lot_size(dry_run_client: TestClient) -> None:
    r = dry_run_client.post(
        "/api/v1/execution/preflight",
        headers={"X-Control-Token": "s3cret"},
        json=_payload(quantity_btc=0.000001, reference_price=70_000.0),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is False
    assert _check(body, "lot_size")["passed"] is False


def test_preflight_metrics_are_exposed(dry_run_client: TestClient) -> None:
    ok = dry_run_client.post(
        "/api/v1/execution/preflight",
        headers={"X-Control-Token": "s3cret"},
        json=_payload(),
    )
    rejected = dry_run_client.post(
        "/api/v1/execution/preflight",
        headers={"X-Control-Token": "s3cret"},
        json=_payload(quantity_btc=0.000001, reference_price=70_000.0),
    )
    assert ok.status_code == 200
    assert rejected.status_code == 200

    metrics = dry_run_client.get("/api/v1/metrics").json()
    assert metrics["preflight_results"]["binance"] == {"accepted": 1, "rejected": 1}

    prom = dry_run_client.get("/metrics").text
    assert 'arb_preflight_total{result="accepted",venue="binance"} 1' in prom
    assert 'arb_preflight_total{result="rejected",venue="binance"} 1' in prom


def test_test_order_never_runs_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    settings = Settings(
        control_token="s3cret",
        ingest_autostart=False,
        execution_mode="testnet",
        enable_test_orders=False,
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    app = create_app()
    with TestClient(app) as c:
        r = c.post(
            "/api/v1/execution/test-order",
            headers={"X-Control-Token": "s3cret"},
            json=_payload(),
        )
    assert r.status_code == 409


def test_test_order_response_redacts_secrets(testnet_client: TestClient) -> None:
    health = testnet_client.get("/health").json()
    assert health["mode"] == "testnet"
    assert health["execution_enabled"] is True
    assert health["test_orders_enabled"] is True
    assert health["control_token_required"] is True

    r = testnet_client.post(
        "/api/v1/execution/test-order",
        headers={"X-Control-Token": "s3cret"},
        json=_payload(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True
    assert body["status"] == "accepted_test"
    dumped = json.dumps(body).lower()
    assert "dummy-secret" not in dumped
    assert "dummy-key" not in dumped
    assert "signature" not in dumped
    assert "client_order_id" in body["exchange_response"]

    metrics = testnet_client.get("/api/v1/metrics").json()
    assert metrics["test_order_results"]["binance"] == {"accepted_test": 1}
