"""Modelos de integridad enriquecida por exchange (PRD-004)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

IntegrityMode = Literal["generic", "warn", "enforce"]
IntegritySeverity = Literal["info", "warn", "error"]


class IntegrityDecision(BaseModel):
    accepted: bool
    reason: str | None = None
    validator: str
    seq: int | None = None
    checksum: str | None = None
    severity: IntegritySeverity = "error"


class IntegrityReport(BaseModel):
    validator: str = "generic"
    accepted: int = 0
    rejected: int = 0
    last_reason: str | None = None
    last_seq: int | None = None
    last_checksum: str | None = None
    checksum_failures: int = 0
    sequence_gaps: int = 0
    last_valid_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
