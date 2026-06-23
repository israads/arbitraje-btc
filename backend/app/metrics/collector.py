"""C13 — Colector de métricas para el jurado (STORY-022, FR-017, NFR-001/010).

Acumula, EN VENTANA (deques acotadas) y de forma monotónica:

- **Embudo** detectadas→viables→ejecutables→capturadas con MOTIVO (desglose por
  `DiscardReason`) y por ESTRATEGIA (spatial / stat_z). Los conteos del embudo son
  ACUMULADOS y se leen de la fuente única `AppState.opp_counts` al construir el snapshot
  (este colector NO duplica el conteo del embudo: sólo añade los desgloses).
- **Latencia por etapa** (p50/p99/max): detección (ingesta→motor, `latency_ms`) y
  ejecución (ventana entre patas, `exec_latency_ms`). Percentiles sobre la ventana.
- **Microestructura** (USD por BTC): effective spread (edge bruto `vwap_sell-vwap_buy`),
  realized spread (edge neto `net_pnl/q`), price impact (coste = effective-realized),
  capture ratio (captured/detected), fill ratio (matched/q_target sobre capturadas).
- **Opportunity lifetime**: duración (ms) que un cruce dirigido (estrategia,buy,sell)
  permanece CONTINUAMENTE detectado → histograma "lifetime vs latencia" (la tesis: el
  edge vive ms; con latencia sub-ms ES capturable).

Diseño puro y testeable: sin red, sin I/O, sin reloj real (los timestamps llegan en los
objetos `Opportunity`/`Execution`). `record_*` es O(1) amortizado; `snapshot()` calcula
percentiles bajo demanda. Thread-safety no necesaria: un solo event loop (Apéndice F).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict, deque

from ..config import Settings
from ..models.enums import OpportunityStatus, Strategy
from ..models.execution import Execution
from ..models.metrics import MetricsSnapshot, StageLatency
from ..models.opportunity import Opportunity

# Cotas superiores (ms) del histograma de opportunity lifetime. El último bucket es
# "todo lo mayor" (cota +inf implícita).
_LIFETIME_BUCKETS_MS: tuple[float, ...] = (1, 2, 5, 10, 25, 50, 100, 250, 500, 1000)


def _percentile(samples: list[float], q: float) -> float | None:
    """Percentil `q` (0..100) por nearest-rank sobre muestras ya materializadas.

    Determinista y sin numpy (evita dependencia en el camino de métricas). Lista vacía
    → None (honesto: no hay dato, no se inventa 0.0)."""
    if not samples:
        return None
    s = sorted(samples)
    # nearest-rank: rank = ceil(q/100 · n), 1-indexado, acotado a [1, n].
    rank = max(1, min(len(s), math.ceil(q / 100.0 * len(s))))
    return s[rank - 1]


class MetricsCollector:
    """Acumulador de métricas del jurado (C13). Una instancia viva por proceso."""

    def __init__(self, settings: Settings) -> None:
        w = settings.metrics_window
        self._lifetime_gap = settings.lifetime_gap_ms / 1000.0
        # Ventanas de latencia (monotónicas).
        self._detect_lat: deque[float] = deque(maxlen=w)
        self._exec_lat: deque[float] = deque(maxlen=w)
        # Ventanas de microestructura (USD por BTC). EVALUADOR (pre-trade, sobre opps
        # evaluadas): effective (bruto) y expected_net (modelado) emparejados en la MISMA
        # muestra → impact modelado consistente (no `mean(a)-mean(b)` de poblaciones distintas).
        self._eff_spread: deque[float] = deque(maxlen=w)
        self._expected_net: deque[float] = deque(maxlen=w)
        self._modeled_impact: deque[float] = deque(maxlen=w)  # eff - expected_net (par exacto)
        # EJECUCIÓN (post-trade, sobre capturadas): realized REAL = realized_pnl/matched_qty
        # (incluye fills parciales, leg risk y pérdidas de unwind). Honesto: distinto del
        # expected_net del evaluador, que asume fill pleno y simétrico.
        self._realized_spread: deque[float] = deque(maxlen=w)
        self._fill_ratio: deque[float] = deque(maxlen=w)
        # Lifetime: episodios cerrados (ms) + episodios abiertos por cruce dirigido.
        self._lifetime_ms: deque[float] = deque(maxlen=w)
        self._open: dict[tuple[str, str, str], tuple[float, float]] = {}  # key → (first,last)
        # Desgloses ACUMULADOS (no en ventana: el embudo es total de sesión).
        self._discard_reasons: Counter[str] = Counter()
        self._by_strategy: dict[str, Counter[str]] = {
            s.value: Counter() for s in Strategy
        }
        self._preflight_results: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self._test_order_results: defaultdict[str, Counter[str]] = defaultdict(Counter)

    # ---- Registro (camino caliente; O(1) amortizado) ----

    def record_opportunity(self, opp: Opportunity) -> None:
        """Registra una oportunidad en latencia + microestructura + lifetime + desgloses.

        Se llama una vez por opp DESPUÉS de que el motor selló su estado final del tick
        (viable/discarded/captured), con el mismo objeto que entra al embudo."""
        # Latencia de detección (ingesta → motor). Sólo muestras FINITAS y >=0 (isfinite
        # descarta NaN e Inf — un Inf envenenaría la media/percentil, como ya hace C7).
        lat = opp.latency_ms
        if lat is not None and math.isfinite(lat) and lat >= 0.0:
            self._detect_lat.append(float(lat))

        # Desglose del embudo por estrategia (cuenta el estado final del tick).
        strat = self._by_strategy.get(opp.strategy.value)
        if strat is not None:
            strat[opp.status.value] += 1
        if opp.discard_reason is not None:
            self._discard_reasons[opp.discard_reason.value] += 1

        # Microestructura del EVALUADOR (C6): effective bruto y expected_net modelado, EMPAREJADOS
        # en la misma muestra → impact = eff-expected_net consistente. Se exige `net_pnl` presente
        # y finito para AMBAS (si falta, se descarta la opp de las dos ventanas: sin neto no hay
        # coste medible y emparejar evita el sesgo de poblaciones distintas).
        q = opp.q_target
        vb, vs, net = opp.vwap_buy, opp.vwap_sell, opp.net_pnl
        if (
            vb is not None and vs is not None and net is not None and q > 0
            and math.isfinite(vb) and math.isfinite(vs) and math.isfinite(net)
        ):
            eff = vs - vb
            expected_net = net / q
            self._eff_spread.append(eff)
            self._expected_net.append(expected_net)
            self._modeled_impact.append(eff - expected_net)

        # Opportunity lifetime: duración continua del cruce dirigido. Reloj monotónico de
        # detección (t_detect); sin él no se mide (honesto). Antes de tocar el cruce actual,
        # CIERRA por timeout los episodios cuyo último avistamiento quedó más viejo que el gap
        # (su cruce desapareció) — esto da la semántica correcta de "lifetime = mientras el
        # cruce está vivo" y ACOTA `_open` (evita fuga de memoria con muchos cruces dirigidos).
        now = opp.t_detect
        if now is not None and math.isfinite(now):
            self._expire_stale(now)
            key = (opp.strategy.value, opp.buy_venue, opp.sell_venue)
            ep = self._open.get(key)
            delta = (now - ep[1]) if ep is not None else None
            if ep is not None and delta is not None and 0.0 <= delta <= self._lifetime_gap:
                self._open[key] = (ep[0], now)  # extiende el episodio vivo (sólo hacia adelante)
            else:
                if ep is not None:
                    self._close_episode(ep)  # gap, o t_detect retrocedió → cierra y reabre
                self._open[key] = (now, now)

    def _expire_stale(self, now: float) -> None:
        """Cierra (y registra) los episodios abiertos cuyo cruce no se ve hace > gap."""
        stale = [k for k, (_, last) in self._open.items() if now - last > self._lifetime_gap]
        for k in stale:
            self._close_episode(self._open.pop(k))

    def record_execution(self, ex: Execution) -> None:
        """Registra una ejecución CAPTURADA: latencia de ejecución + fill ratio + realized REAL."""
        el = ex.exec_latency_ms
        if el is not None and el >= 0:
            self._exec_lat.append(float(el))
        # fill ratio = matched / objetivo (q_requested, igual en ambas patas). Sin objetivo → no.
        req = max((leg.qty_requested for leg in ex.legs), default=0.0)
        if req > 0 and ex.matched_qty >= 0:
            self._fill_ratio.append(min(1.0, ex.matched_qty / req))
        # realized REAL por BTC casado: incluye fills parciales, leg risk y pérdidas de unwind.
        if ex.matched_qty > 0 and math.isfinite(ex.realized_pnl):
            self._realized_spread.append(ex.realized_pnl / ex.matched_qty)

    def record_preflight(self, venue: str, result: str) -> None:
        """Cuenta resultados de preflight con labels acotados para Prometheus."""
        self._preflight_results[venue.strip().lower() or "unknown"][result] += 1

    def record_test_order(self, venue: str, result: str) -> None:
        """Cuenta resultados de test-order con labels acotados para Prometheus."""
        self._test_order_results[venue.strip().lower() or "unknown"][result] += 1

    def _close_episode(self, ep: tuple[float, float]) -> None:
        dur_ms = (ep[1] - ep[0]) * 1000.0
        if dur_ms >= 0.0 and dur_ms == dur_ms:
            self._lifetime_ms.append(dur_ms)

    # ---- Lectura ----

    def _lifetime_samples(self) -> list[float]:
        """Episodios cerrados + los abiertos vigentes (su duración acumulada hasta ahora).
        Filtra duraciones negativas (defensa ante `last < first` por t_detect retrocedido)."""
        out = list(self._lifetime_ms)
        out.extend(
            (last - first) * 1000.0
            for first, last in self._open.values()
            if last >= first
        )
        return out

    def _stage(self, name: str, window: deque[float]) -> StageLatency | None:
        if not window:
            return None
        s = list(window)
        return StageLatency(
            stage=name,
            count=len(s),
            p50_ms=_percentile(s, 50),
            p99_ms=_percentile(s, 99),
            max_ms=max(s),
        )

    @staticmethod
    def _mean(window: deque[float]) -> float | None:
        return sum(window) / len(window) if window else None

    def detect_p50_p99(self) -> tuple[float, float]:
        """(p50, p99) de la latencia de detección en ms para logging (0.0 si no hay muestra)."""
        s = list(self._detect_lat)
        return (_percentile(s, 50) or 0.0, _percentile(s, 99) or 0.0)

    def discard_reasons(self) -> dict[str, int]:
        """Desglose acumulado de descartes por motivo (para logging/lectura externa)."""
        return dict(self._discard_reasons)

    def snapshot(self, funnel: dict[str, int]) -> MetricsSnapshot:
        """Construye el snapshot. `funnel` es la fuente única `AppState.opp_counts`
        (conteos acumulados del embudo); aquí sólo se añaden latencia/microestructura/
        desgloses calculados sobre las ventanas."""
        detected = funnel.get(OpportunityStatus.detected.value, 0)
        captured = funnel.get(OpportunityStatus.captured.value, 0)

        eff = self._mean(self._eff_spread)
        expected_net = self._mean(self._expected_net)
        # impact = media de (eff-expected_net) emparejado por muestra (no resta de medias).
        impact = self._mean(self._modeled_impact)
        realized = self._mean(self._realized_spread)  # REAL, desde ejecuciones capturadas
        detect_stage = self._stage("detect", self._detect_lat)

        life = self._lifetime_samples()
        hist = [0] * (len(_LIFETIME_BUCKETS_MS) + 1)
        for v in life:
            placed = False
            for i, edge in enumerate(_LIFETIME_BUCKETS_MS):
                if v <= edge:
                    hist[i] += 1
                    placed = True
                    break
            if not placed:
                hist[-1] += 1

        return MetricsSnapshot(
            window="session",
            n_samples=len(self._eff_spread),
            detected=detected,
            viable=funnel.get(OpportunityStatus.viable.value, 0),
            executable=funnel.get(OpportunityStatus.executable.value, 0),
            captured=captured,
            discarded=funnel.get(OpportunityStatus.discarded.value, 0),
            unwound=funnel.get("unwound", 0),
            discard_reasons=dict(self._discard_reasons),
            by_strategy={k: dict(v) for k, v in self._by_strategy.items() if v},
            preflight_results={k: dict(v) for k, v in self._preflight_results.items()},
            test_order_results={k: dict(v) for k, v in self._test_order_results.items()},
            detect_latency=detect_stage,
            exec_latency=self._stage("exec", self._exec_lat),
            p50_ms=detect_stage.p50_ms if detect_stage else None,
            p99_ms=detect_stage.p99_ms if detect_stage else None,
            effective_spread=eff,
            expected_net_spread=expected_net,
            realized_spread=realized,
            price_impact=impact,
            capture_ratio=(captured / detected) if detected > 0 else None,
            fill_ratio=self._mean(self._fill_ratio),
            opp_lifetime_hist=hist,
            opp_lifetime_buckets_ms=list(_LIFETIME_BUCKETS_MS),
            opp_lifetime_p50_ms=_percentile(life, 50),
            opp_lifetime_p99_ms=_percentile(life, 99),
        )
