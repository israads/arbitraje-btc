"""C14 — Replay cronológico point-in-time + métricas (FR-014 AC#2/3/4, STORY-021).

Reproduce una grabación de `NormalizedBook` por el MISMO motor/simulador que el camino vivo
(NO una ruta paralela — AC#3): `SpatialDetector` (C5) + `StatZDetector` (C5) + `NetEvaluator`
(C6) + `Prioritizer` (C7) + `ExecutionSimulator` (C9) + `Portfolio` (C10). Cada componente es
una instancia FRESCA (no toca el estado vivo).

POINT-IN-TIME (AC#2): los ticks se procesan en orden cronológico ascendente; en el instante
`t` la DECISIÓN (detección/evaluación/ranking) ve SÓLO libros con ts ≤ t (los que `detector.books`
acumuló). No hay look-ahead en la decisión.

LATENCIA / LEG RISK REAL (la razón de ser del backtest, memoria del proyecto): al simular una
opp decidida en `t`, el leg2 (venta) se RE-LEE en `t + exec_latency_ms` usando el SIGUIENTE
tick GRABADO del venue de venta cuyo ts ≥ t+Δ (`sell_book_t1`). Eso NO es look-ahead ilícito:
la decisión es a `t` (sólo datos ≤ t) y el FILL del leg2 ocurre realmente más tarde, al precio
que de verdad existía en `t+Δ`. Así el simulador (C9, STORY-016) ejerce de verdad el camino de
re-lectura → fills parciales / UNWIND con pérdida real, que en vivo nunca se dispara (en vivo
detecta→simula sobre el MISMO snapshot, sin desfase). El jurado VE unwinds en la demo del backtest.

MÉTRICAS (AC#4): Sharpe (por trade, no anualizado), win rate, profit/trade, max drawdown y
profit factor; con separación in-sample / out-of-sample (tramos cronológicos reproducidos por
separado, cada uno con CARTERA fresca → P&L independiente). El tramo out-of-sample se CALIENTA
con los ticks del in-sample (sin tradear) para que la ventana del z-score (W) y los books NO
arranquen en frío en el split — así el backtest del tramo out-of-sample refleja lo que el
sistema haría a partir de ahí (de otro modo las primeras ~W obs/par no generarían señales
stat_z y la métrica de generalización quedaría sesgada).

ALCANCE (honesto, alineado con AC#3 que enumera FR-005/008/009): el replay reusa el MOTOR DE
EJECUCIÓN — detección (C5), neto (C6), priorización (C7), simulación con leg risk (C9), cartera
(C10). NO aplica las capas OPERATIVAS vivas: circuit breakers (C8/FR-012) ni rebalanceo
periódico (C10/FR-011, su coste on-chain). El backtest mide el EDGE de la estrategia sobre los
datos grabados, no los halts de seguridad ni el coste de mantenimiento del inventario; por eso
sus métricas son una COTA SUPERIOR de la actividad (sin breakers que detengan ni coste de
rebalanceo que reste). Es una separación deliberada estrategia/overlay-operativo.

Determinista: sin red ni reloj; el `ts` de cada `Execution` se toma del tick (`ts_recv_monotonic`).
"""
from __future__ import annotations

import math
from bisect import bisect_left
from collections import defaultdict

import numpy as np

from ..config import Settings
from ..engine import NetEvaluator, Prioritizer, SpatialDetector, StatZDetector
from ..models.backtest import BacktestResult, SegmentMetrics
from ..models.enums import DiscardReason, OpportunityStatus
from ..models.market import NormalizedBook
from ..sim import ExecutionSimulator, Portfolio


def _compute_metrics(
    trades: list[float],
    equity_curve: list[float],
    *,
    n_ticks: int,
    n_unwinds: int,
    n_viable: int,
    n_detected: int,
) -> SegmentMetrics:
    """Calcula las métricas de un tramo a partir del P&L realizado por trade y la curva de
    P&L acumulado. Robusto a tramos sin trades (devuelve los campos derivados en None/0)."""
    n_trades = len(trades)
    realized_total = float(sum(trades)) if trades else 0.0

    profit_per_trade: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    sharpe: float | None = None

    if n_trades > 0:
        profit_per_trade = realized_total / n_trades
        wins = sum(1 for t in trades if t > 0.0)
        win_rate = wins / n_trades
        gains = sum(t for t in trades if t > 0.0)
        losses = -sum(t for t in trades if t < 0.0)  # magnitud positiva
        # profit_factor indefinido sin trades perdedores (no se divide por 0): None + honesto.
        profit_factor = (gains / losses) if losses > 0.0 else None

    if n_trades >= 2:
        arr = np.array(trades, dtype=float)
        std = float(arr.std(ddof=1))  # desviación muestral del P&L por trade
        if math.isfinite(std) and std > 0.0:
            sharpe = float(arr.mean()) / std

    # Max drawdown: mayor caída pico→valle de la curva de P&L realizado ACUMULADO.
    max_dd = 0.0
    peak = 0.0  # arranca en 0 (P&L acumulado parte de 0 antes del primer trade)
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd

    return SegmentMetrics(
        n_ticks=n_ticks,
        n_trades=n_trades,
        n_unwinds=n_unwinds,
        n_viable=n_viable,
        n_detected=n_detected,
        realized_pnl_total=realized_total,
        profit_per_trade=profit_per_trade,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown_usd=max_dd,
        sharpe=sharpe,
        equity_curve=equity_curve,
    )


def _replay_segment(
    ticks: list[NormalizedBook],
    settings: Settings,
    *,
    warmup: list[NormalizedBook] | None = None,
) -> SegmentMetrics:
    """Reproduce un tramo cronológico por el motor/simulador fresco y devuelve sus métricas.

    `ticks` debe venir ordenado por `ts_recv_monotonic` ascendente. Reusa el pipeline completo
    (detección espacial + z-score → neto → ranking → gate de capital → simulación con leg risk).

    `warmup` (opcional): ticks PREVIOS al tramo que se alimentan al detector/stat SIN tradear,
    sólo para calentar la ventana del z-score y los books (el tramo no arranca en frío). NO
    cuentan en `n_ticks` ni generan trades; la cartera arranca fresca igual."""
    if not ticks:
        return SegmentMetrics(n_ticks=0)

    detector = SpatialDetector(settings)
    stat = StatZDetector(settings)
    evaluator = NetEvaluator(settings)
    prioritizer = Prioritizer(settings)
    sim = ExecutionSimulator(settings)
    pf = Portfolio(settings)

    # Warm-up: calienta detector.books y la ventana del z-score con el tramo previo (sin tradear).
    if warmup:
        for nb in warmup:
            wnow = nb.ts_recv_monotonic
            detector.on_book(nb, now=wnow)
            stat.on_book(nb, detector.books, now=wnow)

    # Índice de ticks FUTUROS por venue (para sell_book_t1 vía bisect O(log n)).
    venue_ts: dict[str, list[float]] = defaultdict(list)
    venue_books: dict[str, list[NormalizedBook]] = defaultdict(list)
    for nb in ticks:
        venue_ts[nb.exchange].append(nb.ts_recv_monotonic)
        venue_books[nb.exchange].append(nb)

    latency_s = settings.exec_latency_ms / 1000.0

    def future_sell_book(venue: str, t: float) -> NormalizedBook | None:
        """Primer tick GRABADO del `venue` con ts ≥ t+latencia (el book del leg2 en t+Δ).
        None si el venue no vuelve a actualizarse: el simulador cae a STORY-009 (sin reread,
        sin unwind espurio)."""
        arr = venue_ts.get(venue)
        if not arr:
            return None
        idx = bisect_left(arr, t + latency_s)
        if idx >= len(arr):
            return None
        return venue_books[venue][idx]

    trades: list[float] = []
    equity_curve: list[float] = []
    n_unwinds = 0
    n_viable = 0
    n_detected = 0

    for nb in ticks:
        # `now`=ts del tick → staleness/latencia point-in-time contra el reloj GRABADO.
        now = nb.ts_recv_monotonic
        opps = [*detector.on_book(nb, now=now), *stat.on_book(nb, detector.books, now=now)]
        for opp in opps:
            bb = detector.books.get(opp.buy_venue)
            sb = detector.books.get(opp.sell_venue)
            if bb is not None and sb is not None:
                evaluator.evaluate(opp, bb, sb)
        opps = prioritizer.rank(opps)  # C7: viables por score desc
        for opp in opps:
            n_detected += 1
            if opp.status is not OpportunityStatus.viable:
                continue
            n_viable += 1
            # C7 gate de capital/inventario (mismo que on_opp en vivo).
            if not pf.can_afford(opp):
                opp.status = OpportunityStatus.discarded
                opp.discard_reason = DiscardReason.insufficient_balance
                continue
            bb = detector.books.get(opp.buy_venue)
            sb = detector.books.get(opp.sell_venue)
            if bb is None or sb is None:
                continue
            # C9: re-lectura del leg2 en t+Δ con el tick futuro real del venue de venta.
            sb_t1 = future_sell_book(opp.sell_venue, nb.ts_recv_monotonic)
            execution = sim.simulate(opp, bb, sb, sell_book_t1=sb_t1, ts=nb.ts_recv_monotonic)
            if execution is None:
                continue  # descarte pre-trade por slippage (gate del simulador)
            pf.apply_execution(execution)  # sanea internamente: sólo suma realized si es finito
            # Guard de finitud: un realized_pnl NaN/inf (book corrupto) NO debe envenenar las
            # métricas (Sharpe ya se protege, pero el drawdown con NaN quedaría en 0 silencioso).
            pnl = execution.realized_pnl if math.isfinite(execution.realized_pnl) else 0.0
            trades.append(pnl)
            if execution.unwound:
                n_unwinds += 1
            equity_curve.append(pf.realized_pnl)

    return _compute_metrics(
        trades, equity_curve,
        n_ticks=len(ticks), n_unwinds=n_unwinds, n_viable=n_viable, n_detected=n_detected,
    )


def run_backtest(
    ticks: list[NormalizedBook],
    settings: Settings,
    *,
    in_sample_frac: float | None = None,
) -> BacktestResult:
    """Reproduce una grabación completa y devuelve el resultado global + in/out-of-sample.

    Los tramos in-sample y out-of-sample se reproducen por SEPARADO (cartera fresca cada uno)
    para una evaluación de generalización honesta. El tramo global se reproduce sobre todo el
    flujo. Todos usan el MISMO motor/simulador (AC#3). Vacío → resultado con métricas nulas."""
    frac = in_sample_frac if in_sample_frac is not None else settings.backtest_in_sample_frac
    # Acota el split a (0,1) por robustez (el caller puede pasar valores fuera de rango).
    frac = min(0.99, max(0.01, frac))

    # Filtra ticks con ts no finito (book corrupto): un NaN rompería el orden de `sorted` y, con
    # él, el bisect de `future_sell_book` (selección de sell_book_t1) de forma silenciosa.
    finite = [nb for nb in ticks if math.isfinite(nb.ts_recv_monotonic)]
    ordered = sorted(finite, key=lambda nb: nb.ts_recv_monotonic)
    n = len(ordered)
    split = int(frac * n)

    overall = _replay_segment(ordered, settings)
    in_sample = _replay_segment(ordered[:split], settings)
    # out-of-sample se CALIENTA con el in-sample (sin tradear) para no arrancar en frío la
    # ventana del z-score → métrica de generalización fiel (cartera fresca igual).
    out_of_sample = _replay_segment(ordered[split:], settings, warmup=ordered[:split])

    return BacktestResult(
        n_ticks_total=n,
        in_sample_frac=frac,
        overall=overall,
        in_sample=in_sample,
        out_of_sample=out_of_sample,
    )
