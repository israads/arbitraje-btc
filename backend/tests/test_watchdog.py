"""STORY-014 — Watchdog de datos stale (C8) + exclusión en el detector (C5)."""
from __future__ import annotations

import asyncio
import logging
import time

from app.config import Settings
from app.engine.detector import SpatialDetector
from app.models.enums import ConnectionStatus
from app.models.market import NormalizedBook, RawOrderBook
from app.risk.watchdog import Watchdog, is_stale
from app.state import AppState
from app.stream.hub import StreamHub


def _nb(ex: str, bid: float, ask: float, ts: float) -> NormalizedBook:
    return NormalizedBook(
        exchange=ex, symbol="BTC/USD", quote_ccy="USD",
        bids=[(bid, 1.0)], asks=[(ask, 1.0)], price_norm_factor=1.0, ts_recv_monotonic=ts,
    )


def _state(settings: Settings | None = None) -> AppState:
    s = settings or Settings()
    return AppState(settings=s, hub=StreamHub(client_queue_maxsize=10))


# ---- Predicado is_stale ----
def test_is_stale_boundary():
    now = 1000.0
    # age == umbral => NO stale (frontera estricta >)
    assert is_stale(now - 0.75, now, 750) is False
    # age > umbral => stale
    assert is_stale(now - 0.751, now, 750) is True
    # recién recibido => fresco
    assert is_stale(now, now, 750) is False


# ---- Detector excluye venues stale ----
def test_detector_excludes_stale_venue():
    d = SpatialDetector(Settings())  # staleness_ms=750
    now = time.monotonic()
    d.on_book(_nb("binance", 100, 101, now - 10.0))  # binance CONGELADO hace 10s
    # kraken fresco; sin la exclusión habría cruce binance(ask101)->kraken(bid102)
    opps = d.on_book(_nb("kraken", 102, 103, now))
    assert opps == []  # binance excluido => 1 solo venue fresco => sin oportunidad


def test_detector_keeps_fresh_venues():
    d = SpatialDetector(Settings())
    t = time.monotonic()
    d.on_book(_nb("binance", 100, 101, t))
    opps = d.on_book(_nb("kraken", 102, 103, t))  # ambos frescos
    assert len(opps) == 1
    assert opps[0].buy_venue == "binance" and opps[0].sell_venue == "kraken"


# ---- Watchdog.evaluate (puro): live / stale / missing ----
def test_evaluate_live_stale_missing():
    state = _state()
    now = time.monotonic()
    state.latest_norm["binance"] = _nb("binance", 100, 101, now - 0.1)   # fresco
    state.latest_norm["kraken"] = _nb("kraken", 100, 101, now - 10.0)    # stale
    # coinbase: sin book (nunca recibido) => stale
    wd = Watchdog(state, state.settings)

    status = wd.evaluate(now)

    assert status["binance"] is ConnectionStatus.live
    assert status["kraken"] is ConnectionStatus.stale
    assert status["coinbase"] is ConnectionStatus.stale


# ---- run(): publica feed_status y loguea transición live->stale ----
def test_run_publishes_status_and_logs_transition(caplog):
    # Margen amplio (50ms) entre el primer tick (~5ms) y el umbral para evitar
    # flakiness bajo carga: el primer tick es live con holgura, luego stale.
    settings = Settings(watchdog_interval_ms=5, staleness_ms=50)
    state = _state(settings)
    t = time.monotonic()
    for ex in ("binance", "kraken", "coinbase"):
        state.latest_norm[ex] = _nb(ex, 100, 101, t)

    wd = Watchdog(state, settings)

    async def _run():
        task = asyncio.create_task(wd.run())
        await asyncio.sleep(0.02)   # primer tick: live (age < 50ms)
        await asyncio.sleep(0.10)   # age supera 50ms => stale (transición)
        wd.stop()
        await task

    with caplog.at_level(logging.WARNING, logger="app.risk.watchdog"):
        asyncio.run(_run())

    assert state.feed_status["binance"] is ConnectionStatus.stale
    assert any("-> stale" in r.message for r in caplog.records)


# ---- Config: rechaza umbrales no positivos ----
def test_config_rejects_nonpositive():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(staleness_ms=0)
    with pytest.raises(ValidationError):
        Settings(watchdog_interval_ms=0)


# ---- /health expone status por feed ----
def test_health_endpoint_exposes_status(client):
    ctx = client.app.state.ctx
    t = time.monotonic()
    ctx.latest_books["binance"] = RawOrderBook(
        exchange="binance", symbol="BTC/USDT", quote_ccy="USDT",
        bids=[(100.0, 1.0)], asks=[(101.0, 1.0)], ts_recv_monotonic=t,
    )
    ctx.latest_norm["binance"] = _nb("binance", 100.0, 101.0, t)  # operable
    feeds = client.get("/health").json()["feeds"]
    assert feeds["binance"]["status"] == "live"
    # kraken/coinbase sin book => stale, y age_ms presente como None (shape estable)
    assert feeds["kraken"]["status"] == "stale"
    assert feeds["kraken"]["age_ms"] is None
    assert feeds["coinbase"]["status"] == "stale"


def test_health_status_stale_when_raw_fresh_but_no_normalized(client):
    """HIGH-1/M4: raw book fresco pero SIN normalizado (peg no disponible) → el
    venue no es operable → /health debe decir `stale`, coherente con el detector
    (que solo opera sobre books normalizados). Antes /health decía `live`."""
    ctx = client.app.state.ctx
    ctx.latest_books["binance"] = RawOrderBook(
        exchange="binance", symbol="BTC/USDT", quote_ccy="USDT",
        bids=[(100.0, 1.0)], asks=[(101.0, 1.0)], ts_recv_monotonic=time.monotonic(),
    )
    # sin ctx.latest_norm["binance"]
    feeds = client.get("/health").json()["feeds"]
    assert feeds["binance"]["book"] is True       # el raw existe (informativo)
    assert feeds["binance"]["status"] == "stale"  # pero no operable
