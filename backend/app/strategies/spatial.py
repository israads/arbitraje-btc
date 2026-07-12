"""Adapter StrategyModule para el detector espacial existente (PRD-008).

ESTADO: contrato/introspección, sin consumidor en el hot path. El motor vivo cablea
`SpatialDetector` directamente (`run_engine`); este adapter existe para cumplir la
interfaz unificada de PRD-008 (tests de contrato en `tests/test_strategy_modules.py`)
y para extender `/strategies` sin tocar el motor. No es código muerto accidental.
"""
from __future__ import annotations

from ..engine.detector import SpatialDetector
from ..models.enums import Strategy
from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity
from ..models.strategy import StrategyExplanation


class SpatialStrategyAdapter:
    id = Strategy.spatial.value
    enabled = True

    def __init__(self, detector: SpatialDetector) -> None:
        self.detector = detector

    def on_book(
        self,
        book: NormalizedBook,
        books: dict[str, NormalizedBook],
    ) -> list[Opportunity]:
        return self.detector.on_book(book)

    def explain(self, opportunity: Opportunity) -> StrategyExplanation:
        return StrategyExplanation(
            strategy=self.id,
            opportunity_id=opportunity.id,
            title="Spatial cross-exchange",
            summary="Cruce spot entre venues, evaluado por el motor principal.",
            payload=opportunity.strategy_payload,
        )
