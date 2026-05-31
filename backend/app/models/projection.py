"""Modelos de la Projection Suite v2 (capturabilidad · capacidad · forward).

Contrato estable para `GET /api/v1/projection|capacity|forward` y el evento SSE `projection`.
Todo determinista y serializable; las matrices `[fee_tier][size]` mantienen compatibilidad con
el dashboard actual (`matrix` = net USD/BTC) y añaden capas (net USD, P_survive, edge esperado,
coste dominante).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class FeeTier(BaseModel):
    label: str
    bps: float


# --- Capa 1: Frontier (capturabilidad) ---------------------------------------------------

class FrontierBestCell(BaseModel):
    """Una celda destacada (un óptimo) de la frontier."""

    size_btc: float
    fee_bps: float
    net_per_btc: float
    net_usd: float
    expected_edge_usd: float | None = None
    p_survive: float | None = None


class FrontierBest(BaseModel):
    """Tres óptimos distintos (F3): por edge unitario, por edge total esperado y ajustado a riesgo.

    Maximizar USD/BTC puede elegir una celda diminuta; por eso se exponen los tres."""

    by_unit_edge: FrontierBestCell | None = None
    by_total_edge: FrontierBestCell | None = None
    by_risk_adjusted: FrontierBestCell | None = None


class FrontierResult(BaseModel):
    """Break-even Frontier v2. Matrices alineadas `[fee_tier][size]`."""

    mode: str                                            # demo | live
    route: dict[str, str] | None = None                 # {buy, sell, symbol} en modo live
    asof_monotonic: float | None = None
    sizes_btc: list[float]
    fee_tiers: list[FeeTier]
    matrix: list[list[float | None]]                     # net USD/BTC (compat dashboard)
    net_usd: list[list[float | None]]                    # net total USD
    p_survive: list[list[float | None]]                  # prob. de sobrevivir hasta ejecución
    expected_edge: list[list[float | None]]              # Expected Capturable Edge (USD)
    depth_limited: list[list[bool]]
    dominant_cost: list[list[str]]                       # fees | slippage | rebalance | none
    best: FrontierBest
    gross_top_per_btc: float
    survival_model: str | None = None                    # descripción de la calibración P_survive
    notes: str = ""


# --- Capa 2: Capacity curve (escalado de capital) ----------------------------------------

class CapacityPoint(BaseModel):
    q_btc: float
    edge_total_usd: float
    edge_marginal_per_btc: float
    sqrt_impact_usd: float | None = None                 # overlay teórico (square-root law)


class CapacityResult(BaseModel):
    mode: str
    route: dict[str, str] | None = None
    fee_bps: float
    points: list[CapacityPoint] = Field(default_factory=list)
    q_star_btc: float | None = None                      # óptimo: max edge_total (marginal→0)
    q_star_edge_usd: float | None = None
    hard_capacity_btc: float | None = None               # edge_total cruza 0
    throughput_usd_per_opp: float | None = None
    notes: str = ""


# --- Capa 3: Forward (Monte Carlo + honestidad estadística) ------------------------------

class ForwardBands(BaseModel):
    """Percentiles de equity acumulada por paso (fan chart)."""

    step: list[int] = Field(default_factory=list)
    p5: list[float] = Field(default_factory=list)
    p25: list[float] = Field(default_factory=list)
    p50: list[float] = Field(default_factory=list)
    p75: list[float] = Field(default_factory=list)
    p95: list[float] = Field(default_factory=list)


class ForwardResult(BaseModel):
    """Proyección forward honesta a partir de la distribución empírica de P&L por trade."""

    available: bool                                      # False si no hay trades suficientes
    n_trades: int = 0
    n_paths: int = 0
    block_mean: float | None = None                     # longitud media de bloque (bootstrap)
    bands: ForwardBands = Field(default_factory=ForwardBands)
    terminal_p5: float | None = None
    terminal_p50: float | None = None
    terminal_p95: float | None = None
    terminal_hist: list[int] = Field(default_factory=list)   # histograma de P&L terminal
    terminal_hist_edges: list[float] = Field(default_factory=list)
    max_dd_p50: float | None = None
    max_dd_p95: float | None = None
    prob_profit: float | None = None                    # P(P&L terminal > 0)
    prob_ruin: float | None = None
    # Honestidad estadística (López de Prado).
    sharpe_per_trade: float | None = None
    psr: float | None = None                            # Probabilistic Sharpe Ratio (SR*=0)
    dsr: float | None = None                            # Deflated Sharpe Ratio
    min_trl: float | None = None                        # Minimum Track Record Length (trades)
    n_configs: int = 1                                  # K configuraciones probadas (para DSR)
    notes: str = ""
