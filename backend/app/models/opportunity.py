"""Oportunidad de arbitraje — alimenta el embudo (detected→viable→...→captured)."""
from __future__ import annotations

from pydantic import BaseModel

from .enums import DiscardReason, OpportunityStatus, Strategy


class Opportunity(BaseModel):
    id: str
    strategy: Strategy
    symbol: str
    buy_venue: str
    sell_venue: str
    q_target: float = 0.0
    vwap_buy: float | None = None
    vwap_sell: float | None = None
    fees: float | None = None
    slippage: float | None = None
    net_pnl: float | None = None
    z_score: float | None = None
    score: float | None = None
    status: OpportunityStatus = OpportunityStatus.detected
    discard_reason: DiscardReason | None = None
    t_recv: float | None = None       # monotónico (ingesta)
    t_detect: float | None = None     # monotónico (motor)
    latency_ms: float | None = None   # t_detect - t_recv
