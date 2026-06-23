"""Adapter StrategyModule para el detector z-score existente (PRD-008)."""
from __future__ import annotations

from ..engine.statz import StatZDetector
from ..models.enums import Strategy
from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity
from ..models.strategy import StrategyExplanation, StrategyRisk


class StatZStrategyAdapter:
    id = Strategy.stat_z.value
    enabled = True

    def __init__(self, detector: StatZDetector) -> None:
        self.detector = detector

    def on_book(
        self,
        book: NormalizedBook,
        books: dict[str, NormalizedBook],
    ) -> list[Opportunity]:
        return self.detector.on_book(book, books)

    def explain(self, opportunity: Opportunity) -> StrategyExplanation:
        return StrategyExplanation(
            strategy=self.id,
            opportunity_id=opportunity.id,
            title="Statistical z-score",
            summary="Señal estadística que aún debe pasar por el mismo evaluador neto spot.",
            risks=[
                StrategyRisk(
                    key="mean_reversion",
                    label="Reversión no garantizada",
                    severity="medium",
                    detail="La señal z-score no sustituye la validación de fees/profundidad.",
                )
            ],
            payload=opportunity.strategy_payload,
        )
