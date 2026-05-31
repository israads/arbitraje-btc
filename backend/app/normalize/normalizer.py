"""C3 — Normalizador: RawOrderBook (moneda nativa) → NormalizedBook (USD).

`precio_norm = precio × factor_peg`. Si el peg aún no está disponible para la
moneda de cotización, devuelve `None` (nunca falsea 1.00): el venue simplemente no
entra en la comparación hasta tener su peg vivo.
"""
from __future__ import annotations

import logging

from ..models.market import NormalizedBook, RawOrderBook
from .peg import PegProvider

log = logging.getLogger("app.normalize")


class Normalizer:
    def __init__(self, peg: PegProvider) -> None:
        self._peg = peg
        self._warned: set[str] = set()

    def normalize(self, raw: RawOrderBook) -> NormalizedBook | None:
        factor = self._peg.factor_for(raw.quote_ccy)
        if factor is None:
            if raw.quote_ccy not in self._warned:
                log.info(
                    "normalize: peg de %s aún no disponible; %s queda fuera hasta tenerlo",
                    raw.quote_ccy, raw.exchange,
                )
                self._warned.add(raw.quote_ccy)
            return None
        return NormalizedBook(
            exchange=raw.exchange,
            symbol=raw.symbol,
            quote_ccy=raw.quote_ccy,
            bids=[(p * factor, q) for p, q in raw.bids],
            asks=[(p * factor, q) for p, q in raw.asks],
            price_norm_factor=factor,
            ts_exchange=raw.ts_exchange,
            ts_recv_monotonic=raw.ts_recv_monotonic,
            seq=raw.seq,
        )
