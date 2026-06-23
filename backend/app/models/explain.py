"""Modelos de explicación por oportunidad.

Contrato de PRD-001: compara el spread ingenuo contra el edge ejecutable calculado por
el motor, y descompone las fricciones principales sin duplicar la fórmula económica.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CostComponent(BaseModel):
    key: str
    label: str
    usd: float | None = None
    per_btc: float | None = None


class NaiveComparison(BaseModel):
    buy_price: float | None = None
    sell_price: float | None = None
    spread_usd_per_btc: float | None = None
    gross_usd: float | None = None
    would_trade: bool = False


class EngineDecision(BaseModel):
    status: str
    reason: str | None = None
    net_usd: float | None = None
    net_per_btc: float | None = None
    dominant_cost: str | None = None
    trades: bool = False


class OpportunityRoute(BaseModel):
    symbol: str
    buy_venue: str
    sell_venue: str


class OpportunityExplanation(BaseModel):
    id: str
    route: OpportunityRoute
    q_target: float
    naive: NaiveComparison
    engine: EngineDecision
    breakdown: list[CostComponent] = Field(default_factory=list)
    peg: dict[str, float | str | None] = Field(default_factory=dict)
    timestamps: dict[str, float | None] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

