"""Modelos de parametrizacion runtime/what-if para la fase final.

Estos contratos son deliberadamente seguros: los overrides sirven para recalcular escenarios
what-if y proyecciones sin tocar ejecucion real. Aplicar al motor vivo queda separado y protegido.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RuntimeParamOverrides(BaseModel):
    default_trade_qty_btc: float | None = Field(default=None, gt=0.0)
    max_slippage: float | None = Field(default=None, ge=0.0)
    min_net_profit_usd: float | None = None
    exec_latency_ms: int | None = Field(default=None, ge=1)
    expected_trades_per_rebalance: float | None = Field(default=None, gt=0.0)
    peg_tolerance: float | None = Field(default=None, ge=0.0)
    z_open: float | None = None
    z_close: float | None = None
    z_stop: float | None = None
    inventory_skew_limit: float | None = Field(default=None, ge=0.0)
    fee_bps: float | None = Field(default=None, ge=0.0)
    n_paths: int | None = Field(default=None, ge=100, le=20_000)
    enabled_exchange_overrides: dict[str, bool] = Field(default_factory=dict)


class WhatIfRequest(BaseModel):
    size_btc: float | None = Field(default=None, gt=0.0)
    fee_bps: float | None = Field(default=None, ge=0.0)
    fee_buy_bps: float | None = Field(default=None, ge=0.0)
    fee_sell_bps: float | None = Field(default=None, ge=0.0)
    latency_ms: int | None = Field(default=None, ge=1)
    max_slippage: float | None = Field(default=None, ge=0.0)
    min_net_profit_usd: float | None = None
    expected_trades_per_rebalance: float | None = Field(default=None, gt=0.0)
