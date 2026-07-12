"""Tests del fallback a replay para demo C16 (STORY-024, FR-018).

Cubren: detección de caída de feed → auto-activación; vuelta a vivo al recuperarse; modos
on/off forzados; inyección re-sellada (fresca) por el pipeline; no-activación sin datos;
robustez del controlador.
"""
from __future__ import annotations

import pytest

from app.backtest import Recorder
from app.config import get_settings
from app.demo import DemoFallback, JuryScenarioPlayer
from app.demo.scenarios import (
    ORDER_FAILURE_NO_CLAIM,
    REPEATS_PER_SCENARIO,
    build_jury_scenarios,
)
from app.engine.explain import build_opportunity_explanation
from app.models.enums import DiscardReason, OpportunityStatus, Strategy
from app.models.market import NormalizedBook
from app.models.opportunity import Opportunity
from app.state import AppState
from app.stream.hub import StreamHub


def _settings(**over):
    s = get_settings().model_copy(deep=True)
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _nb(exchange="binance", *, bid=100.0, ask=101.0, ts=1.0):
    return NormalizedBook(
        exchange=exchange, symbol="BTC/USD", quote_ccy="USD",
        bids=[[bid, 1.0]], asks=[[ask, 1.0]],
        price_norm_factor=1.0, ts_exchange=ts, ts_recv_monotonic=ts,
    )


def _state(settings, recorder=None):
    st = AppState(settings=settings, hub=StreamHub(client_queue_maxsize=100))
    st.recorder = recorder
    return st


def _fallback(settings, recorder, sink, changes=None):
    return DemoFallback(
        _state(settings, recorder), settings,
        inject=sink.append,
        on_change=(changes.append if changes is not None else None),
    )


def _seed_recorder(n=5):
    rec = Recorder(maxlen=100, enabled=True)
    for i in range(n):
        rec.record(_nb(ts=float(i)))
    return rec


# ---- auto: activación por caída de feed ----

def test_auto_activa_sin_feed_real():
    sink: list[NormalizedBook] = []
    changes: list[dict] = []
    fb = _fallback(_settings(demo_stale_ms=2000), _seed_recorder(), sink, changes)
    # Nunca hubo mark_live → real_alive False → en auto se activa e inyecta.
    fb.tick(now=10.0)
    assert fb.active is True
    assert len(sink) == 1
    assert changes and changes[0]["badge"] == "DEMO DATA"


def test_auto_no_activa_con_feed_vivo():
    sink: list[NormalizedBook] = []
    fb = _fallback(_settings(demo_stale_ms=2000), _seed_recorder(), sink)
    fb.mark_live(now=10.0)
    fb.tick(now=10.5)  # 500ms < 2000ms → feed vivo
    assert fb.active is False
    assert sink == []


def test_auto_vuelve_a_vivo_al_recuperarse():
    sink: list[NormalizedBook] = []
    changes: list[dict] = []
    fb = _fallback(_settings(demo_stale_ms=2000), _seed_recorder(), sink, changes)
    fb.tick(now=10.0)             # activa (sin feed real)
    assert fb.active is True
    fb.mark_live(now=20.0)        # llega dato real
    fb.tick(now=20.1)            # recupera → desactiva
    assert fb.active is False
    assert changes[-1]["active"] is False
    assert changes[-1]["source"] == "live"


def test_auto_activa_tras_stale():
    sink: list[NormalizedBook] = []
    fb = _fallback(_settings(demo_stale_ms=2000), _seed_recorder(), sink)
    fb.mark_live(now=10.0)
    fb.tick(now=10.5)            # vivo
    assert fb.active is False
    fb.tick(now=13.0)           # 3000ms > 2000ms sin dato real → activa
    assert fb.active is True


# ---- modos forzados ----

def test_modo_on_fuerza_replay_con_feed_vivo():
    sink: list[NormalizedBook] = []
    fb = _fallback(_settings(), _seed_recorder(), sink)
    fb.mark_live(now=10.0)
    fb.set_mode("on")
    fb.tick(now=10.1)           # feed vivo PERO modo on → replay
    assert fb.active is True
    assert len(sink) == 1


def test_modo_off_nunca_replay():
    sink: list[NormalizedBook] = []
    fb = _fallback(_settings(), _seed_recorder(), sink)
    fb.set_mode("off")
    fb.tick(now=100.0)          # sin feed real PERO modo off → no replay
    assert fb.active is False
    assert sink == []


def test_modo_jury_inyecta_escenarios_deterministas():
    sink: list[NormalizedBook] = []
    fb = _fallback(_settings(), _seed_recorder(), sink)
    fb.set_mode("jury")
    fb.tick(now=100.0)
    st = fb.status()
    assert fb.active is True
    assert st["source"] == "deterministic"
    assert st["scenario"] == "good_edge"
    assert st["scenario_index"] == 1
    assert st["n_scenarios"] == 7
    assert len(sink) == 2


def test_jury_player_cycles_all_required_scenarios():
    player = JuryScenarioPlayer(repeats_per_scenario=1)
    names = [player.next_frame().scenario.name for _ in range(8)]
    assert names[:7] == [
        "good_edge",
        "naive_trap",
        "peg_adverse",
        "stale_feed",
        "latency_decay",
        "thin_book",
        "order_failure",
    ]
    assert names[7] == "good_edge"


# ---- PRD-013: identidad de activación (scenario_run_id) y cadencia ----

def test_scenario_run_id_increments_on_transition_and_same_name_reselection():
    sink: list[NormalizedBook] = []
    fb = _fallback(_settings(), None, sink)
    fb.set_mode("jury")
    fb.tick(now=100.0)
    st = fb.status()
    assert st["scenario"] == "good_edge"
    assert st["scenario_run_id"] == 0
    assert st["scenario_started_at"] == 100.0
    # Transición natural del player (auto-avance tras agotar las repeticiones).
    for i in range(REPEATS_PER_SCENARIO):
        fb.tick(now=101.0 + i)
    st2 = fb.status()
    assert st2["scenario"] == "naive_trap"
    assert st2["scenario_run_id"] == 1
    # Re-selección explícita del MISMO nombre → nueva activación → nuevo run_id.
    assert fb.select_jury_scenario("naive_trap") is True
    fb.tick(now=500.0)
    st3 = fb.status()
    assert st3["scenario"] == "naive_trap"
    assert st3["scenario_run_id"] == 2
    assert st3["scenario_started_at"] == 500.0


def test_repeated_frames_keep_scenario_run_id():
    sink: list[NormalizedBook] = []
    fb = _fallback(_settings(), None, sink)
    fb.set_mode("jury")
    fb.tick(now=100.0)
    fb.tick(now=100.5)
    fb.tick(now=101.0)
    st = fb.status()
    # Frames repetidos del mismo escenario conservan identidad Y started_at del PRIMER frame.
    assert st["scenario"] == "good_edge"
    assert st["scenario_run_id"] == 0
    assert st["scenario_started_at"] == 100.0


def test_scenario_change_is_published_before_its_books_are_injected():
    """El SSE demo debe preceder opportunity/metrics producidos síncronamente por inject."""
    events: list[tuple[str, int | str | None]] = []
    settings = _settings()
    fb = DemoFallback(
        _state(settings),
        settings,
        inject=lambda nb: events.append(("inject", nb.exchange)),
        on_change=lambda st: events.append(("change", st.get("scenario_run_id"))),
    )
    fb.set_mode("jury")
    fb.tick(now=100.0)
    # También en la PRIMERA activación: el demo con run_id=0 precede a sus books.
    # (_activate emite antes un change transitorio con run_id=None; el cliente lo
    # descarta por run_id nulo — lo que importa es que 0 llegue antes del primer inject.)
    run0_change = events.index(("change", 0))
    first_inject = next(i for i, ev in enumerate(events) if ev[0] == "inject")
    assert run0_change < first_inject
    # Frame REPETIDO del mismo escenario: inyecta books pero NO re-publica demo
    # (un evento demo duplicado con el mismo run_id sería ruido, no identidad nueva).
    events.clear()
    fb.tick(now=100.5)
    assert all(ev[0] == "inject" for ev in events)
    assert any(ev[0] == "inject" for ev in events)
    # Consumir el resto de good_edge; el siguiente tick abre naive_trap.
    for i in range(REPEATS_PER_SCENARIO - 2):
        fb.tick(now=101.0 + i)
    events.clear()
    fb.tick(now=200.0)

    assert events[0] == ("change", 1)
    assert events[1][0] == "inject"


def test_jury_window_is_longer_than_two_metrics_intervals():
    """Cadencia mínima RF-002: duración >= 2×metrics_emit_ms + 250 ms garantiza una baseline
    de métricas y al menos una muestra POSTERIOR dentro de la misma activación."""
    s = get_settings()
    duration_ms = REPEATS_PER_SCENARIO * s.demo_replay_interval_ms
    assert duration_ms >= 2 * s.metrics_emit_ms + 250


# ---- PRD-013: catálogo de contratos esperado→observable (los 7 escenarios) ----

# Tabla de contratos del PRD-013: señal verificable o claim retirado explícito (RF-003B).
JURY_CONTRACTS = {
    "good_edge": "captured",
    "naive_trap": "not_profitable_fees",
    "peg_adverse": "peg_adverse",
    "stale_feed": "stale_data_excluded",
    "latency_decay": "slippage_over_limit",
    "thin_book": "thin_book",
    "order_failure": ORDER_FAILURE_NO_CLAIM,
}


def test_jury_catalog_matches_contract_table_exactly():
    names = [s.name for s in build_jury_scenarios()]
    assert names == list(JURY_CONTRACTS)


@pytest.mark.parametrize("name", list(JURY_CONTRACTS))
def test_jury_scenario_declares_verifiable_contract(name):
    scenario = {s.name: s for s in build_jury_scenarios()}[name]
    assert scenario.expected_result == JURY_CONTRACTS[name]
    if name == "order_failure":
        # RF-003B: claim retirado — nunca promete preflight/test-order (el player sólo
        # construye books; el fallback jamás invoca ejecución).
        assert "preflight" not in scenario.expected_result
        assert "test_order" not in scenario.expected_result
    elif name == "good_edge":
        # Señal: opportunity.status=captured (evento) / delta metrics.captured (respaldo).
        assert scenario.expected_result == OpportunityStatus.captured.value
    elif name == "stale_feed":
        # Señal: estado feed/breaker stale, no un DiscardReason; el fixture inyecta stale.
        assert scenario.stale is True
    else:
        # Señal: discard_reason homónimo del pipeline (evento + delta en discard_reasons).
        assert scenario.expected_result in {r.value for r in DiscardReason}


# ---- inyección re-sellada (fresca) ----

def test_inyeccion_resella_ts_fresco():
    sink: list[NormalizedBook] = []
    fb = _fallback(_settings(), _seed_recorder(), sink)
    fb.tick(now=999.0)
    assert sink[0].ts_recv_monotonic == 999.0   # re-sellado a `now`, no el ts grabado (0..4)
    assert sink[0].exchange == "binance"


def test_replay_ciclico():
    sink: list[NormalizedBook] = []
    fb = _fallback(_settings(), _seed_recorder(n=3), sink)
    for t in range(7):
        fb.tick(now=float(100 + t))
    assert len(sink) == 7  # 7 inyecciones sobre 3 ticks → cicla sin agotarse


# ---- sin datos ----

def test_sin_datos_no_activa():
    sink: list[NormalizedBook] = []
    fb = _fallback(_settings(demo_recording_path=""), Recorder(enabled=True), sink)
    fb.tick(now=100.0)          # recorder vacío, sin archivo → no activa (honesto)
    assert fb.active is False
    assert sink == []


def test_recorder_none_no_activa():
    sink: list[NormalizedBook] = []
    fb = _fallback(_settings(demo_recording_path=""), None, sink)
    fb.tick(now=100.0)
    assert fb.active is False


def test_respaldo_archivo_en_frio(tmp_path):
    """Arranque en frío (recorder vacío) → usa el recording de respaldo en archivo (cargado
    UNA vez en construcción, no en el hot loop)."""
    path = tmp_path / "backup.jsonl"
    _seed_recorder(4).to_jsonl(str(path))
    sink: list[NormalizedBook] = []
    fb = _fallback(_settings(demo_recording_path=str(path)),
                   Recorder(enabled=True), sink)  # recorder vivo VACÍO
    fb.tick(now=500.0)
    assert fb.active is True
    assert len(sink) == 1
    assert sink[0].ts_recv_monotonic == 500.0


def test_respaldo_archivo_binario_no_crash(tmp_path):
    """Archivo de respaldo binario/no-UTF8 → no aborta el arranque (UnicodeDecodeError no es
    OSError) y simplemente no hay datos que reproducir."""
    path = tmp_path / "bad.bin"
    path.write_bytes(b"\xff\xfe\x00\x01binary garbage\x80")
    sink: list[NormalizedBook] = []
    fb = _fallback(_settings(demo_recording_path=str(path)), Recorder(enabled=True), sink)
    fb.tick(now=100.0)
    assert fb.active is False  # sin datos válidos → no activa
    assert sink == []


# ---- status ----

def test_status_shape():
    fb = _fallback(_settings(), _seed_recorder(), [])
    st = fb.status()
    assert st["active"] is False and st["source"] == "live" and st["badge"] is None
    fb.tick(now=10.0)
    st2 = fb.status()
    assert st2["active"] is True and st2["source"] == "replay"
    assert st2["badge"] == "DEMO DATA" and st2["n_replay_ticks"] == 5


# ---- endpoints ----

def test_endpoint_demo_status(client):
    r = client.get("/api/v1/demo")
    assert r.status_code == 200
    body = r.json()
    assert "active" in body and "mode" in body


def test_endpoint_demo_set_mode(client):
    r = client.post("/api/v1/demo?mode=on")
    assert r.status_code == 200
    assert r.json()["mode"] == "on"
    r2 = client.post("/api/v1/demo?mode=invalid")
    assert r2.status_code == 422


def test_endpoint_demo_set_jury_mode(client):
    r = client.post("/api/v1/demo?mode=jury")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "jury"
    assert body["source"] == "deterministic"
    assert body["scenario"] == "good_edge"
    assert body["n_scenarios"] == 7


def test_endpoint_demo_lists_and_selects_adverse_scenarios(client):
    listed = client.get("/api/v1/demo/scenarios")
    assert listed.status_code == 200
    scenarios = {s["name"]: s for s in listed.json()["scenarios"]}
    assert scenarios["thin_book"]["expected_result"] == "thin_book"
    assert scenarios["order_failure"]["kind"] == "execution"

    selected = client.post("/api/v1/demo/scenario/thin_book")
    assert selected.status_code == 200
    body = selected.json()
    assert body["mode"] == "jury"
    assert body["scenario"] == "thin_book"
    assert body["expected_result"] == "thin_book"


def test_session_export_contains_sections_and_redacts_settings(client):
    ctx = client.app.state.ctx
    buy = _nb("bitstamp", bid=99.0, ask=100.0)
    sell = _nb("kraken", bid=103.0, ask=104.0)
    opp = Opportunity(
        id="export-opp",
        strategy=Strategy.spatial,
        symbol="BTC/USD",
        buy_venue="bitstamp",
        sell_venue="kraken",
        q_target=1.0,
        vwap_buy=100.0,
        vwap_sell=103.0,
        status=OpportunityStatus.viable,
        t_recv=1.0,
        t_detect=1.0,
    )
    opp.explanation = build_opportunity_explanation(opp, buy, sell, ctx.settings)
    ctx.latest_norm[buy.exchange] = buy
    ctx.latest_norm[sell.exchange] = sell
    ctx.record_opportunity(opp)

    r = client.get("/api/v1/session/export")
    assert r.status_code == 200
    body = r.json()
    assert {"metadata", "settings", "quotes", "opportunities", "metrics", "demo"} <= set(body)
    assert "runtime_params" in body
    assert "control_token" not in body["settings"]
    assert "db_url" not in body["settings"]
    assert "calibration" in body
    assert "shadow_samples" in body["calibration"]
    assert body["opportunities"][0]["id"] == "export-opp"
    assert body["opportunities"][0]["explanation"]["id"] == "export-opp"


def test_health_incluye_demo(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert "demo" in r.json()
