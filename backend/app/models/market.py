"""Modelos de mercado: Quote, NormalizedBook, PegRate (C3).

`ts_recv_monotonic` (reloj monotónico local) se usa para latencia y staleness;
`ts_exchange` (epoch ms UTC del exchange) para decisiones y orden. Nunca mezclar
ambos relojes para decidir (ver Integration Architecture).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# (price, qty) — qty en BTC; price en la moneda de cotización del venue.
PriceLevel = tuple[float, float]


class Quote(BaseModel):
    """Top-of-book de un venue (precio en su moneda de cotización, sin normalizar)."""

    exchange: str
    symbol: str
    quote_ccy: str
    best_bid: float
    best_ask: float
    ts_exchange: float | None = None
    ts_recv_monotonic: float
    seq: int | None = None


class NormalizedBook(BaseModel):
    """Order book normalizado a USD. `price_norm_factor = peg_stable/USD` (nunca 1.00
    si `quote_ccy` es una stable distinta de USD)."""

    exchange: str
    symbol: str
    quote_ccy: str
    bids: list[PriceLevel] = Field(default_factory=list)  # orden descendente
    asks: list[PriceLevel] = Field(default_factory=list)  # orden ascendente
    price_norm_factor: float = 1.0
    ts_exchange: float | None = None
    ts_recv_monotonic: float
    seq: int | None = None

    @property
    def best_bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None


class RawOrderBook(BaseModel):
    """Order book crudo de un exchange (ccxt.pro), antes de normalizar a USD (C1).

    `bids`/`asks` ya recortados a la profundidad y en su moneda de cotización
    nativa. El normalizador (C3, STORY-003) lo convierte a `NormalizedBook`.
    """

    exchange: str
    symbol: str
    quote_ccy: str
    bids: list[PriceLevel] = Field(default_factory=list)  # orden descendente
    asks: list[PriceLevel] = Field(default_factory=list)  # orden ascendente
    ts_exchange: float | None = None      # epoch ms del exchange (UTC)
    ts_recv_monotonic: float              # time.monotonic() local (latencia/staleness)
    seq: int | None = None                # nonce/sequence del exchange
    meta: dict[str, Any] = Field(default_factory=dict)  # U/u/checksum/channel específicos

    @property
    def best_bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None


class PegRate(BaseModel):
    """Tipo de cambio vivo de una stablecoin contra USD (par del propio exchange)."""

    stable: str
    usd_rate: float
    ts: float
    source: str
