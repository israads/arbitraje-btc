"""Registry de adapters de ejecución.

No hay fallback a live: si un venue no está soportado explícitamente, se rechaza.
"""
from __future__ import annotations

from ..config import Settings
from .binance import BinanceTestnetAdapter
from .models import ExecutionAdapter

SUPPORTED_EXECUTION_VENUES: tuple[str, ...] = ("binance",)


class UnsupportedExecutionVenue(ValueError):
    pass


def get_execution_adapter(settings: Settings, venue: str) -> ExecutionAdapter:
    normalized = venue.strip().lower()
    if normalized != "binance":
        raise UnsupportedExecutionVenue(f"unsupported execution venue: {venue}")
    return BinanceTestnetAdapter(settings)
