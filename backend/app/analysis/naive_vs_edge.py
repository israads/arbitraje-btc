"""Naive-vs-edge: la tesis del motor hecha agregado de sesion.

Un detector de spreads ingenuo tradearia toda diferencia bruta positiva de precio. Este motor
camina el libro, descuenta fees, latencia y peg, y solo captura lo que sobrevive. Esta funcion
agrega ambas visiones sobre las oportunidades ya evaluadas y atribuye la fuga a razones de
descarte. Es presentacion pura: no recalcula economia ni hace I/O.
"""
from __future__ import annotations

import math
from collections.abc import Iterable

from ..config import Settings
from ..models.analysis import NaiveVsEdgeReport, RejectionBucket
from ..models.enums import DiscardReason, OpportunityStatus
from ..models.opportunity import Opportunity

# Etiquetas legibles de cada razon de descarte (en es-MX, para el panel del jurado).
_REASON_LABELS: dict[str, str] = {
    DiscardReason.not_profitable_fees.value: "No rentable tras fees",
    DiscardReason.thin_book.value: "Libro sin profundidad",
    DiscardReason.peg_adverse.value: "Peg USDT adverso",
    DiscardReason.slippage_over_limit.value: "Slippage sobre limite",
    DiscardReason.breaker_active.value: "Breaker activo",
    DiscardReason.stale_venue.value: "Venue stale",
    DiscardReason.insufficient_balance.value: "Balance insuficiente",
    DiscardReason.z_below_threshold.value: "z-score bajo umbral",
}


def _per_btc(usd: float, q: float) -> float | None:
    return usd / q if q > 0.0 and math.isfinite(usd) else None


def _naive_gross(opp: Opportunity, q: float) -> float | None:
    """Bruto que un detector de spreads contaria: (vwap_sell - vwap_buy) x q, pre-costes."""
    if opp.vwap_buy is None or opp.vwap_sell is None:
        return None
    spread = opp.vwap_sell - opp.vwap_buy
    if not math.isfinite(spread):
        return None
    return spread * q


def build_naive_vs_edge(
    opps: Iterable[Opportunity],
    settings: Settings,
) -> NaiveVsEdgeReport:
    """Agrega el contraste ingenuo-vs-motor sobre `opps` (tipicamente `recent_opps`)."""
    sample_size = 0
    naive_trades = 0
    naive_gross = 0.0
    naive_q = 0.0
    engine_trades = 0
    engine_net = 0.0
    engine_q = 0.0
    engine_overlap = 0
    buckets: dict[str, tuple[int, float]] = {}

    for opp in opps:
        sample_size += 1
        q = opp.q_target if opp.q_target > 0.0 else settings.default_trade_qty_btc
        gross = _naive_gross(opp, q)
        naive_would_trade = gross is not None and gross > 0.0

        if naive_would_trade:
            assert gross is not None
            naive_trades += 1
            naive_gross += gross
            naive_q += q

        if opp.status == OpportunityStatus.captured:
            engine_trades += 1
            engine_net += opp.net_pnl or 0.0
            engine_q += q
            if naive_would_trade:
                engine_overlap += 1  # capturadas que el ingenuo TAMBIÉN tradearía → para el ratio
        elif naive_would_trade and opp.status == OpportunityStatus.discarded:
            assert gross is not None
            reason = opp.discard_reason.value if opp.discard_reason else "unknown"
            count, lost = buckets.get(reason, (0, 0.0))
            buckets[reason] = (count + 1, lost + gross)

    rejections = [
        RejectionBucket(
            reason=reason,
            label=_REASON_LABELS.get(reason, reason),
            count=count,
            lost_gross_usd=lost,
        )
        for reason, (count, lost) in buckets.items()
    ]
    rejections.sort(key=lambda b: (b.count, b.lost_gross_usd), reverse=True)
    dominant = rejections[0].reason if rejections else None

    # Ratio honesto: de lo que el ingenuo tradearía, qué fracción captura el motor (∈ [0,1]).
    survival = engine_overlap / naive_trades if naive_trades > 0 else None
    overstatement = naive_gross - engine_net

    return NaiveVsEdgeReport(
        sample_size=sample_size,
        naive_trades=naive_trades,
        naive_gross_usd=naive_gross,
        naive_gross_per_btc=_per_btc(naive_gross, naive_q),
        engine_trades=engine_trades,
        engine_net_usd=engine_net,
        engine_net_per_btc=_per_btc(engine_net, engine_q),
        naive_q_btc=naive_q,
        engine_q_btc=engine_q,
        overstatement_usd=overstatement,
        survival_rate=survival,
        rejections=rejections,
        dominant_rejection=dominant,
        headline=_headline(naive_trades, naive_gross, engine_trades, engine_net, rejections),
    )


def _headline(
    naive_trades: int,
    naive_gross: float,
    engine_trades: int,
    engine_net: float,
    rejections: list[RejectionBucket],
) -> str:
    if naive_trades == 0:
        return "Sin spreads brutos detectados en esta sesion todavia."
    lead = (
        f"Un detector ingenuo contaria ${naive_gross:,.2f} brutos en {naive_trades} trades; "
        f"el motor dejo ${engine_net:,.2f} netos en {engine_trades}."
    )
    if rejections:
        top = rejections[0]
        lead += f" Mayor fuga: {top.label} ({top.count})."
    return lead
