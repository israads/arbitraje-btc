"""C1 — el ingestor emite RawOrderBook, reconecta tras error (sin `break`) y
conserva ts_exchange/seq + sella ts_recv monotónico. Cliente ccxt.pro simulado."""
from __future__ import annotations

import asyncio

from app.config import ExchangeConfig, Settings
from app.ingest import build_ingestors
from app.ingest.exchange_ingestor import ExchangeIngestor


class FakeClient:
    """Reproduce un guion de respuestas de `watch_order_book` (book o excepción)."""

    def __init__(self, scripted: list) -> None:
        self._scripted = list(scripted)
        self.calls = 0
        self.closed = False

    async def watch_order_book(self, symbol: str, limit: int | None = None) -> dict:
        self.calls += 1
        if not self._scripted:
            await asyncio.sleep(3600)  # agota el guion → bloquea hasta cancelación
        item = self._scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True


def _cfg() -> ExchangeConfig:
    return ExchangeConfig(
        id="binance", symbol="BTC/USDT", quote_ccy="USDT",
        fee_taker=0.0010, withdrawal_btc=0.0002, ob_limit=5,
    )


async def test_ingestor_emits_and_reconnects():
    book = {"bids": [[70000.0, 1.0], [69999.0, 0.5]],
            "asks": [[70010.0, 2.0]], "timestamp": 123, "nonce": 9}
    fake = FakeClient([book, RuntimeError("ws dropped"), book])
    received = []
    ing = ExchangeIngestor(
        _cfg(), received.append, client_factory=lambda c: fake, max_backoff=0.01
    )
    task = asyncio.create_task(ing.run())
    for _ in range(300):  # espera 2 books (con un error/reconexión en medio)
        if len(received) >= 2:
            break
        await asyncio.sleep(0.01)
    await ing.close()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(received) >= 2
    b = received[0]
    assert b.exchange == "binance"
    assert b.quote_ccy == "USDT"
    assert b.best_bid == 70000.0
    assert b.best_ask == 70010.0
    assert b.ts_exchange == 123
    assert b.seq == 9
    assert b.ts_recv_monotonic > 0
    assert fake.calls >= 3   # book → excepción → book (no hizo `break`)
    assert fake.closed is True


async def test_ingestor_stops_on_permanent_error():
    """Error PERMANENTE (auth/símbolo/permiso) detiene SÓLO ese venue sin reintentar en bucle
    (robustez C1): a diferencia de un error transitorio, reintentar no lo arregla."""
    from ccxt.base.errors import AuthenticationError

    book = {"bids": [[70000.0, 1.0]], "asks": [[70010.0, 1.0]], "timestamp": 1}
    fake = FakeClient([book, AuthenticationError("clave inválida"), book])
    received: list = []
    ing = ExchangeIngestor(
        _cfg(), received.append, client_factory=lambda c: fake, max_backoff=0.01
    )
    task = asyncio.create_task(ing.run())
    for _ in range(300):
        if ing.permanent_error is not None:
            break
        await asyncio.sleep(0.01)
    await ing.close()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert ing.permanent_error is not None
    assert "AuthenticationError" in ing.permanent_error
    assert len(received) == 1  # sólo el primer book; tras el auth error NO reintenta el tercero


async def test_ingestor_respects_depth_limit():
    deep = {"bids": [[100.0 - i, 1.0] for i in range(20)],
            "asks": [[100.0 + i, 1.0] for i in range(20)], "timestamp": 1}
    fake = FakeClient([deep])
    received = []
    ing = ExchangeIngestor(_cfg(), received.append, client_factory=lambda c: fake)
    task = asyncio.create_task(ing.run())
    for _ in range(300):
        if received:
            break
        await asyncio.sleep(0.01)
    await ing.close()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert received
    assert len(received[0].bids) == 5   # recortado a ob_limit
    assert len(received[0].asks) == 5


# ---------------------------------------------------------------------------
# STORY-013 — Tests de ingestor Coinbase y build_ingestors con 3 exchanges
# ---------------------------------------------------------------------------

def _coinbase_cfg() -> ExchangeConfig:
    """Config de coinbase con ob_limit pequeño para el test."""
    return ExchangeConfig(
        id="coinbase", symbol="BTC/USD", quote_ccy="USD",
        fee_taker=0.0060, withdrawal_btc=0.0001, ob_limit=5,
        enabled=True,
    )


async def test_coinbase_ingestor_emits_and_reconnects():
    """El ingestor de coinbase emite RawOrderBook y reconecta tras error (mismo patrón
    que binance/kraken). BTC/USD → quote_ccy=USD, sin peg USDT."""
    book = {
        "bids": [[50_000.0, 0.5], [49_999.0, 1.0]],
        "asks": [[50_010.0, 0.8]],
        "timestamp": 1_700_000_000_000,
        "nonce": 42,
    }
    fake = FakeClient([book, RuntimeError("ws closed"), book])
    received = []
    ing = ExchangeIngestor(
        _coinbase_cfg(), received.append, client_factory=lambda c: fake, max_backoff=0.01
    )
    task = asyncio.create_task(ing.run())
    for _ in range(300):
        if len(received) >= 2:
            break
        await asyncio.sleep(0.01)
    await ing.close()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(received) >= 2
    b = received[0]
    assert b.exchange == "coinbase"
    assert b.symbol == "BTC/USD"
    assert b.quote_ccy == "USD"          # BTC/USD: sin peg USDT
    assert b.best_bid == 50_000.0
    assert b.best_ask == 50_010.0
    assert b.ts_exchange == 1_700_000_000_000
    assert b.seq == 42
    assert b.ts_recv_monotonic > 0
    assert fake.calls >= 3               # emitió → excepción → emitió (sin break)
    assert fake.closed is True


async def test_coinbase_ingestor_respects_depth_limit():
    """El ingestor de coinbase recorta los niveles al ob_limit (50 en prod, 5 en test)."""
    deep = {
        "bids": [[50_000.0 - i, 1.0] for i in range(20)],
        "asks": [[50_100.0 + i, 1.0] for i in range(20)],
        "timestamp": 1,
    }
    fake = FakeClient([deep])
    received = []
    ing = ExchangeIngestor(_coinbase_cfg(), received.append, client_factory=lambda c: fake)
    task = asyncio.create_task(ing.run())
    for _ in range(300):
        if received:
            break
        await asyncio.sleep(0.01)
    await ing.close()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert received
    assert len(received[0].bids) == 5   # recortado a ob_limit=5
    assert len(received[0].asks) == 5


def test_build_ingestors_includes_coinbase():
    """build_ingestors crea un ingestor por cada exchange habilitado (multi-venue)."""
    s = Settings()
    # Verificamos que coinbase está habilitado en el config por defecto (STORY-013)
    assert s.exchanges["coinbase"].enabled is True

    ingestors = build_ingestors(s, lambda rb: None, client_factory=lambda c: None)  # type: ignore[arg-type]
    ids = {ing.cfg.id for ing in ingestors}
    # Un ingestor por venue habilitado; incluye coinbase y los venues multi añadidos.
    assert ids == {e.id for e in s.enabled_exchanges}
    assert {"binance", "kraken", "coinbase", "gemini", "kucoin"} <= ids
    assert "okx" not in ids and "bitfinex" not in ids  # deshabilitados


def test_build_ingestors_coinbase_config():
    """El ingestor de coinbase tiene los parámetros correctos del Apéndice E."""
    s = Settings()
    ingestors = build_ingestors(s, lambda rb: None, client_factory=lambda c: None)  # type: ignore[arg-type]
    cb = next((ing for ing in ingestors if ing.cfg.id == "coinbase"), None)
    assert cb is not None, "No se encontró el ingestor de coinbase"
    assert cb.cfg.symbol == "BTC/USD"
    assert cb.cfg.quote_ccy == "USD"
    assert cb.cfg.fee_taker == 0.0060     # fees configurables, nunca hardcodeados
    assert cb.cfg.ob_limit == 50          # snapshot level2 grande (Apéndice G)
