"""Modelos pydantic compartidos (data model de la arquitectura)."""
from __future__ import annotations

from .account import Balance, InventorySnapshot
from .calibration import (
    ShadowOpportunitySample,
    SurvivalCalibrationBucket,
    SurvivalCalibrationReport,
    SurvivalObservation,
)
from .enums import (
    BreakerType,
    ConnectionStatus,
    DiscardReason,
    LegSide,
    OpportunityStatus,
    Strategy,
)
from .events import StreamEvent
from .execution import Execution, Leg
from .explain import (
    CostComponent,
    EngineDecision,
    NaiveComparison,
    OpportunityExplanation,
    OpportunityRoute,
)
from .market import NormalizedBook, PegRate, PriceLevel, Quote, RawOrderBook
from .metrics import MetricsSnapshot
from .opportunity import Opportunity
from .preflight import (
    ExecutionStatus,
    PreflightCheck,
    PreflightRequest,
    PreflightResult,
    TestOrderRequest,
    TestOrderResult,
)
from .risk import CircuitBreakerState
from .session import SessionExport, SessionMetadata
from .strategy import (
    FundingOpportunity,
    FundingRate,
    OpportunityLeg,
    RegionalMXNOpportunity,
    StrategyExplanation,
    StrategyInfo,
    StrategyRisk,
)

__all__ = [
    "Balance",
    "InventorySnapshot",
    "ShadowOpportunitySample",
    "SurvivalCalibrationBucket",
    "SurvivalCalibrationReport",
    "SurvivalObservation",
    "BreakerType",
    "ConnectionStatus",
    "DiscardReason",
    "LegSide",
    "OpportunityStatus",
    "Strategy",
    "StreamEvent",
    "Execution",
    "Leg",
    "CostComponent",
    "EngineDecision",
    "NaiveComparison",
    "OpportunityExplanation",
    "OpportunityRoute",
    "NormalizedBook",
    "PegRate",
    "PriceLevel",
    "Quote",
    "RawOrderBook",
    "MetricsSnapshot",
    "Opportunity",
    "ExecutionStatus",
    "PreflightCheck",
    "PreflightRequest",
    "PreflightResult",
    "TestOrderRequest",
    "TestOrderResult",
    "CircuitBreakerState",
    "SessionExport",
    "SessionMetadata",
    "FundingOpportunity",
    "FundingRate",
    "OpportunityLeg",
    "RegionalMXNOpportunity",
    "StrategyExplanation",
    "StrategyInfo",
    "StrategyRisk",
]
