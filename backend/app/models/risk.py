"""Estado de circuit breakers (C8, FR-012)."""
from __future__ import annotations

from pydantic import BaseModel

from .enums import BreakerType


class CircuitBreakerState(BaseModel):
    type: BreakerType
    active: bool = False
    reason: str | None = None
    since: float | None = None
