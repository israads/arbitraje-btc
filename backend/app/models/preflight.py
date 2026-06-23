"""Modelos de ejecución protegida/testnet (PRD-003).

La API expone sólo payloads saneados y checks auditables. No hay secretos, firmas ni headers
privados en estos modelos.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ExecutionMode = Literal["disabled", "dry_run", "testnet"]
OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]


class PreflightCheck(BaseModel):
    name: str
    passed: bool
    detail: str | None = None


class PreflightRequest(BaseModel):
    opportunity_id: str | None = None
    venue: str
    side: OrderSide
    symbol: str = "BTCUSDT"
    quantity_btc: float = Field(gt=0.0)
    order_type: OrderType = "market"
    limit_price: float | None = Field(default=None, gt=0.0)
    # Precio usado para validar minNotional de órdenes MARKET. El endpoint puede rellenarlo
    # desde la oportunidad o el book actual; también se acepta en body para pruebas/dry-run.
    reference_price: float | None = Field(default=None, gt=0.0)


class TestOrderRequest(PreflightRequest):
    pass


class PreflightResult(BaseModel):
    mode: ExecutionMode
    accepted: bool
    venue: str
    symbol: str
    checks: list[PreflightCheck]
    sanitized_order: dict[str, Any] = Field(default_factory=dict)


class TestOrderResult(BaseModel):
    mode: ExecutionMode
    accepted: bool
    venue: str
    symbol: str
    status: Literal["accepted_test", "rejected_test", "failed"]
    checks: list[PreflightCheck]
    submitted_order: dict[str, Any] = Field(default_factory=dict)
    exchange_response: dict[str, Any] = Field(default_factory=dict)


class ExecutionStatus(BaseModel):
    mode: ExecutionMode
    enabled: bool
    test_orders_enabled: bool
    supported_venues: list[str]
    credentials_configured: dict[str, bool]
    notes: list[str] = Field(default_factory=list)
