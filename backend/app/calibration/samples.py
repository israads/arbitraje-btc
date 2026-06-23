"""Construcción de muestras shadow desde oportunidades ya evaluadas."""
from __future__ import annotations

import math
from collections.abc import Mapping

from ..config import Settings
from ..models.calibration import ShadowOpportunitySample
from ..models.explain import OpportunityExplanation
from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity
from ..projection.survival import p_survive


def _finite(v: float | None) -> float | None:
    return float(v) if v is not None and math.isfinite(v) else None


def _book_age_ms(ts_detect: float, book: NormalizedBook | None) -> float | None:
    if book is None:
        return None
    age = (ts_detect - book.ts_recv_monotonic) * 1000.0
    return age if math.isfinite(age) and age >= 0.0 else None


def _dominant_cost(opp: Opportunity) -> str | None:
    explanation: OpportunityExplanation | None = getattr(opp, "explanation", None)
    if explanation is not None:
        return explanation.engine.dominant_cost
    return None


def build_shadow_sample(
    opp: Opportunity,
    books: Mapping[str, NormalizedBook],
    settings: Settings,
    *,
    source: str = "live",
) -> ShadowOpportunitySample:
    """Crea un sample observe-only sin mirar ticks futuros."""
    ts_detect = (
        opp.t_detect
        if opp.t_detect is not None
        else opp.t_recv
        if opp.t_recv is not None
        else 0.0
    )
    buy_book = books.get(opp.buy_venue)
    sell_book = books.get(opp.sell_venue)
    q = max(opp.q_target or 0.0, 0.0)
    gross = (
        (opp.vwap_sell - opp.vwap_buy) * q
        if opp.vwap_buy is not None and opp.vwap_sell is not None and q > 0.0
        else None
    )
    net_per_btc = (
        opp.net_pnl / q
        if opp.net_pnl is not None and q > 0.0 and math.isfinite(opp.net_pnl)
        else None
    )
    spread_bps = (
        ((opp.vwap_sell - opp.vwap_buy) / opp.vwap_buy) * 10_000.0
        if opp.vwap_buy is not None
        and opp.vwap_sell is not None
        and opp.vwap_buy > 0.0
        and math.isfinite(opp.vwap_buy)
        and math.isfinite(opp.vwap_sell)
        else None
    )
    estimate = (
        p_survive(net_per_btc, settings.exec_latency_ms)
        if net_per_btc is not None
        else None
    )
    book_age_buy = _book_age_ms(ts_detect, buy_book)
    book_age_sell = _book_age_ms(ts_detect, sell_book)
    peg_buy = _finite(buy_book.price_norm_factor if buy_book is not None else None)
    peg_sell = _finite(sell_book.price_norm_factor if sell_book is not None else None)
    return ShadowOpportunitySample(
        id=opp.id,
        ts_detect=float(ts_detect),
        strategy=opp.strategy.value,
        symbol=opp.symbol,
        buy_venue=opp.buy_venue,
        sell_venue=opp.sell_venue,
        q_target=q,
        gross_usd=_finite(gross),
        net_usd=_finite(opp.net_pnl),
        net_per_btc=_finite(net_per_btc),
        fees_usd=_finite(opp.fees),
        slippage_usd=_finite(opp.slippage),
        dominant_cost=_dominant_cost(opp),
        latency_ms=_finite(opp.latency_ms),
        book_age_buy_ms=_finite(book_age_buy),
        book_age_sell_ms=_finite(book_age_sell),
        spread_bps=_finite(spread_bps),
        peg_factor_buy=peg_buy,
        peg_factor_sell=peg_sell,
        status=opp.status.value,
        discard_reason=opp.discard_reason.value if opp.discard_reason is not None else None,
        p_survive_estimated=_finite(estimate),
        source=source,
        features={
            "book_age_buy_ms": _finite(book_age_buy),
            "book_age_sell_ms": _finite(book_age_sell),
            "spread_bps": _finite(spread_bps),
            "peg_factor_buy": peg_buy,
            "peg_factor_sell": peg_sell,
            "source": source,
        },
    )
