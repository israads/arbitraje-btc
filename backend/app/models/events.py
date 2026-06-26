"""Evento de streaming SSE (C11). `type` = quote | opportunity | execution |
pnl | breaker | metrics | connection_status."""
from __future__ import annotations

import json
from functools import cached_property
from typing import Any

from pydantic import BaseModel


class StreamEvent(BaseModel):
    type: str
    data: dict[str, Any]

    @cached_property
    def data_json(self) -> str:
        """JSON del payload, serializado UNA sola vez. El hub difunde el mismo objeto a todas
        las colas, así que con N clientes SSE el dict se serializa 1 vez, no N (ruta caliente)."""
        return json.dumps(self.data)
