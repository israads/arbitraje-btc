"""C1 — Ingestor de un exchange: loop `watch_order_book` con reconexión backoff.

Sella `ts_recv` monotónico (latencia/staleness) y conserva `ts_exchange`. Nunca hace
`break` ante un error: registra, espera (backoff exponencial acotado) y reintenta —
ccxt.pro re-suscribe en la siguiente llamada. Emite `RawOrderBook` vía `on_book`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from ..config import ExchangeConfig
from ..models.market import RawOrderBook
from .client_factory import WatchClient, make_ccxtpro_client

log = logging.getLogger("app.ingest")

ClientFactory = Callable[[ExchangeConfig], WatchClient]

# Errores PERMANENTES por venue: credenciales inválidas, símbolo inexistente o permiso
# denegado NO se arreglan reintentando — reintentar en bucle sólo desperdicia ciclos y oculta
# el fallo. Se detiene ESE venue (los demás siguen). Los transitorios (red/timeout/JSON) caen
# al backoff. Import tolerante: sin ccxt instalado, la tupla queda vacía (no rompe los tests).
try:
    from ccxt.base.errors import (
        AuthenticationError,
        BadSymbol,
        PermissionDenied,
    )

    _PERMANENT_ERRORS: tuple[type[BaseException], ...] = (
        AuthenticationError, BadSymbol, PermissionDenied,
    )
except Exception:  # pragma: no cover — ccxt siempre presente en runtime/CI
    _PERMANENT_ERRORS = ()


class ExchangeIngestor:
    def __init__(
        self,
        cfg: ExchangeConfig,
        on_book: Callable[[RawOrderBook], None],
        *,
        client_factory: ClientFactory = make_ccxtpro_client,
        max_backoff: float = 30.0,
    ) -> None:
        self.cfg = cfg
        self._on_book = on_book
        self._client_factory = client_factory
        self.max_backoff = max_backoff
        self._client: WatchClient | None = None
        self._running = True
        self._first = True
        self.permanent_error: str | None = None  # set si el venue se detiene por fallo permanente

    async def run(self) -> None:
        self._client = self._client_factory(self.cfg)
        backoff = 1.0
        while self._running:
            try:
                ob = await self._client.watch_order_book(self.cfg.symbol, limit=self.cfg.ob_limit)
                book = self._to_raw(ob)
                if self._first:
                    log.info("ingest %s: primer order book OK (%s)", self.cfg.id, self.cfg.symbol)
                    self._first = False
                self._on_book(book)
                backoff = 1.0  # reset tras éxito
            except asyncio.CancelledError:
                raise
            except _PERMANENT_ERRORS as exc:
                # Auth/símbolo/permiso: reintentar no lo arregla. Detenemos SÓLO este venue
                # (los demás feeds siguen) y dejamos rastro para health/diagnóstico.
                self.permanent_error = f"{type(exc).__name__}: {exc}"
                log.error(
                    "ingest %s error PERMANENTE (%s) — venue detenido, sin reintentos",
                    self.cfg.id, self.permanent_error,
                )
                self._running = False
            except Exception as exc:  # noqa: BLE001 — resiliencia: nunca tumbar el loop
                log.warning(
                    "ingest %s error: %s — reconectando en %.1fs", self.cfg.id, exc, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(self.max_backoff, backoff * 2)

    def _to_raw(self, ob: dict[str, Any]) -> RawOrderBook:
        n = self.cfg.ob_limit
        meta = self._extract_meta(ob)
        return RawOrderBook(
            exchange=self.cfg.id,
            symbol=self.cfg.symbol,
            quote_ccy=self.cfg.quote_ccy,
            bids=[(float(p), float(q)) for p, q in (ob.get("bids") or [])[:n]],
            asks=[(float(p), float(q)) for p, q in (ob.get("asks") or [])[:n]],
            ts_exchange=ob.get("timestamp"),
            ts_recv_monotonic=time.monotonic(),
            seq=ob.get("nonce"),
            meta=meta,
        )

    @staticmethod
    def _extract_meta(ob: dict[str, Any]) -> dict[str, Any]:
        """Preserva metadata útil para validadores por venue sin acoplarse a ccxt internals."""
        meta: dict[str, Any] = {}
        for key in (
            "nonce",
            "checksum",
            "checksum_crc32",
            "checksum_valid",
            "sequence",
            "sequence_num",
            "first_update_id",
            "final_update_id",
            "lastUpdateId",
            "U",
            "u",
            "channel",
        ):
            if key in ob:
                meta[key] = ob[key]
        info = ob.get("info")
        if isinstance(info, dict):
            for key in (
                "checksum",
                "sequence",
                "sequence_num",
                "first_update_id",
                "final_update_id",
                "lastUpdateId",
                "U",
                "u",
                "channel",
            ):
                if key in info and key not in meta:
                    meta[key] = info[key]
        return meta

    async def close(self) -> None:
        self._running = False
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as exc:  # noqa: BLE001
                log.debug("ingest %s close error: %s", self.cfg.id, exc)
