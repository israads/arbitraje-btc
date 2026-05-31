"""Inventario y balances pre-posicionados (C10). Invariante de conservación."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Balance(BaseModel):
    exchange: str
    asset: str       # BTC | USDT | USD
    amount: float


class InventorySnapshot(BaseModel):
    ts: float
    balances: list[Balance] = Field(default_factory=list)
    total_usd: float | None = None
