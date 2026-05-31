"""STORY-018 — Circuit breakers + kill switch (C8, FR-012).

Cubre: el manager puro (evaluate de los 5 breakers + enganche/auto + kill/resume), el
tracker de volatilidad, el monitor (medición desde el estado vivo), el GATE del motor
(viable→discarded(breaker_active) con breaker activo) y los endpoints de control + /health.
"""
from __future__ import annotations

import asyncio
import logging
import time

import pytest

from app.config import ExchangeConfig, Settings
from app.models.enums import BreakerType, ConnectionStatus, OpportunityStatus
from app.models.market import NormalizedBook
from app.risk.breakers import BreakerManager, BreakerMonitor, VolatilityTracker
from app.state import AppState
from app.stream.hub import StreamHub


def _nb(ex: str, bid: float, ask: float, ts: float = 0.0) -> NormalizedBook:
    return NormalizedBook(
        exchange=ex, symbol="BTC/USD", quote_ccy="USD",
        bids=[(bid, 5.0)], asks=[(ask, 5.0)], price_norm_factor=1.0, ts_recv_monotonic=ts,
    )


def _mgr(**over) -> BreakerManager:
    return BreakerManager(Settings(**over))


# ----------------- BreakerManager.evaluate (puro) -----------------
def test_all_clear_not_tripped():
    m = _mgr()
    m.evaluate(now=1.0, equity=100.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=10.0)
    assert m.tripped is False
    assert m.active_types() == []


def test_volatility_breaker_auto_trips_and_clears():
    m = _mgr(volatility_breaker_bps=200.0)
    m.evaluate(now=1.0, equity=100.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=250.0)
    assert m.tripped is True
    assert "volatility" in m.active_types()
    # cede la volatilidad → se limpia solo (auto, sin resume)
    m.evaluate(now=2.0, equity=100.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=50.0)
    assert "volatility" not in m.active_types()


def test_volatility_boundary_strict():
    m = _mgr(volatility_breaker_bps=200.0)
    m.evaluate(now=1.0, equity=100.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=200.0)  # == umbral: NO dispara (>)
    assert "volatility" not in m.active_types()


def test_inventory_skew_breaker_auto():
    m = _mgr()
    m.evaluate(now=1.0, equity=100.0, skew_breached=True, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    assert "inventory_skew" in m.active_types()
    m.evaluate(now=2.0, equity=100.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    assert "inventory_skew" not in m.active_types()


def test_stale_data_breaker_when_no_live_venue():
    m = _mgr()
    m.evaluate(now=1.0, equity=100.0, skew_breached=False, live_venues=0,
               enabled_venues=3, volatility_bps=0.0)
    assert "stale_data" in m.active_types()
    # con al menos un venue vivo, no dispara
    m.evaluate(now=2.0, equity=100.0, skew_breached=False, live_venues=1,
               enabled_venues=3, volatility_bps=0.0)
    assert "stale_data" not in m.active_types()


def test_stale_data_not_tripped_when_no_venues_enabled():
    m = _mgr()
    m.evaluate(now=1.0, equity=100.0, skew_breached=False, live_venues=0,
               enabled_venues=0, volatility_bps=None)
    assert "stale_data" not in m.active_types()


def test_drawdown_breaker_latches_until_resume():
    m = _mgr(max_drawdown_usd=5_000.0)
    # pico de equity = 100k
    m.evaluate(now=1.0, equity=100_000.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    assert "max_drawdown" not in m.active_types()
    # cae 6k > 5k → dispara
    m.evaluate(now=2.0, equity=94_000.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    assert "max_drawdown" in m.active_types()
    # equity se recupera, pero el breaker ENGANCHA (no se limpia solo)
    m.evaluate(now=3.0, equity=99_000.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    assert "max_drawdown" in m.active_types()
    # resume re-ancla el pico al valor actual y limpia el enganche
    m.resume(equity=99_000.0)
    assert "max_drawdown" not in m.active_types()
    assert m.tripped is False
    # tras resume, sólo re-dispara si cae > límite desde el NUEVO pico (99k)
    m.evaluate(now=4.0, equity=95_000.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    assert "max_drawdown" not in m.active_types()  # cayó 4k < 5k
    m.evaluate(now=5.0, equity=93_000.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    assert "max_drawdown" in m.active_types()  # cayó 6k > 5k


def test_drawdown_boundary_strict():
    m = _mgr(max_drawdown_usd=5_000.0)
    m.evaluate(now=1.0, equity=100_000.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    m.evaluate(now=2.0, equity=95_000.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)  # cae exactamente 5k: NO (>)
    assert "max_drawdown" not in m.active_types()


def test_kill_switch_latches_and_resume_clears():
    m = _mgr()
    m.trip_kill_switch()
    assert m.tripped is True
    assert "kill_switch" in m.active_types()
    # un evaluate posterior NO lo limpia (es manual/enganchado)
    m.evaluate(now=1.0, equity=100.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    assert "kill_switch" in m.active_types()
    m.resume()
    assert "kill_switch" not in m.active_types()
    assert m.tripped is False


def test_resume_does_not_mask_persistent_auto_breaker():
    """resume() limpia kill/drawdown pero un breaker AUTO con condición viva sigue activo."""
    m = _mgr()
    m.trip_kill_switch()
    m.evaluate(now=1.0, equity=100.0, skew_breached=True, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)  # skew sigue roto
    m.resume()
    assert "kill_switch" not in m.active_types()
    # el monitor recomputará; al re-evaluar, skew sigue activo
    m.evaluate(now=2.0, equity=100.0, skew_breached=True, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    assert "inventory_skew" in m.active_types()
    assert m.tripped is True


def test_since_preserved_while_active():
    m = _mgr()
    m.evaluate(now=10.0, equity=100.0, skew_breached=True, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    st = {s.type: s for s in m.states()}[BreakerType.inventory_skew]
    assert st.since == 10.0
    m.evaluate(now=20.0, equity=100.0, skew_breached=True, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    st2 = {s.type: s for s in m.states()}[BreakerType.inventory_skew]
    assert st2.since == 10.0  # mismo episodio: no se reinicia


def test_status_shape():
    m = _mgr()
    m.trip_kill_switch()
    s = m.status()
    assert s["halted"] is True
    assert "kill_switch" in s["active"]
    assert len(s["breakers"]) == len(list(BreakerType))
    assert all({"type", "active", "reason", "since"} <= set(b) for b in s["breakers"])


def test_evaluate_handles_none_equity_and_vol():
    m = _mgr()
    m.evaluate(now=1.0, equity=None, skew_breached=False, live_venues=2,
               enabled_venues=3, volatility_bps=None)  # sin portfolio ni vol aún
    assert m.tripped is False


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_evaluate_ignores_nonfinite_equity(bad):
    m = _mgr(max_drawdown_usd=5_000.0)
    m.evaluate(now=1.0, equity=100_000.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    m.evaluate(now=2.0, equity=bad, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)  # no finito no envenena el pico
    assert "max_drawdown" not in m.active_types()


def test_since_resets_after_retrip():
    """Tras limpiarse y re-dispararse, `since` toma el nuevo `now` (episodio nuevo)."""
    m = _mgr()
    m.evaluate(now=10.0, equity=100.0, skew_breached=True, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    m.evaluate(now=11.0, equity=100.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)  # se limpia
    m.evaluate(now=20.0, equity=100.0, skew_breached=True, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)  # re-dispara
    st = {s.type: s for s in m.states()}[BreakerType.inventory_skew]
    assert st.since == 20.0


def test_resume_without_equity_keeps_peak():
    """resume() sin equity limpia el latch pero NO re-ancla el pico (queda el previo)."""
    m = _mgr(max_drawdown_usd=5_000.0)
    m.evaluate(now=1.0, equity=100_000.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)  # pico 100k
    m.evaluate(now=2.0, equity=90_000.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)  # drawdown 10k → latcha
    assert "max_drawdown" in m.active_types()
    m.resume()  # sin equity: limpia latch, conserva pico 100k
    assert "max_drawdown" not in m.active_types()
    # cae a 94k: contra el pico 100k son 6k > 5k → re-dispara (pico NO re-anclado)
    m.evaluate(now=3.0, equity=94_000.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    assert "max_drawdown" in m.active_types()


def test_resume_with_nan_equity_does_not_poison_peak():
    m = _mgr(max_drawdown_usd=5_000.0)
    m.evaluate(now=1.0, equity=100_000.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    m.resume(equity=float("nan"))  # NaN no debe envenenar el pico
    m.evaluate(now=2.0, equity=99_000.0, skew_breached=False, live_venues=3,
               enabled_venues=3, volatility_bps=0.0)
    assert "max_drawdown" not in m.active_types()  # pico sigue siendo 100k finito


# ----------------- VolatilityTracker -----------------
def test_volatility_tracker_range_bps():
    vt = VolatilityTracker(window_ms=5_000)
    vt.update("binance", 100.0, now=0.0)
    vt.update("binance", 102.0, now=1.0)   # +2% = 200 bps
    assert vt.max_bps(1.0) == pytest.approx(200.0)


def test_volatility_tracker_window_drops_old():
    vt = VolatilityTracker(window_ms=1_000)  # 1s
    vt.update("binance", 100.0, now=0.0)
    vt.update("binance", 200.0, now=2.0)     # el de t=0 ya cayó de la ventana
    # sólo un punto dentro de [1.0, 2.0] → no opina
    assert vt.max_bps(2.0) is None


def test_volatility_tracker_ignores_corrupt():
    vt = VolatilityTracker(window_ms=5_000)
    vt.update("binance", float("nan"), now=0.0)
    vt.update("binance", -5.0, now=1.0)
    vt.update("binance", 0.0, now=2.0)
    assert vt.max_bps(2.0) is None


def test_volatility_tracker_flat_is_zero_not_none():
    """≥2 puntos con mids idénticos → rango 0.0 (no None): hay datos, no hay volatilidad."""
    vt = VolatilityTracker(window_ms=5_000)
    vt.update("binance", 100.0, 0.0)
    vt.update("binance", 100.0, 1.0)
    assert vt.max_bps(1.0) == 0.0


def test_volatility_tracker_prunes_empty_keys():
    vt = VolatilityTracker(window_ms=1_000)
    vt.update("ghost", 100.0, 0.0)
    vt.max_bps(now=5.0)  # 5s después: el punto cae de la ventana y la clave se poda
    assert "ghost" not in vt._hist


def test_volatility_tracker_max_across_venues():
    vt = VolatilityTracker(window_ms=5_000)
    vt.update("a", 100.0, 0.0)
    vt.update("a", 101.0, 1.0)    # 100 bps
    vt.update("b", 100.0, 0.0)
    vt.update("b", 103.0, 1.0)    # 300 bps
    assert vt.max_bps(1.0) == pytest.approx(300.0)


# ----------------- BreakerMonitor.measure -----------------
def _state(**over) -> AppState:
    return AppState(settings=Settings(**over), hub=StreamHub(client_queue_maxsize=10))


# Set fijo de 3 venues para tests cuya lógica (equity completa, drawdown) NO debe
# acoplarse al nº de venues de producción (el default ahora es multi-venue).
_THREE_VENUES = {
    "binance": ExchangeConfig(id="binance", symbol="BTC/USDT", quote_ccy="USDT",
                              fee_taker=0.0010, withdrawal_btc=0.0002, ob_limit=20),
    "kraken": ExchangeConfig(id="kraken", symbol="BTC/USD", quote_ccy="USD",
                             fee_taker=0.0040, withdrawal_btc=0.00005, ob_limit=25),
    "coinbase": ExchangeConfig(id="coinbase", symbol="BTC/USD", quote_ccy="USD",
                               fee_taker=0.0060, withdrawal_btc=0.0001, ob_limit=50),
}


def _state3(**over) -> AppState:
    """AppState fijado a 3 venues (binance/kraken/coinbase)."""
    return AppState(settings=Settings(exchanges=_THREE_VENUES, **over),
                    hub=StreamHub(client_queue_maxsize=10))


def test_monitor_measure_from_live_state():
    st = _state3()
    st.breakers = BreakerManager(st.settings)
    st.latest_norm["binance"] = _nb("binance", 100.0, 101.0)
    st.latest_norm["kraken"] = _nb("kraken", 100.5, 101.5)
    st.feed_status = {
        "binance": ConnectionStatus.live,
        "kraken": ConnectionStatus.stale,
        "coinbase": ConnectionStatus.stale,
    }
    mon = BreakerMonitor(st, st.settings)
    meas = mon.measure(now=time.monotonic())
    assert meas["live_venues"] == 1
    assert meas["enabled_venues"] == 3
    assert meas["equity"] is None or meas["equity"] == 0.0  # sin portfolio sembrado


def test_monitor_skips_drawdown_when_equity_incomplete():
    """FIX HIGH (revisión adversarial): con un venue que tiene BTC pero SIN libro vivo,
    equity_total lo marca a 0 → equity cae ~miles USD por dato faltante, no por pérdida. El
    monitor pasa equity=None (no evalúa drawdown) hasta que todos los venues con BTC sean
    marcables → NO latcha un HALT espurio."""
    from app.sim import Portfolio
    st = _state3(max_drawdown_usd=5_000.0)
    st.breakers = BreakerManager(st.settings)
    st.portfolio = Portfolio(st.settings)  # 3 venues sembrados con 2 BTC + 100k c/u
    # Sólo binance tiene libro: kraken/coinbase con BTC pero sin mark → equity incompleta.
    st.latest_norm["binance"] = _nb("binance", 100_000.0, 100_010.0)
    mon = BreakerMonitor(st, st.settings)
    meas = mon.measure(now=1.0)
    assert meas["equity"] is None  # equity incompleta → no se mide drawdown
    st.breakers.evaluate(**meas)
    assert "max_drawdown" not in st.breakers.active_types()  # sin halt espurio
    # Con TODOS los libros vivos, la equity se vuelve completa y medible.
    st.latest_norm["kraken"] = _nb("kraken", 100_000.0, 100_010.0)
    st.latest_norm["coinbase"] = _nb("coinbase", 100_000.0, 100_010.0)
    meas2 = mon.measure(now=2.0)
    assert meas2["equity"] is not None and meas2["equity"] > 0.0


def test_equity_complete_ignores_venues_without_btc():
    """Un venue sin BTC no exige libro para considerar la equity completa."""
    from app.sim import Portfolio
    st = _state3()
    st.portfolio = Portfolio(st.settings)
    # Vacía el BTC de kraken/coinbase: sólo binance mantiene BTC.
    st.portfolio.venues["kraken"].btc = 0.0
    st.portfolio.venues["coinbase"].btc = 0.0
    st.latest_norm["binance"] = _nb("binance", 100_000.0, 100_010.0)
    mon = BreakerMonitor(st, st.settings)
    meas = mon.measure(now=1.0)
    assert meas["equity"] is not None  # completa: el único venue con BTC tiene mark


def test_mid_handles_missing_sides():
    bb = NormalizedBook(exchange="x", symbol="BTC/USD", quote_ccy="USD",
                        bids=[(100.0, 1.0)], asks=[], price_norm_factor=1.0, ts_recv_monotonic=0.0)
    assert BreakerMonitor._mid(bb) == 100.0   # sólo bid
    aa = NormalizedBook(exchange="x", symbol="BTC/USD", quote_ccy="USD",
                        bids=[], asks=[(101.0, 1.0)], price_norm_factor=1.0, ts_recv_monotonic=0.0)
    assert BreakerMonitor._mid(aa) == 101.0   # sólo ask
    empty = NormalizedBook(exchange="x", symbol="BTC/USD", quote_ccy="USD",
                           bids=[], asks=[], price_norm_factor=1.0, ts_recv_monotonic=0.0)
    assert BreakerMonitor._mid(empty) is None


def test_monitor_measure_with_portfolio_equity():
    from app.sim import Portfolio
    st = _state3()
    st.breakers = BreakerManager(st.settings)
    st.portfolio = Portfolio(st.settings)
    st.latest_norm["binance"] = _nb("binance", 100.0, 101.0)
    st.latest_norm["kraken"] = _nb("kraken", 100.0, 101.0)
    st.latest_norm["coinbase"] = _nb("coinbase", 100.0, 101.0)
    mon = BreakerMonitor(st, st.settings)
    meas = mon.measure(now=time.monotonic())
    assert meas["equity"] is not None and meas["equity"] > 0.0


def test_monitor_run_trips_and_emits_on_change(caplog):
    """El monitor recomputa y dispara on_change al cambiar el set de breakers activos."""
    st = _state(breaker_interval_ms=5, volatility_window_ms=5_000, volatility_breaker_bps=50.0)
    st.breakers = BreakerManager(st.settings)
    st.feed_status = {"binance": ConnectionStatus.live, "kraken": ConnectionStatus.live,
                      "coinbase": ConnectionStatus.live}
    # mids con rango grande → dispara volatilidad
    changes: list[list[str]] = []
    mon = BreakerMonitor(st, st.settings, on_change=lambda m: changes.append(m.active_types()))

    async def _run():
        t = time.monotonic()
        st.latest_norm["binance"] = _nb("binance", 100.0, 101.0, t)
        task = asyncio.create_task(mon.run())
        await asyncio.sleep(0.02)
        # mueve el mid +5% → 500 bps > 50
        st.latest_norm["binance"] = _nb("binance", 106.0, 107.0, time.monotonic())
        await asyncio.sleep(0.05)
        mon.stop()
        await task

    with caplog.at_level(logging.WARNING, logger="app.risk.breakers"):
        asyncio.run(_run())

    assert st.breakers.tripped is True
    assert any("volatility" in c for c in changes)


def test_monitor_run_survives_tick_error(caplog):
    """Un fallo en un tick no mata la tarea (se loguea y sigue)."""
    st = _state(breaker_interval_ms=5)
    st.breakers = BreakerManager(st.settings)

    class Boom:
        def equity_total(self, books):
            raise RuntimeError("boom")
        def inventory_skew(self):
            return {"breached": False}

    st.portfolio = Boom()  # type: ignore[assignment]
    mon = BreakerMonitor(st, st.settings)

    async def _run():
        task = asyncio.create_task(mon.run())
        await asyncio.sleep(0.03)
        mon.stop()
        await task

    with caplog.at_level(logging.ERROR, logger="app.risk.breakers"):
        asyncio.run(_run())
    assert any("breaker tick" in r.message for r in caplog.records)


def test_monitor_run_propagates_cancellation():
    """El shutdown cancela la task: CancelledError se re-lanza (no se traga)."""
    st = _state(breaker_interval_ms=5)
    st.breakers = BreakerManager(st.settings)
    mon = BreakerMonitor(st, st.settings)

    async def _run():
        task = asyncio.create_task(mon.run())
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_run())


def test_monitor_run_skips_when_manager_none():
    """Sin manager (arranque/autostart off) el tick se salta sin fallar."""
    st = _state(breaker_interval_ms=5)
    st.breakers = None
    mon = BreakerMonitor(st, st.settings)

    async def _run():
        task = asyncio.create_task(mon.run())
        await asyncio.sleep(0.03)
        # se asigna el manager en runtime: el monitor lo relee y empieza a evaluar
        st.breakers = BreakerManager(st.settings)
        st.feed_status = {"binance": ConnectionStatus.live}
        await asyncio.sleep(0.03)
        mon.stop()
        await task

    asyncio.run(_run())
    assert st.breakers is not None  # no crasheó con manager None


# ----------------- GATE del motor (on_opp) vía endpoints + cliente -----------------
def test_control_status_default_clear(client):
    s = client.get("/api/v1/control/status").json()
    assert s["halted"] is False
    assert s["active"] == []
    assert len(s["breakers"]) == len(list(BreakerType))


def test_kill_switch_and_resume_endpoints(client):
    s = client.post("/api/v1/control/kill-switch").json()
    assert s["halted"] is True
    assert "kill_switch" in s["active"]
    # /health refleja el estado
    h = client.get("/health").json()
    assert h["breakers"]["halted"] is True
    # resume limpia
    s2 = client.post("/api/v1/control/resume").json()
    assert s2["halted"] is False
    assert "kill_switch" not in s2["active"]


def test_kill_switch_idempotent(client):
    client.post("/api/v1/control/kill-switch")
    s = client.post("/api/v1/control/kill-switch").json()
    assert s["halted"] is True


def test_engine_gate_discards_viable_when_breaker_active():
    """Con un breaker activo, una opp VIABLE se reclasifica a discarded(breaker_active) y el
    embudo se reconcilia (viable→discarded), replicando el on_opp del lifespan."""
    from app.models.enums import DiscardReason, Strategy
    from app.models.opportunity import Opportunity

    st = _state()
    st.breakers = BreakerManager(st.settings)
    st.breakers.trip_kill_switch()

    def on_opp(opp):
        is_viable = opp.status is OpportunityStatus.viable
        st.record_opportunity(opp)
        if is_viable and st.breakers is not None and st.breakers.tripped:
            opp.status = OpportunityStatus.discarded
            opp.discard_reason = DiscardReason.breaker_active
            st.opp_counts[OpportunityStatus.viable.value] = max(
                0, st.opp_counts[OpportunityStatus.viable.value] - 1
            )
            st.opp_counts[OpportunityStatus.discarded.value] += 1

    opp = Opportunity(
        id="opp-1", strategy=Strategy.spatial, symbol="BTC/USD",
        buy_venue="binance", sell_venue="kraken", q_target=1.0,
        vwap_buy=100.0, vwap_sell=101.0, status=OpportunityStatus.viable,
    )
    on_opp(opp)
    assert opp.status is OpportunityStatus.discarded
    assert opp.discard_reason is DiscardReason.breaker_active
    assert st.opp_counts["viable"] == 0
    assert st.opp_counts["discarded"] == 1
    assert st.opp_counts["detected"] == 1
