"""Corredor regional México/MXN experimental (PRD-008)."""
from __future__ import annotations

from ..config import Settings
from ..engine.bookmath import mid_lenient
from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity
from ..models.strategy import RegionalMXNOpportunity, StrategyExplanation, StrategyRisk


class RegionalMXNStrategy:
    id = "regional_mxn"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = settings.strategy_regional_mxn_enabled

    def on_book(
        self,
        book: NormalizedBook,
        books: dict[str, NormalizedBook],
    ) -> list[Opportunity]:
        return []

    def explain(self, opportunity: Opportunity) -> StrategyExplanation:
        return StrategyExplanation(
            strategy=self.id,
            opportunity_id=opportunity.id,
            title="Spread regional MXN",
            summary="Compara BTC/MXN contra BTC/USD usando FX explícito y fricción fiat.",
            legs=opportunity.legs or [],
            risks=[
                StrategyRisk(
                    key="fiat_transfer",
                    label="Fricción fiat",
                    severity="medium",
                    detail="Transferencias y liquidez bancaria pueden dominar el spread regional.",
                )
            ],
            payload=opportunity.strategy_payload,
        )

    def compare(
        self,
        mxn_book: NormalizedBook,
        usd_book: NormalizedBook,
        *,
        usd_mxn: float | None,
    ) -> RegionalMXNOpportunity:
        if usd_mxn is None or usd_mxn <= 0.0:
            raise ValueError("usd_mxn fx rate is required")
        mxn_mid = mid_lenient(mxn_book)
        usd_mid = mid_lenient(usd_book)
        if mxn_mid is None or usd_mid is None or usd_mid <= 0.0:
            raise ValueError("both MXN and USD books need a finite mid price")

        mxn_as_usd = mxn_mid / usd_mxn
        gross_spread_usd = mxn_as_usd - usd_mid
        gross_spread_bps = gross_spread_usd / usd_mid * 10_000.0
        net_spread_bps = gross_spread_bps - self.settings.strategy_mxn_fiat_fee_bps
        return RegionalMXNOpportunity(
            mxn_venue=mxn_book.exchange,
            usd_venue=usd_book.exchange,
            symbol_mxn=mxn_book.symbol,
            symbol_usd=usd_book.symbol,
            btc_mxn_mid=mxn_mid,
            btc_usd_mid=usd_mid,
            usd_mxn=usd_mxn,
            btc_mxn_as_usd=mxn_as_usd,
            gross_spread_usd=gross_spread_usd,
            gross_spread_bps=gross_spread_bps,
            fiat_fee_bps=self.settings.strategy_mxn_fiat_fee_bps,
            net_spread_bps=net_spread_bps,
            risk="experimental_fiat_fx_no_spot_pnl_mixing",
        )

    def find_opportunities(
        self,
        books: dict[str, NormalizedBook],
        *,
        usd_mxn: float | None,
    ) -> list[RegionalMXNOpportunity]:
        if not self.enabled:
            return []
        mxn_books = [
            book for book in books.values()
            if book.quote_ccy.upper() == "MXN" or book.symbol.upper().endswith("/MXN")
        ]
        usd_books = [
            book for book in books.values()
            if book.quote_ccy.upper() in {"USD", "USDT"}
            and not book.symbol.upper().endswith("/MXN")
        ]
        out: list[RegionalMXNOpportunity] = []
        for mxn_book in mxn_books:
            for usd_book in usd_books:
                out.append(self.compare(mxn_book, usd_book, usd_mxn=usd_mxn))
        return out
