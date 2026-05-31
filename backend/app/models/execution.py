"""Ejecución simulada y sus patas (fills). Soporta parciales y leg risk/unwind (C9).

Modela el resultado de simular una `Opportunity` viable como TAKER en ambos venues
(STORY-009): fills realistas recorriendo el book, fills parciales si la profundidad no
alcanza, y exposición de LEG RISK cuando un leg se llena más que el otro. El UNWIND real
de esa exposición es STORY-016 (Sprint 2): aquí se MODELA y EXPONE (cantidad +
mark-to-market), la API queda lista para que STORY-016 la consuma.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import DiscardReason, LegSide, OpportunityStatus


class Leg(BaseModel):
    """Pata de una ejecución (un fill por venue/lado).

    `qty_requested` es lo que se intentó ejecutar (q_target); `qty_filled` lo que el book
    permitió (taker). `qty_filled < qty_requested` ⇒ fill parcial en este leg.
    """

    venue: str
    side: LegSide
    qty_filled: float
    vwap: float
    fee: float                          # fee taker en USD del tramo llenado
    qty_requested: float = 0.0          # objetivo solicitado (para detectar parcial)

    @property
    def partial(self) -> bool:
        """`True` si este leg no se llenó del todo (profundidad insuficiente)."""
        return self.qty_filled + 1e-12 < self.qty_requested


class Execution(BaseModel):
    """Resultado de simular un trade. `realized_pnl` es el P&L NETO del tramo CASADO
    (`matched_qty`), no del leg sobre-llenado: ese excedente queda como leg risk abierto
    (cantidad + mark-to-market) pendiente de unwind (STORY-016)."""

    id: str
    opportunity_id: str
    legs: list[Leg] = Field(default_factory=list)
    matched_qty: float = 0.0           # min(filled_buy, filled_sell): tramo casado
    partial: bool = False              # algún leg con filled < requested (Qe < Q objetivo)
    unwound: bool = False              # 2ª pata no rentable → se deshizo la 1ª (STORY-016)
    # Motivo del unwind (sólo si `unwound`): por qué la 2ª pata dejó de ser rentable tras la
    # latencia — `not_profitable_fees` (el neto del tramo cayó bajo el umbral) o
    # `slippage_over_limit` (el slippage del leg2 re-leído superó `max_slippage`). None si no
    # hubo unwind. Trazabilidad para el embudo/metricas del jurado (STORY-022).
    unwind_reason: DiscardReason | None = None
    realized_pnl: float = 0.0          # P&L neto del tramo casado (o pérdida de unwind)
    # --- LEG RISK (exposición abierta; unwind = STORY-016) ---
    leg_risk_qty: float = 0.0          # |filled_buy - filled_sell|: BTC sin casar
    # NOTIONAL bruto del excedente al top-of-book contrario (best_bid si largos, best_ask
    # si cortos), NO P&L no realizado. La P&L de unwind se deriva en STORY-016 como
    # (precio_unwind - leg_risk_entry_vwap) * leg_risk_qty.
    leg_risk_mtm: float = 0.0
    # COSTE BASE del excedente: VWAP al que se llenó realmente la franja [matched, filled]
    # del leg sobre-llenado (los niveles más profundos del fill). Lo necesita STORY-016
    # para la pérdida de unwind sin re-leer libros (sin look-ahead). 0.0 si no hay leg risk.
    leg_risk_entry_vwap: float = 0.0
    leg_risk_venue: str | None = None  # venue del leg sobre-llenado (dónde queda abierto)
    # lado del excedente: buy = BTC comprado de más (largos); sell = BTC vendido de más (cortos)
    leg_risk_side: LegSide | None = None
    # --- Latencia de ejecución simulada (Apéndice D.3) ---
    exec_latency_ms: int = 0           # ventana entre patas que origina el leg risk
    status: OpportunityStatus = OpportunityStatus.captured  # estado tras simular
    ts: float | None = None
