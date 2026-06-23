"""Explicación auditable de una oportunidad (PRD-001).

La explicación es una capa de presentación: recibe el resultado económico ya calculado
por `ExecutionCostModel` y lo traduce a un contrato JSON. No decide, no hace I/O y no
recalcula el neto por su cuenta.
"""
from __future__ import annotations

import math

from ..config import Settings
from ..models.enums import OpportunityStatus
from ..models.explain import (
    CostComponent,
    EngineDecision,
    NaiveComparison,
    OpportunityExplanation,
    OpportunityRoute,
)
from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity
from .cost_model import NetBreakdown


def _finite(x: float | None) -> float | None:
    return x if x is not None and math.isfinite(x) else None


def _per_btc(usd: float | None, q: float) -> float | None:
    return usd / q if usd is not None and q > 0.0 and math.isfinite(usd) else None


def build_opportunity_explanation(
    opp: Opportunity,
    buy_book: NormalizedBook,
    sell_book: NormalizedBook,
    settings: Settings,
    *,
    breakdown: NetBreakdown | None = None,
) -> OpportunityExplanation:
    """Construye la explicación de `opp` contra los books usados por el evaluador.

    `breakdown` debe venir de `compute_net`. Si no existe (descartes tempranos como
    peg/thin book), se devuelve una explicación parcial que conserva naive comparison,
    decisión y timestamps.
    """
    q = opp.q_target if opp.q_target > 0.0 else settings.default_trade_qty_btc
    best_ask = _finite(buy_book.best_ask)
    best_bid = _finite(sell_book.best_bid)
    spread = (best_bid - best_ask) if best_ask is not None and best_bid is not None else None
    naive_gross = spread * q if spread is not None and q > 0.0 else None

    net = _finite(opp.net_pnl)
    if breakdown is not None and net is None:
        net = breakdown.net
    net_q = opp.q_target if opp.q_target > 0.0 else breakdown.filled if breakdown else q
    net_per_btc = _per_btc(net, net_q)

    components: list[CostComponent] = []
    dominant = None
    if breakdown is not None and breakdown.filled > 0.0:
        filled = breakdown.filled
        dominant = breakdown.dominant_cost
        components = [
            CostComponent(
                key="gross",
                label="Gross spread",
                usd=breakdown.gross,
                per_btc=_per_btc(breakdown.gross, filled),
            ),
            CostComponent(
                key="fees_buy",
                label="Buy fee",
                usd=-breakdown.fees_buy,
                per_btc=_per_btc(-breakdown.fees_buy, filled),
            ),
            CostComponent(
                key="fees_sell",
                label="Sell fee",
                usd=-breakdown.fees_sell,
                per_btc=_per_btc(-breakdown.fees_sell, filled),
            ),
            CostComponent(
                key="slippage",
                label="Depth slippage",
                usd=-breakdown.slippage_cost,
                per_btc=_per_btc(-breakdown.slippage_cost, filled),
            ),
            CostComponent(
                key="rebalance",
                label="Rebalance",
                usd=-breakdown.rebalance,
                per_btc=_per_btc(-breakdown.rebalance, filled),
            ),
            CostComponent(
                key="net",
                label="Engine net",
                usd=breakdown.net,
                per_btc=breakdown.net_per_btc,
            ),
        ]

    notes: list[str] = []
    if breakdown is None:
        notes.append("partial_explanation")
    if spread is not None and spread > 0.0 and opp.status is OpportunityStatus.discarded:
        notes.append("naive_positive_engine_rejected")
    if buy_book.price_norm_factor != 1.0 or sell_book.price_norm_factor != 1.0:
        notes.append("cross_stablecoin_or_peg_adjusted")

    peg_delta = max(abs(buy_book.price_norm_factor - 1.0), abs(sell_book.price_norm_factor - 1.0))

    return OpportunityExplanation(
        id=opp.id,
        route=OpportunityRoute(
            symbol=opp.symbol,
            buy_venue=opp.buy_venue,
            sell_venue=opp.sell_venue,
        ),
        q_target=opp.q_target,
        naive=NaiveComparison(
            buy_price=best_ask,
            sell_price=best_bid,
            spread_usd_per_btc=spread,
            gross_usd=naive_gross,
            would_trade=bool(spread is not None and spread > 0.0 and q > 0.0),
        ),
        engine=EngineDecision(
            status=opp.status.value,
            reason=opp.discard_reason.value if opp.discard_reason is not None else None,
            net_usd=net,
            net_per_btc=net_per_btc,
            dominant_cost=dominant,
            trades=opp.status in {
                OpportunityStatus.viable,
                OpportunityStatus.executable,
                OpportunityStatus.captured,
            },
        ),
        breakdown=components,
        peg={
            "buy_quote": buy_book.quote_ccy,
            "sell_quote": sell_book.quote_ccy,
            "buy_factor": buy_book.price_norm_factor,
            "sell_factor": sell_book.price_norm_factor,
            "peg_adverse_bps": peg_delta * 10_000.0,
        },
        timestamps={
            "t_recv": opp.t_recv,
            "t_detect": opp.t_detect,
            "buy_ts_exchange": buy_book.ts_exchange,
            "sell_ts_exchange": sell_book.ts_exchange,
        },
        notes=notes,
    )
