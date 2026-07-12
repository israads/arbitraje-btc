"""PRD-009 — camino API de la configuración base (`PUT /api/v1/config/sim`).

Cubre los tests 4a, 5 y 6 del gate de salida: bloqueo 409 de `enabled`
(`venue_restart_required`), 422 de venue desconocido (y su precedencia sobre el 409),
atomicidad ante fallo de persistencia, reseed condicional (solo balances iniciales) e
invariantes del ledger antes/después de un cambio hot aceptado.

`get_settings()` está cacheado y el endpoint muta la instancia canónica: cada test limpia
esa cache antes y después para no contaminar al resto de la suite.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.api.v1.router import _PROJECTION_CACHE
from app.config import get_settings
from app.main import create_app


@pytest.fixture
def client():
    """TestClient con lifespan real (DB en memoria, autostart off; token vacío en dev) y
    `Settings` FRESCOS por test: limpia la cache de `get_settings` antes y después."""
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    get_settings.cache_clear()


def _fingerprint(pf):
    return (
        {
            v: (vb.btc, vb.quote, vb.open_btc, vb.open_cost_basis_usd)
            for v, vb in pf.venues.items()
        },
        pf.realized_pnl,
    )


# --- Test 4a del gate: cambio de `enabled` → 409 sin cambios observables ----------------

def test_put_enabled_change_returns_409_and_changes_nothing(client, monkeypatch):
    """Deshabilitar un venue en caliente devuelve 409 `venue_restart_required` y NO
    persiste, NO muta Settings, NO re-siembra y NO limpia caches."""
    import app.store.config_store as cs

    ctx = client.app.state.ctx
    assert ctx.settings.exchanges["kraken"].enabled is True
    settings_before = ctx.settings.model_dump()
    fp_before = _fingerprint(ctx.portfolio)
    saves: list[dict] = []
    monkeypatch.setattr(cs, "save_app_config", lambda *a, **k: saves.append({}))
    sentinel = ("sentinela", (time.time(), "vivo"))
    _PROJECTION_CACHE[sentinel[0]] = sentinel[1]
    try:
        r = client.put(
            "/api/v1/config/sim", json={"exchanges": {"kraken": {"enabled": False}}}
        )
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert detail["code"] == "venue_restart_required"
        assert detail["venues"] == ["kraken"]
        assert "reiniciar" in detail["message"]
        # Cero cambios observables: runtime, portfolio, cache y persistencia intactos.
        assert ctx.settings.model_dump() == settings_before
        assert ctx.settings.exchanges["kraken"].enabled is True  # sigue operativo
        assert _fingerprint(ctx.portfolio) == fp_before
        assert _PROJECTION_CACHE.get(sentinel[0]) == sentinel[1]  # cache no limpiada
        assert saves == []                                        # no se persistió nada
    finally:
        _PROJECTION_CACHE.pop(sentinel[0], None)


def test_put_multiple_enabled_changes_single_409_sorted(client):
    """Varios cambios de `enabled` → UN único 409 con la lista ordenada alfabéticamente."""
    ctx = client.app.state.ctx
    settings_before = ctx.settings.model_dump()
    r = client.put(
        "/api/v1/config/sim",
        json={
            "exchanges": {
                "kraken": {"enabled": False},
                "binance": {"enabled": False},
                "coinbase": {"enabled": True},  # sin cambio (ya True): no cuenta
            }
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"]["venues"] == ["binance", "kraken"]
    assert ctx.settings.model_dump() == settings_before  # el rechazo no mutó NADA antes


def test_put_enabled_unchanged_is_valid_noop(client):
    """Repetir los valores `enabled` actuales es válido (no-op, compat con la UI previa)."""
    enabled_now = client.app.state.ctx.settings.exchanges["kraken"].enabled
    r = client.put(
        "/api/v1/config/sim", json={"exchanges": {"kraken": {"enabled": enabled_now}}}
    )
    assert r.status_code == 200
    assert r.json()["applied"] == []


# --- 422: venue desconocido (y precedencia sobre el 409) --------------------------------

def test_put_unknown_venue_422_applies_nothing(client, monkeypatch):
    import app.store.config_store as cs

    ctx = client.app.state.ctx
    settings_before = ctx.settings.model_dump()
    saves: list[dict] = []
    monkeypatch.setattr(cs, "save_app_config", lambda *a, **k: saves.append({}))
    r = client.put(
        "/api/v1/config/sim",
        json={
            "exchanges": {"nope": {"fee_taker": 0.0001}, "kraken": {"fee_taker": 0.0001}}
        },
    )
    assert r.status_code == 422
    # Los campos válidos del payload TAMPOCO se aplican ni se persisten (sin app. parcial).
    assert ctx.settings.model_dump() == settings_before
    assert saves == []


def test_put_unknown_venue_plus_enabled_change_is_422_not_409(client):
    """El 422 de venue desconocido precede al 409 de `enabled` (orden RF-007)."""
    r = client.put(
        "/api/v1/config/sim",
        json={"exchanges": {"nope": {"enabled": True}, "kraken": {"enabled": False}}},
    )
    assert r.status_code == 422


# --- Test 5 del gate: fallo de persistencia → cero cambios ------------------------------

def test_put_persistence_failure_leaves_state_intact(client, monkeypatch):
    """Si `save_app_config` falla, la respuesta es no-2xx y Settings, portfolio, cache y
    fila previa quedan exactamente como estaban (la mutación runtime va DESPUÉS del commit)."""
    import app.store.config_store as cs

    ctx = client.app.state.ctx
    settings_before = ctx.settings.model_dump()
    ctx.portfolio.realized_pnl = 77.0  # marca de sesión: debe sobrevivir al fallo
    fp_before = _fingerprint(ctx.portfolio)
    portfolio_before = ctx.portfolio

    async def boom(*a, **k):
        raise RuntimeError("db caída")

    monkeypatch.setattr(cs, "save_app_config", boom)
    sentinel = ("sentinela", (time.time(), "vivo"))
    _PROJECTION_CACHE[sentinel[0]] = sentinel[1]
    try:
        r = client.put(
            "/api/v1/config/sim",
            json={"exchanges": {"kraken": {"fee_taker": 0.0001, "initial_btc": 9.0}}},
        )
        assert r.status_code >= 500
        assert ctx.settings.model_dump() == settings_before
        assert ctx.portfolio is portfolio_before          # no se sustituyó el portfolio
        assert _fingerprint(ctx.portfolio) == fp_before   # ni se re-sembró
        assert _PROJECTION_CACHE.get(sentinel[0]) == sentinel[1]
    finally:
        _PROJECTION_CACHE.pop(sentinel[0], None)


# --- RF-006: ediciones hot — reseed SOLO si cambian los balances iniciales ---------------

def test_put_fee_change_applies_hot_without_reseed(client):
    """Cambiar solo fees/umbrales actualiza Settings y conserva el P&L de la sesión."""
    ctx = client.app.state.ctx
    ctx.portfolio.realized_pnl = 42.0
    portfolio_before = ctx.portfolio
    r = client.put(
        "/api/v1/config/sim",
        json={"exchanges": {"kraken": {"fee_taker": 0.0011}}, "min_net_profit_usd": 3.5},
    )
    assert r.status_code == 200
    applied = r.json()["applied"]
    assert "kraken.fee_taker=0.0011" in applied
    assert "min_net_profit_usd=3.5" in applied
    assert ctx.settings.exchanges["kraken"].fee_taker == 0.0011
    assert ctx.settings.min_net_profit_usd == 3.5
    assert ctx.portfolio is portfolio_before              # ni se sustituyó la instancia
    assert ctx.portfolio.realized_pnl == 42.0             # P&L intacto: sin reseed


def test_put_same_values_is_noop_and_preserves_pnl(client):
    """Reenviar el snapshot completo sin cambios reales (presencia ≠ cambio) no aplica
    nada ni re-siembra."""
    ctx = client.app.state.ctx
    ctx.portfolio.realized_pnl = 13.0
    kraken = ctx.settings.exchanges["kraken"]
    r = client.put(
        "/api/v1/config/sim",
        json={
            "exchanges": {
                "kraken": {
                    "fee_taker": kraken.fee_taker,
                    "initial_btc": kraken.initial_btc,
                    "initial_quote": kraken.initial_quote,
                }
            }
        },
    )
    assert r.status_code == 200
    assert r.json()["applied"] == []
    assert ctx.portfolio.realized_pnl == 13.0


def test_put_initial_balance_change_reseeds_once(client):
    """Cambiar `initial_btc`/`initial_quote` re-siembra el portfolio (P&L y curva a cero)
    con los balances nuevos, enlazado a la instancia canónica de Settings."""
    ctx = client.app.state.ctx
    ctx.portfolio.realized_pnl = 42.0
    r = client.put(
        "/api/v1/config/sim",
        json={"exchanges": {"kraken": {"initial_btc": 7.0}}},
    )
    assert r.status_code == 200
    assert "kraken.initial_btc=7.0" in r.json()["applied"]
    assert ctx.settings.exchanges["kraken"].initial_btc == 7.0  # runtime Settings al día
    assert ctx.portfolio.realized_pnl == 0.0              # nuevo punto de partida
    assert ctx.portfolio.venues["kraken"].btc == 7.0
    assert len(ctx.portfolio.equity_series) == 0
    assert ctx.portfolio.settings is ctx.settings         # instancia canónica compartida


# --- Test 6 del gate: invariantes antes/después de un cambio hot aceptado ----------------

def test_ledger_invariants_hold_across_accepted_hot_change(client):
    """Conservación y doble entrada (GET /validation) pasan antes Y después de un cambio
    de config hot aceptado."""
    r0 = client.get("/api/v1/validation")
    assert r0.status_code == 200
    assert r0.json()["all_passed"] is True
    r = client.put(
        "/api/v1/config/sim",
        json={"exchanges": {"kraken": {"fee_taker": 0.0022}}},
    )
    assert r.status_code == 200
    r1 = client.get("/api/v1/validation")
    assert r1.status_code == 200
    assert r1.json()["all_passed"] is True
