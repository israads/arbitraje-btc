"""Resultado del backtest (C14, FR-014): métricas por segmento + in/out-of-sample.

`SegmentMetrics` es el set de métricas de un tramo de la grabación reproducido; `BacktestResult`
agrupa el tramo global + in-sample + out-of-sample (separación para evaluar generalización).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SegmentMetrics(BaseModel):
    """Métricas de un tramo reproducido por el MISMO motor/simulador (FR-014 AC#4).

    Convenciones (honestas, documentadas):
      · `sharpe` = media/desv. del P&L realizado POR TRADE (no anualizado; None si <2 trades
        o desviación nula).
      · `max_drawdown_usd` = mayor caída pico→valle de la curva de P&L realizado ACUMULADO.
      · `profit_factor` = Σ ganancias / |Σ pérdidas| (None si no hubo trades perdedores).
      · `win_rate` = fracción de trades con P&L realizado > 0.
    """

    n_ticks: int = 0
    n_trades: int = 0          # ejecuciones simuladas (capturas), incluye unwinds
    n_unwinds: int = 0         # subconjunto de trades que acabaron en UNWIND (leg risk, STORY-016)
    n_viable: int = 0
    n_detected: int = 0
    realized_pnl_total: float = 0.0
    profit_per_trade: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    max_drawdown_usd: float = 0.0
    sharpe: float | None = None
    # Curva de P&L realizado acumulado (para la equity curve del dashboard, STORY-023).
    equity_curve: list[float] = Field(default_factory=list)


class BacktestResult(BaseModel):
    """Resultado completo de un replay: tramo global + in-sample + out-of-sample."""

    n_ticks_total: int = 0
    in_sample_frac: float = 0.7
    ts: float = 0.0  # sello (epoch) inyectado por el endpoint; los cómputos no leen reloj
    overall: SegmentMetrics = Field(default_factory=SegmentMetrics)
    in_sample: SegmentMetrics = Field(default_factory=SegmentMetrics)
    out_of_sample: SegmentMetrics = Field(default_factory=SegmentMetrics)
