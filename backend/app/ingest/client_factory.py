"""Fábrica de clientes ccxt.pro (1 instancia por exchange).

El import de `ccxt.pro` es perezoso (dentro de la función): es pesado y solo se
necesita en runtime, no en tests (que inyectan un cliente falso).
"""
from __future__ import annotations

from typing import Any, Protocol, cast

from ..config import ExchangeConfig


class WatchClient(Protocol):
    """Interfaz mínima usada por el ingestor (compatible con ccxt.pro)."""

    async def watch_order_book(self, symbol: str, limit: int | None = ...) -> dict[str, Any]: ...
    async def close(self) -> None: ...


def make_ccxtpro_client(cfg: ExchangeConfig) -> WatchClient:
    import ccxt.pro as ccxtpro  # import perezoso (pesado)

    klass = getattr(ccxtpro, cfg.id)
    options: dict[str, Any] = {"enableRateLimit": True}
    # Coinbase (STORY-013): el snapshot level2 es grande → subir max_msg_size.
    if cfg.id == "coinbase":
        options["options"] = {"watchOrderBook": {"maxMsgSize": 10 * 1024 * 1024}}
    return cast(WatchClient, klass(options))
