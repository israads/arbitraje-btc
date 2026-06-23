"""Snapshot de métricas para el jurado (C13): embudo + latencia + microestructura.

Lo produce `app.metrics.MetricsCollector` (STORY-022) y lo sirve `GET /api/v1/metrics`
(+ evento SSE `metrics`). Todos los agregados son honestos: `None` cuando no hay muestras
(no se inventa 0.0). Latencia y ventanas son monotónicas (NFR-001/010).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class StageLatency(BaseModel):
    """Latencia p50/p99 de una etapa del pipeline (monotónica, en ventana)."""

    stage: str
    count: int = 0
    p50_ms: float | None = None
    p99_ms: float | None = None
    max_ms: float | None = None


class MetricsSnapshot(BaseModel):
    window: str = "session"
    n_samples: int = 0  # tamaño de la ventana de microestructura efectiva

    # --- Embudo (FR-017): detectadas → viables → ejecutables → capturadas + descartadas ---
    # Conteos ACUMULADOS (misma semántica que `AppState.opp_counts`, fuente única).
    detected: int = 0
    viable: int = 0
    executable: int = 0
    captured: int = 0
    discarded: int = 0
    unwound: int = 0  # sub-conteo de `captured` que acabaron en UNWIND (STORY-016)
    # Desglose de descartes por motivo (DiscardReason → conteo) — "con motivo".
    discard_reasons: dict[str, int] = Field(default_factory=dict)
    # Desglose del embudo por estrategia (spatial / stat_z) — visibilidad del z-score.
    by_strategy: dict[str, dict[str, int]] = Field(default_factory=dict)
    # Ejecución protegida/testnet (PRD-003/006): labels acotados por venue y resultado.
    preflight_results: dict[str, dict[str, int]] = Field(default_factory=dict)
    test_order_results: dict[str, dict[str, int]] = Field(default_factory=dict)

    # --- Latencia por etapa (monotónica, en ventana) — NFR-001 p50<50ms ---
    detect_latency: StageLatency | None = None   # ingesta → detección (t_detect - t_recv)
    exec_latency: StageLatency | None = None      # ventana de ejecución entre patas (leg risk)
    # Compat: p50/p99 de la etapa de DETECCIÓN a nivel raíz (lectura rápida del jurado).
    p50_ms: float | None = None
    p99_ms: float | None = None

    # --- Microestructura (USD por BTC, media en ventana) ---
    # Del EVALUADOR (pre-trade, sobre opps evaluadas), emparejados por muestra:
    effective_spread: float | None = None    # edge BRUTO: vwap_sell - vwap_buy
    expected_net_spread: float | None = None  # neto MODELADO por C6: net_pnl/q (asume fill pleno)
    price_impact: float | None = None         # coste/BTC modelado: effective - expected_net
    # De la EJECUCIÓN (post-trade, sobre capturadas) — el neto REAL, distinto del modelado:
    realized_spread: float | None = None      # realized_pnl/matched: incl. parcial/legrisk/unwind
    capture_ratio: float | None = None        # captured / detected
    fill_ratio: float | None = None           # media(matched_qty / q_target) sobre capturadas

    # --- Opportunity lifetime vs latencia (histograma de ms) ---
    opp_lifetime_hist: list[int] = Field(default_factory=list)
    opp_lifetime_buckets_ms: list[float] = Field(default_factory=list)  # cotas superiores
    opp_lifetime_p50_ms: float | None = None
    opp_lifetime_p99_ms: float | None = None
