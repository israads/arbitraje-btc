"""C3 — Normalizador a modelo común + normalización de moneda (peg). FR-003.

`precio_norm = precio × peg_stable/USD` con peg vivo (nunca 1.00) y tolerancia
configurable. Implementación: STORY-003.
"""
from __future__ import annotations

import logging

from ..config import Settings
from ..ingest.client_factory import make_ccxtpro_client
from .normalizer import Normalizer
from .peg import PegProvider
from .peg_ingestor import ClientFactory, PegIngestor

log = logging.getLogger("app.normalize")

__all__ = ["Normalizer", "PegProvider", "PegIngestor", "build_peg_ingestors"]


def build_peg_ingestors(
    settings: Settings,
    peg: PegProvider,
    *,
    client_factory: ClientFactory = make_ccxtpro_client,
) -> list[PegIngestor]:
    """Un loop por stablecoin configurada en `peg_pairs`. La fuente es
    `peg_source_exchange` (debe existir en `exchanges`)."""
    source = settings.exchanges.get(settings.peg_source_exchange)
    if source is None:
        log.warning("peg_source_exchange %r no está en exchanges", settings.peg_source_exchange)
        return []
    return [
        PegIngestor(source, stable, pair, peg, client_factory=client_factory,
                    max_backoff=settings.ingest_max_backoff)
        for stable, pair in settings.peg_pairs.items()
    ]
