"""C1 — Ingestores por exchange (ccxt.pro). FR-001, FR-002.

Un loop `watch_order_book` por (exchange, símbolo), agrupados con
`gather(return_exceptions=True)`; `limit` acotado a valores válidos del exchange;
reconexión con backoff (sin `break`); sella `ts_recv` monotónico + `ts_exchange`.

Implementación: STORY-002 (Binance+Kraken). Coinbase se habilita en STORY-013.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable

from ..config import Settings
from ..models.market import RawOrderBook
from ..runner import Runner
from .client_factory import make_ccxtpro_client
from .exchange_ingestor import ClientFactory, ExchangeIngestor

log = logging.getLogger("app.ingest")

__all__ = ["ExchangeIngestor", "build_ingestors", "run_ingestors", "make_ccxtpro_client"]


def build_ingestors(
    settings: Settings,
    on_book: Callable[[RawOrderBook], None],
    *,
    client_factory: ClientFactory = make_ccxtpro_client,
) -> list[ExchangeIngestor]:
    return [
        ExchangeIngestor(
            cfg, on_book, client_factory=client_factory, max_backoff=settings.ingest_max_backoff
        )
        for cfg in settings.enabled_exchanges
    ]


async def run_ingestors(ingestors: Iterable[Runner]) -> None:
    """Agrupa los loops de cualquier `Runner` (ingestor de exchange o de peg): una excepción
    en uno no tumba a los demás (NFR-002/003)."""
    await asyncio.gather(*(ing.run() for ing in ingestors), return_exceptions=True)
