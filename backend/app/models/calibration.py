"""Modelos para calibración de supervivencia (PRD-005)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CalibrationMode = Literal["observe_only", "report", "score", "gate"]
CalibrationConfidence = Literal["low", "medium", "high"]
FeatureValue = float | str | None


class ShadowOpportunitySample(BaseModel):
    id: str
    ts_detect: float
    strategy: str
    symbol: str
    buy_venue: str
    sell_venue: str
    q_target: float
    gross_usd: float | None = None
    net_usd: float | None = None
    net_per_btc: float | None = None
    fees_usd: float | None = None
    slippage_usd: float | None = None
    dominant_cost: str | None = None
    latency_ms: float | None = None
    book_age_buy_ms: float | None = None
    book_age_sell_ms: float | None = None
    spread_bps: float | None = None
    peg_factor_buy: float | None = None
    peg_factor_sell: float | None = None
    status: str
    discard_reason: str | None = None
    p_survive_estimated: float | None = None
    source: str = "live"
    features: dict[str, FeatureValue] = Field(default_factory=dict)


class SurvivalObservation(BaseModel):
    opportunity_id: str
    latency_ms: int
    observed: bool | None
    future_net_usd: float | None = None
    reason: str | None = None


class SurvivalCalibrationBucket(BaseModel):
    p_low: float
    p_high: float
    n: int = 0
    estimated_mid: float
    observed_rate: float | None = None
    abs_error: float | None = None
    confidence: CalibrationConfidence = "low"


class SurvivalCalibrationReport(BaseModel):
    mode: CalibrationMode
    latency_ms: int
    n_samples: int
    n_observed: int
    n_missing: int
    confidence: CalibrationConfidence
    buckets: list[SurvivalCalibrationBucket] = Field(default_factory=list)
    observations: list[SurvivalObservation] = Field(default_factory=list)
