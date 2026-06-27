"""Modelos de configuración base editable y persistible.

A diferencia de `RuntimeParamOverrides` (what-if read-only), esto SÍ cambia la configuración
base del motor: balances pre-posicionados, fees, venues habilitados y umbrales económicos. Se
persiste en la tabla `app_config` y se aplica a `Settings` al arrancar (y en caliente vía endpoint).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ExchangeOverride(BaseModel):
    """Overrides editables por venue. Todos opcionales: solo se aplican los presentes."""

    enabled: bool | None = None
    fee_taker: float | None = Field(default=None, ge=0.0, le=0.05)      # fracción (0.001 = 0.1%)
    initial_btc: float | None = Field(default=None, ge=0.0, le=1000.0)
    initial_quote: float | None = Field(default=None, ge=0.0, le=1e9)


class SimConfig(BaseModel):
    """Configuración base de la simulación. Persistida y aplicada al motor."""

    exchanges: dict[str, ExchangeOverride] = Field(default_factory=dict)
    default_trade_qty_btc: float | None = Field(default=None, gt=0.0, le=100.0)
    min_net_profit_usd: float | None = None
    max_slippage: float | None = Field(default=None, ge=0.0, le=0.05)
    exec_latency_ms: int | None = Field(default=None, ge=1, le=10_000)
