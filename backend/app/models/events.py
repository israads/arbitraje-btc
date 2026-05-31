"""Evento de streaming SSE (C11). `type` = quote | opportunity | execution |
pnl | breaker | metrics | connection_status."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class StreamEvent(BaseModel):
    type: str
    data: dict[str, Any]
