"""Funding/basis read-only (PRD-008).

ESTADO: estructura sin señal por diseño. `on_book` devuelve SIEMPRE `[]` porque no hay
feed de funding/perp en el alcance actual (spot only): el endpoint
`/strategies/funding/opportunities` expone la ESTRUCTURA del playbook (rates + explain)
para demostrar que la arquitectura extiende a funding sin mezclar su riesgo con el P&L
spot. Activarla de verdad requiere un ingestor de funding rates (fuera de alcance).
"""
from __future__ import annotations

from ..config import Settings
from ..engine.bookmath import mid_lenient
from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity
from ..models.strategy import FundingOpportunity, FundingRate, StrategyExplanation, StrategyRisk


class FundingBasisStrategy:
    id = "funding_basis"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = settings.strategy_funding_enabled

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
            title="Funding/basis read-only",
            summary="La oportunidad de funding se mantiene separada del simulador spot.",
            legs=opportunity.legs or [],
            risks=[
                StrategyRisk(
                    key="margin",
                    label="Riesgo de margen",
                    severity="high",
                    detail="Liquidación y margining quedan fuera del flujo spot.",
                )
            ],
            payload=opportunity.strategy_payload,
        )

    def find_opportunities(
        self,
        rates: list[FundingRate],
        spot_books: dict[str, NormalizedBook],
        *,
        horizon_hours: float = 8.0,
    ) -> list[FundingOpportunity]:
        if not self.enabled:
            return []

        out: list[FundingOpportunity] = []
        for rate in rates:
            spot = self._spot_book(rate, spot_books)
            if spot is None:
                continue
            spot_mid = mid_lenient(spot)
            if spot_mid is None or spot_mid <= 0.0:
                continue
            basis_bps = (rate.mark_price - spot_mid) / spot_mid * 10_000.0
            funding_apr = rate.rate * (24.0 / horizon_hours) * 365.0 * 100.0
            expected_carry_apr = funding_apr - (
                self.settings.strategy_funding_hedge_cost_bps / 100.0
            )
            out.append(
                FundingOpportunity(
                    spot_venue=spot.exchange,
                    perp_venue=rate.venue,
                    symbol=rate.symbol,
                    spot_mid=spot_mid,
                    mark_price=rate.mark_price,
                    index_price=rate.index_price,
                    basis_bps=basis_bps,
                    funding_apr=funding_apr,
                    hedge_cost_bps=self.settings.strategy_funding_hedge_cost_bps,
                    expected_carry_apr=expected_carry_apr,
                    horizon_hours=horizon_hours,
                    risk="read_only_no_spot_pnl_mixing",
                )
            )
        return out

    @staticmethod
    def _spot_book(
        rate: FundingRate,
        spot_books: dict[str, NormalizedBook],
    ) -> NormalizedBook | None:
        base = rate.symbol.split("/")[0].upper()
        for book in spot_books.values():
            parsed = book.symbol.split("/")
            if len(parsed) == 2 and parsed[0].upper() == base:
                return book
        return None
