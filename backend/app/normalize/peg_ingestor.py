"""C3 — Loop que mantiene vivo el peg de una stablecoin observando su par */USD
(p.ej. USDT/USD en Kraken) vía `watch_ticker`. Misma resiliencia que C1 (backoff,
sin `break`). Alimenta el `PegProvider`.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from ..config import ExchangeConfig
from ..ingest.client_factory import WatchClient, make_ccxtpro_client
from .peg import PegProvider

log = logging.getLogger("app.normalize.peg")

ClientFactory = Callable[[ExchangeConfig], WatchClient]


def _rate_from_ticker(t: dict[str, Any]) -> float | None:
    bid, ask = t.get("bid"), t.get("ask")
    if bid and ask and bid > 0 and ask > 0:
        return (float(bid) + float(ask)) / 2.0
    last = t.get("last") or t.get("close")
    return float(last) if last else None


class PegIngestor:
    def __init__(
        self,
        source_cfg: ExchangeConfig,
        stable: str,
        pair: str,
        peg: PegProvider,
        *,
        client_factory: ClientFactory = make_ccxtpro_client,
        max_backoff: float = 30.0,
    ) -> None:
        self.source_cfg = source_cfg
        self.stable = stable
        self.pair = pair
        self._peg = peg
        self._client_factory = client_factory
        self.max_backoff = max_backoff
        self._client: WatchClient | None = None
        self._running = True
        self._first = True

    async def run(self) -> None:
        self._client = self._client_factory(self.source_cfg)
        backoff = 1.0
        while self._running:
            try:
                t = await self._client.watch_ticker(self.pair)  # type: ignore[attr-defined]
                rate = _rate_from_ticker(t)
                if rate:
                    self._peg.update(
                        self.stable, rate, source=self.source_cfg.id, ts=t.get("timestamp") or 0
                    )
                    if self._first:
                        log.info("peg %s=%.5f USD (via %s)", self.stable, rate, self.source_cfg.id)
                        self._first = False
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("peg %s error: %s — reintento en %.1fs", self.stable, exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(self.max_backoff, backoff * 2)

    async def close(self) -> None:
        self._running = False
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as exc:  # noqa: BLE001
                log.debug("peg %s close error: %s", self.stable, exc)
