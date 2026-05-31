"""Tests del colector de métricas C13 (STORY-022, FR-017, NFR-001/010).

Cubren: percentiles de latencia por etapa; microestructura (effective/realized/impact)
desde los números del evaluador; capture/fill ratio; desglose por motivo y estrategia;
opportunity lifetime (episodios continuos + cierre por gap); y robustez ante NaN/None.
"""
from __future__ import annotations

import math

from app.config import get_settings
from app.metrics import MetricsCollector
from app.metrics.collector import _LIFETIME_BUCKETS_MS, _percentile
from app.models.enums import DiscardReason, LegSide, OpportunityStatus, Strategy
from app.models.execution import Execution, Leg
from app.models.opportunity import Opportunity


def _settings(**over):
    s = get_settings().model_copy(deep=True)
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _opp(
    *,
    status=OpportunityStatus.viable,
    strategy=Strategy.spatial,
    buy="binance",
    sell="kraken",
    q=1.0,
    vwap_buy=100.0,
    vwap_sell=110.0,
    net=8.0,
    latency_ms=0.2,
    t_detect=None,
    reason=None,
    id="o",
):
    return Opportunity(
        id=id, strategy=strategy, symbol="BTC/USD", buy_venue=buy, sell_venue=sell,
        q_target=q, vwap_buy=vwap_buy, vwap_sell=vwap_sell, net_pnl=net,
        status=status, discard_reason=reason, latency_ms=latency_ms, t_detect=t_detect,
    )


def _exec(*, matched=1.0, req=1.0, exec_latency=5, realized=8.0, unwound=False):
    return Execution(
        id="e", opportunity_id="o", matched_qty=matched, realized_pnl=realized,
        exec_latency_ms=exec_latency, unwound=unwound,
        legs=[
            Leg(venue="binance", side=LegSide.buy, qty_filled=matched, vwap=100.0,
                fee=0.1, qty_requested=req),
            Leg(venue="kraken", side=LegSide.sell, qty_filled=matched, vwap=110.0,
                fee=0.1, qty_requested=req),
        ],
    )


# ---- _percentile ----

def test_percentile_basico():
    assert _percentile([], 50) is None
    assert _percentile([42.0], 50) == 42.0
    assert _percentile([42.0], 99) == 42.0
    data = [float(i) for i in range(1, 101)]  # 1..100
    assert _percentile(data, 50) == 50.0  # nearest-rank ceil(.5*100)=50 → s[49]=50
    assert _percentile(data, 99) == 99.0
    assert _percentile(data, 100) == 100.0


def test_percentile_no_ordenado():
    assert _percentile([5.0, 1.0, 3.0, 2.0, 4.0], 50) == 3.0


# ---- latencia por etapa ----

def test_latencia_deteccion_p50_p99():
    c = MetricsCollector(_settings())
    for i in range(1, 101):
        c.record_opportunity(_opp(latency_ms=float(i)))
    snap = c.snapshot({"detected": 100})
    assert snap.detect_latency is not None
    assert snap.detect_latency.count == 100
    assert snap.detect_latency.p50_ms == 50.0
    assert snap.detect_latency.p99_ms == 99.0
    assert snap.detect_latency.max_ms == 100.0
    # Compat a nivel raíz.
    assert snap.p50_ms == 50.0 and snap.p99_ms == 99.0


def test_latencia_descarta_nan_y_negativos():
    c = MetricsCollector(_settings())
    c.record_opportunity(_opp(latency_ms=float("nan")))
    c.record_opportunity(_opp(latency_ms=-1.0))
    c.record_opportunity(_opp(latency_ms=None))
    snap = c.snapshot({"detected": 3})
    assert snap.detect_latency is None  # ninguna muestra válida


def test_latencia_ejecucion():
    c = MetricsCollector(_settings())
    for el in (2, 4, 6, 8, 10):
        c.record_execution(_exec(exec_latency=el))
    snap = c.snapshot({})
    assert snap.exec_latency is not None
    assert snap.exec_latency.count == 5
    assert snap.exec_latency.max_ms == 10.0


# ---- microestructura ----

def test_microestructura_effective_expected_impact():
    c = MetricsCollector(_settings())
    # eff = 110-100 = 10/BTC; expected_net = net/q = 8/1 = 8/BTC; impact = 2/BTC.
    c.record_opportunity(_opp(vwap_buy=100.0, vwap_sell=110.0, net=8.0, q=1.0))
    snap = c.snapshot({"detected": 1})
    assert snap.effective_spread == 10.0
    assert snap.expected_net_spread == 8.0
    assert math.isclose(snap.price_impact, 2.0)
    assert snap.realized_spread is None  # sin ejecuciones capturadas aún


def test_microestructura_expected_per_btc_usa_q():
    c = MetricsCollector(_settings())
    c.record_opportunity(_opp(vwap_buy=100.0, vwap_sell=110.0, net=16.0, q=2.0))
    snap = c.snapshot({"detected": 1})
    assert snap.effective_spread == 10.0
    assert snap.expected_net_spread == 8.0  # 16/2


def test_realized_spread_desde_ejecucion():
    """realized_spread es el neto REAL por BTC casado (no el modelado del evaluador)."""
    c = MetricsCollector(_settings())
    c.record_execution(_exec(matched=2.0, realized=12.0))  # 6/BTC
    snap = c.snapshot({})
    assert snap.realized_spread == 6.0


def test_impact_no_desincroniza_con_net_none():
    """Una opp con vwaps pero net=None (descartada por slippage) NO entra a effective ni a
    expected → no sesga el impact (Fin#1)."""
    c = MetricsCollector(_settings())
    c.record_opportunity(_opp(vwap_buy=100.0, vwap_sell=110.0, net=8.0, q=1.0))
    c.record_opportunity(_opp(vwap_buy=100.0, vwap_sell=200.0, net=None, q=1.0,
                              status=OpportunityStatus.discarded,
                              reason=DiscardReason.slippage_over_limit))
    snap = c.snapshot({"detected": 2})
    assert snap.effective_spread == 10.0  # la segunda (eff=100) NO entró
    assert math.isclose(snap.price_impact, 2.0)


def test_microestructura_descarta_inf():
    """Inf NO debe envenenar la media (math.isfinite, como C7)."""
    c = MetricsCollector(_settings())
    c.record_opportunity(_opp(vwap_buy=100.0, vwap_sell=float("inf"), net=8.0,
                              latency_ms=None))
    c.record_opportunity(_opp(latency_ms=float("inf"), vwap_buy=None, vwap_sell=None))
    snap = c.snapshot({"detected": 2})
    assert snap.effective_spread is None  # la muestra Inf se descartó
    assert snap.detect_latency is None    # latencia Inf descartada


def test_microestructura_omite_sin_vwap():
    c = MetricsCollector(_settings())
    c.record_opportunity(_opp(vwap_buy=None, vwap_sell=None))
    snap = c.snapshot({"detected": 1})
    assert snap.effective_spread is None
    assert snap.price_impact is None


# ---- ratios ----

def test_capture_ratio():
    c = MetricsCollector(_settings())
    snap = c.snapshot({"detected": 10, "captured": 3})
    assert snap.capture_ratio == 0.3
    assert c.snapshot({"detected": 0}).capture_ratio is None


def test_fill_ratio_parcial_y_cap():
    c = MetricsCollector(_settings())
    c.record_execution(_exec(matched=0.5, req=1.0))   # 0.5
    c.record_execution(_exec(matched=1.0, req=1.0))   # 1.0
    c.record_execution(_exec(matched=2.0, req=1.0))   # cap a 1.0
    snap = c.snapshot({})
    assert math.isclose(snap.fill_ratio, (0.5 + 1.0 + 1.0) / 3)


# ---- desgloses ----

def test_desglose_por_motivo_y_estrategia():
    c = MetricsCollector(_settings())
    c.record_opportunity(_opp(status=OpportunityStatus.discarded,
                              reason=DiscardReason.not_profitable_fees, strategy=Strategy.spatial))
    c.record_opportunity(_opp(status=OpportunityStatus.discarded,
                              reason=DiscardReason.breaker_active, strategy=Strategy.stat_z))
    c.record_opportunity(_opp(status=OpportunityStatus.captured, strategy=Strategy.spatial))
    snap = c.snapshot({"detected": 3})
    assert snap.discard_reasons["not_profitable_fees"] == 1
    assert snap.discard_reasons["breaker_active"] == 1
    assert snap.by_strategy["spatial"]["discarded"] == 1
    assert snap.by_strategy["spatial"]["captured"] == 1
    assert snap.by_strategy["stat_z"]["discarded"] == 1


# ---- opportunity lifetime ----

def test_lifetime_episodio_continuo():
    c = MetricsCollector(_settings(lifetime_gap_ms=250))
    # Mismo cruce dirigido detectado a t=0, 0.1, 0.2 s (gaps 100ms < 250ms) → un episodio 200ms.
    for t in (0.0, 0.1, 0.2):
        c.record_opportunity(_opp(t_detect=t))
    snap = c.snapshot({"detected": 3})
    # Episodio aún abierto: su duración vigente (200ms) entra en el histograma.
    assert sum(snap.opp_lifetime_hist) == 1
    assert snap.opp_lifetime_p50_ms is not None
    assert 150 <= snap.opp_lifetime_p50_ms <= 250


def test_lifetime_cierra_por_gap():
    c = MetricsCollector(_settings(lifetime_gap_ms=100))
    # gap de 1s (>100ms) cierra el primer episodio (dur 0) y abre otro.
    c.record_opportunity(_opp(t_detect=0.0))
    c.record_opportunity(_opp(t_detect=1.0))
    snap = c.snapshot({"detected": 2})
    assert sum(snap.opp_lifetime_hist) == 2  # un cerrado (0ms) + uno abierto (0ms)


def test_lifetime_distingue_direccion():
    c = MetricsCollector(_settings())
    c.record_opportunity(_opp(buy="binance", sell="kraken", t_detect=0.0))
    c.record_opportunity(_opp(buy="kraken", sell="binance", t_detect=0.05))
    snap = c.snapshot({"detected": 2})
    assert sum(snap.opp_lifetime_hist) == 2  # dos cruces dirigidos distintos, ambos abiertos


def test_lifetime_buckets_consistentes():
    c = MetricsCollector(_settings())
    snap = c.snapshot({})
    assert len(snap.opp_lifetime_hist) == len(_LIFETIME_BUCKETS_MS) + 1
    assert snap.opp_lifetime_buckets_ms == list(_LIFETIME_BUCKETS_MS)


def test_lifetime_t_detect_retrocede_no_da_negativo():
    """Si t_detect retrocede (replay/multi-stream), no debe producir lifetime negativo (H3)."""
    c = MetricsCollector(_settings(lifetime_gap_ms=1000))
    c.record_opportunity(_opp(t_detect=1.0))
    c.record_opportunity(_opp(t_detect=0.5))  # retrocede → cierra el anterior, reabre
    snap = c.snapshot({"detected": 2})
    assert snap.opp_lifetime_p50_ms is not None
    assert snap.opp_lifetime_p50_ms >= 0.0
    assert all(v >= 0 for v in [snap.opp_lifetime_p50_ms, snap.opp_lifetime_p99_ms or 0])


def test_lifetime_expira_y_acota_open():
    """Episodios cuyo cruce desaparece > gap se cierran (registran lifetime) y se liberan de
    `_open` (no fuga de memoria, M1). El tiempo avanza vía el t_detect de OTRO cruce."""
    c = MetricsCollector(_settings(lifetime_gap_ms=100))
    c.record_opportunity(_opp(buy="binance", sell="kraken", t_detect=0.0))
    # otro cruce 1s después: expira el primero (1s > 100ms) y lo cierra.
    c.record_opportunity(_opp(buy="coinbase", sell="kraken", t_detect=1.0))
    assert ("spatial", "binance", "kraken") not in c._open  # liberado
    snap = c.snapshot({"detected": 2})
    # un episodio cerrado (binance→kraken, dur 0) + uno abierto (coinbase→kraken).
    assert sum(snap.opp_lifetime_hist) == 2


def test_lifetime_sin_t_detect_se_omite():
    c = MetricsCollector(_settings())
    c.record_opportunity(_opp(t_detect=None))
    snap = c.snapshot({"detected": 1})
    assert sum(snap.opp_lifetime_hist) == 0


# ---- snapshot vacío honesto ----

def test_snapshot_vacio_es_honesto():
    c = MetricsCollector(_settings())
    snap = c.snapshot({})
    assert snap.effective_spread is None
    assert snap.expected_net_spread is None
    assert snap.realized_spread is None
    assert snap.price_impact is None
    assert snap.capture_ratio is None
    assert snap.fill_ratio is None
    assert snap.detect_latency is None
    assert snap.exec_latency is None


# ---- endpoint /metrics (integración, autostart off) ----

def test_endpoint_metrics_autostart_off(client):
    r = client.get("/api/v1/metrics")
    assert r.status_code == 200
    body = r.json()
    # Embudo presente (fuente única opp_counts), agregados nulos honestos sin tráfico.
    assert body["detected"] == 0
    assert body["effective_spread"] is None
    assert body["capture_ratio"] is None
    assert "opp_lifetime_buckets_ms" in body
