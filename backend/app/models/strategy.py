"""Modelos comunes para módulos de estrategia (PRD-008).

Las extensiones triangular/funding/MXN no comparten exactamente el contrato económico del
arbitraje spot cross-exchange. Estos modelos permiten etiquetar legs, riesgos y payloads sin
forzar todo al par `buy_venue`/`sell_venue` del flujo principal.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class OpportunityLeg(BaseModel):
    """Leg genérico de una oportunidad multi-pata.

    `qty_in`/`qty_out` están en `asset_in`/`asset_out`; `fee` está expresada en la moneda de
    salida del leg para no inventar una conversión USD cuando la estrategia no la tiene.
    """

    venue: str
    symbol: str
    side: Literal["buy", "sell", "funding", "fx"]
    asset_in: str
    asset_out: str
    qty_in: float
    qty_out: float
    price: float | None = None
    fee: float = 0.0
    fee_rate: float = 0.0


class StrategyRisk(BaseModel):
    key: str
    label: str
    severity: Literal["low", "medium", "high"]
    detail: str


class StrategyExplanation(BaseModel):
    strategy: str
    opportunity_id: str
    title: str
    summary: str
    legs: list[OpportunityLeg] = Field(default_factory=list)
    metrics: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    risks: list[StrategyRisk] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class StrategyInfo(BaseModel):
    id: str
    enabled: bool
    mode: Literal["primary", "adapter", "demo_replay", "read_only", "experimental"]
    description: str


class FundingRate(BaseModel):
    venue: str
    symbol: str
    rate: float
    next_funding_ts: float
    mark_price: float
    index_price: float | None = None


class FundingOpportunity(BaseModel):
    strategy: str = "funding_basis"
    spot_venue: str
    perp_venue: str
    symbol: str
    spot_mid: float
    mark_price: float
    index_price: float | None = None
    basis_bps: float
    funding_apr: float
    hedge_cost_bps: float
    expected_carry_apr: float
    horizon_hours: float
    risk: str


class RegionalMXNOpportunity(BaseModel):
    strategy: str = "regional_mxn"
    mxn_venue: str
    usd_venue: str
    symbol_mxn: str
    symbol_usd: str
    btc_mxn_mid: float
    btc_usd_mid: float
    usd_mxn: float
    btc_mxn_as_usd: float
    gross_spread_usd: float
    gross_spread_bps: float
    fiat_fee_bps: float
    net_spread_bps: float
    risk: str
