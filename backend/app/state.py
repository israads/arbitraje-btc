"""Estado de la aplicación: referencias vivas compartidas en el proceso.

Se crea en el `lifespan` de FastAPI y se cuelga de `app.state.ctx`. Estado de mercado
vivo: último order book crudo (C1) y normalizado a USD (C3) por venue, cola del bus
(C4), detector (C5) y embudo de oportunidades. Inventario/métricas/breakers en
STORY-010/022/018.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .bus import BoundedQueue
from .config import Settings
from .models.enums import ConnectionStatus, OpportunityStatus
from .models.market import NormalizedBook, RawOrderBook
from .models.opportunity import Opportunity
from .stream.hub import StreamHub

if TYPE_CHECKING:
    from .backtest import Recorder
    from .demo import DemoFallback
    from .engine import NetEvaluator, Prioritizer, SpatialDetector, StatZDetector
    from .ingest import ExchangeIngestor
    from .integrity.checker import BookIntegrityChecker
    from .metrics import MetricsCollector
    from .models.backtest import BacktestResult
    from .models.calibration import ShadowOpportunitySample
    from .normalize import Normalizer, PegIngestor, PegProvider
    from .risk.breakers import BreakerManager
    from .sim import ExecutionSimulator, Portfolio
    from .store import BatchWriter


def _empty_funnel() -> dict[str, int]:
    # Buckets por status del ciclo de vida + `unwound`: sub-conteo de los `captured` que
    # acabaron en UNWIND (2ª pata no rentable tras la latencia, STORY-016). No es un status
    # del enum (un unwind SÍ se capturó —y se cerró a pérdida—), por eso va como key aparte;
    # lo consume el embudo del jurado (STORY-022).
    funnel = {s.value: 0 for s in OpportunityStatus}
    funnel["unwound"] = 0
    return funnel


@dataclass
class AppState:
    settings: Settings
    hub: StreamHub
    tasks: list[asyncio.Task[None]] = field(default_factory=list)
    ingestors: list[ExchangeIngestor] = field(default_factory=list)
    peg_ingestors: list[PegIngestor] = field(default_factory=list)
    peg: PegProvider | None = None
    normalizer: Normalizer | None = None
    bus: BoundedQueue[NormalizedBook] | None = None
    detector: SpatialDetector | None = None
    stat_detector: StatZDetector | None = None  # C5 — arbitraje estadístico z-score (STORY-019)
    evaluator: NetEvaluator | None = None  # C6 — evaluador de neto (STORY-008)
    prioritizer: Prioritizer | None = None  # C7 — ranking por score (STORY-020)
    simulator: ExecutionSimulator | None = None  # C9 — simulador de ejecución (STORY-009)
    portfolio: Portfolio | None = None  # C10 — inventario pre-posicionado + P&L (STORY-010)
    writer: BatchWriter | None = None   # C12 — escritor async/batch (STORY-011)
    integrity: BookIntegrityChecker | None = None  # C2 — integridad de book (STORY-015)
    breakers: BreakerManager | None = None  # C8 — circuit breakers + kill switch (STORY-018)
    recorder: Recorder | None = None    # C14 — grabador de ticks para replay (STORY-021)
    metrics: MetricsCollector | None = None  # C13 — métricas del jurado (STORY-022)
    demo: DemoFallback | None = None     # C16 — fallback a replay para demo (STORY-024)
    last_backtest: BacktestResult | None = None  # último resultado de replay (C14)
    # Último order book por exchange: crudo (C1) y normalizado a USD (C3).
    latest_books: dict[str, RawOrderBook] = field(default_factory=dict)
    latest_norm: dict[str, NormalizedBook] = field(default_factory=dict)
    # Salud de feeds por venue (C8 watchdog, STORY-014): live | stale.
    feed_status: dict[str, ConnectionStatus] = field(default_factory=dict)
    # Embudo de oportunidades (C13 lo formaliza) + buffer de las recientes.
    opp_counts: dict[str, int] = field(default_factory=_empty_funnel)
    recent_opps: deque[Opportunity] = field(default_factory=lambda: deque(maxlen=200))
    opps_by_id: dict[str, Opportunity] = field(default_factory=dict)
    shadow_samples: deque[ShadowOpportunitySample] = field(init=False)

    def __post_init__(self) -> None:
        self.shadow_samples = deque(maxlen=self.settings.shadow_sample_maxlen)

    def record_opportunity(self, opp: Opportunity) -> None:
        """Registra una oportunidad en el embudo (C13) y el buffer de recientes.

        'detected' es el TOPE del embudo: cuenta toda opp que pasó por detección
        (C5). Tras el evaluador (C6) la opp llega como viable/discarded; ese estado
        suma además a su bucket. Así ``detected`` = total de cruces y
        ``viable + discarded (+ executable/captured)`` = desglose — la lectura
        correcta del embudo para el jurado (antes ``detected`` quedaba en 0 porque
        el evaluador reescribe el estado antes de contar)."""
        self.opp_counts[OpportunityStatus.detected.value] += 1
        if opp.status is not OpportunityStatus.detected:
            self.opp_counts[opp.status.value] = (
                self.opp_counts.get(opp.status.value, 0) + 1
            )
        self.recent_opps.append(opp)
        self.opps_by_id[opp.id] = opp
        max_recent = self.recent_opps.maxlen or 200
        if len(self.opps_by_id) > max_recent * 2:
            live_ids = {o.id for o in self.recent_opps}
            self.opps_by_id = {oid: o for oid, o in self.opps_by_id.items() if oid in live_ids}

    def record_shadow_sample(self, sample: ShadowOpportunitySample) -> None:
        """Registra muestra shadow para calibración observe-only (PRD-005)."""
        self.shadow_samples.append(sample)
