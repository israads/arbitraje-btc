"""C2/PRD-004 — Integridad de order book por exchange.

La capa genérica bloquea libros estructuralmente corruptos. Los validadores específicos
reportan gaps/checksum por venue y, por defecto (`integrity_mode=warn`), observan sin bloquear
para evitar falsos rechazos mientras confirmamos qué metadata expone ccxt.pro en vivo.
"""
from __future__ import annotations

from typing import Any

from ..models.market import RawOrderBook
from .models import IntegrityDecision, IntegrityMode, IntegrityReport
from .validators import VALIDATORS, GenericIntegrityValidator, structural_integrity_reason


def integrity_reason(raw: RawOrderBook, last_seq: int | None) -> str | None:
    """Compatibilidad con STORY-015: motivo genérico de rechazo, o None."""
    return structural_integrity_reason(raw, last_seq)


class BookIntegrityChecker:
    """Valida RawOrderBook por venue; mantiene secuencia y estadísticas enriquecidas."""

    def __init__(self, mode: IntegrityMode = "warn") -> None:
        self.mode = mode
        self._generic = GenericIntegrityValidator()
        self._reports: dict[str, IntegrityReport] = {}

    def _validator_for(self, exchange: str) -> Any:
        if self.mode == "generic":
            return self._generic
        return VALIDATORS.get(exchange, self._generic)

    def check(self, raw: RawOrderBook) -> bool:
        """True si el libro puede entrar al estado vivo; False si debe descartarse."""
        rep = self._reports.setdefault(raw.exchange, IntegrityReport())
        validator = self._validator_for(raw.exchange)
        decision: IntegrityDecision = validator.check(raw, rep)
        rep.validator = decision.validator
        if decision.reason == "sequence_gap":
            rep.sequence_gaps += 1
        if decision.reason == "checksum_failure":
            rep.checksum_failures += 1
        if decision.checksum is not None:
            rep.last_checksum = decision.checksum

        should_block = (not decision.accepted) and (
            decision.severity == "error" or self.mode == "enforce"
        )
        if should_block:
            rep.rejected += 1
            rep.last_reason = decision.reason
            return False

        rep.accepted += 1
        rep.last_reason = decision.reason
        if decision.seq is not None:
            rep.last_seq = decision.seq
        rep.last_valid_at = raw.ts_recv_monotonic
        return True

    def reports(self) -> dict[str, dict[str, Any]]:
        return {ex: r.to_dict() for ex, r in self._reports.items()}
