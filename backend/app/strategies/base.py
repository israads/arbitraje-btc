"""Contrato común para estrategias de mercado (PRD-008)."""
from __future__ import annotations

from typing import Protocol

from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity
from ..models.strategy import StrategyExplanation


class StrategyModule(Protocol):
    id: str
    enabled: bool

    def on_book(
        self,
        book: NormalizedBook,
        books: dict[str, NormalizedBook],
    ) -> list[Opportunity]: ...

    def explain(self, opportunity: Opportunity) -> StrategyExplanation: ...
