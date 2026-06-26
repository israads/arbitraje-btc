"""Modelos de analisis agregado de sesion.

`NaiveVsEdgeReport` contrasta lo que un detector de spreads ingenuo contaria como ganancia
contra el neto que el motor realmente captura tras costes, y atribuye la fuga a razones de
descarte. No recalcula economia: agrega sobre oportunidades ya evaluadas.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RejectionBucket(BaseModel):
    reason: str
    label: str
    count: int
    lost_gross_usd: float


class NaiveVsEdgeReport(BaseModel):
    sample_size: int = 0
    naive_trades: int = 0
    naive_gross_usd: float = 0.0
    naive_gross_per_btc: float | None = None
    engine_trades: int = 0
    engine_net_usd: float = 0.0
    engine_net_per_btc: float | None = None
    naive_q_btc: float = 0.0
    engine_q_btc: float = 0.0
    overstatement_usd: float = 0.0
    survival_rate: float | None = None
    rejections: list[RejectionBucket] = Field(default_factory=list)
    dominant_rejection: str | None = None
    headline: str = ""
