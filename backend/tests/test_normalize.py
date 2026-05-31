"""C3 — peg vivo + normalización a USD (FR-003). Nunca se asume 1.00."""
from __future__ import annotations

import asyncio

from app.config import ExchangeConfig, Settings
from app.models.market import RawOrderBook
from app.normalize import build_peg_ingestors
from app.normalize.normalizer import Normalizer
from app.normalize.peg import PegProvider
from app.normalize.peg_ingestor import PegIngestor, _rate_from_ticker


def _raw(exchange: str, quote: str, bid: float, ask: float) -> RawOrderBook:
    return RawOrderBook(
        exchange=exchange, symbol="BTC/" + quote, quote_ccy=quote,
        bids=[(bid, 1.0)], asks=[(ask, 1.0)], ts_recv_monotonic=1.0,
    )


def test_peg_provider_never_assumes_one():
    peg = PegProvider(target="USD", tolerance=0.005)
    assert peg.factor_for("USD") == 1.0          # target = identidad
    assert peg.factor_for("USDT") is None        # sin peg vivo → None (NO 1.00)
    peg.update("USDT", 0.9997, source="kraken", ts=0)
    assert peg.factor_for("USDT") == 0.9997
    assert peg.within_tolerance("USDT") is True
    peg.update("USDT", 0.95, source="kraken", ts=0)  # depeg
    assert peg.within_tolerance("USDT") is False


def test_normalizer_requires_live_peg():
    peg = PegProvider()
    norm = Normalizer(peg)
    assert norm.normalize(_raw("binance", "USDT", 70000, 70010)) is None  # sin peg
    peg.update("USDT", 0.9998, source="kraken", ts=0)
    nb = norm.normalize(_raw("binance", "USDT", 70000, 70010))
    assert nb is not None
    assert nb.price_norm_factor == 0.9998
    assert nb.best_ask == 70010 * 0.9998
    assert nb.best_bid == 70000 * 0.9998


def test_normalization_makes_venues_comparable():
    """La tesis: Binance(USDT) y Kraken(USD) solo son comparables tras el peg."""
    peg = PegProvider()
    peg.update("USDT", 0.9990, source="kraken", ts=0)  # USDT ligeramente bajo par
    norm = Normalizer(peg)
    binance = norm.normalize(_raw("binance", "USDT", 73534.0, 73534.5))
    kraken = norm.normalize(_raw("kraken", "USD", 73419.0, 73419.5))
    assert binance is not None and kraken is not None
    # Tras normalizar, el precio USDT baja ~0.1% → la brecha aparente se reduce.
    assert binance.best_ask < 73534.5                  # factor < 1 aplicado
    gap_raw = 73534.5 - 73419.5
    gap_norm = binance.best_ask - kraken.best_ask
    assert gap_norm < gap_raw                          # normalizar acerca los precios


async def test_peg_ingestor_updates_provider():
    class FakeTickerClient:
        def __init__(self) -> None:
            self.closed = False
            self._sent = False

        async def watch_ticker(self, pair: str) -> dict:
            if self._sent:
                await asyncio.sleep(3600)
            self._sent = True
            return {"bid": 0.9996, "ask": 0.9998, "last": 0.9997, "timestamp": 111}

        async def close(self) -> None:
            self.closed = True

    src = ExchangeConfig(id="kraken", symbol="BTC/USD", quote_ccy="USD",
                         fee_taker=0.004, withdrawal_btc=0.00005, ob_limit=25)
    peg = PegProvider()
    ing = PegIngestor(src, "USDT", "USDT/USD", peg,
                      client_factory=lambda c: FakeTickerClient(), max_backoff=0.01)
    task = asyncio.create_task(ing.run())
    for _ in range(200):
        if peg.factor_for("USDT") is not None:
            break
        await asyncio.sleep(0.01)
    await ing.close()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    # mid de (0.9996, 0.9998) = 0.9997
    assert peg.factor_for("USDT") == 0.9997


# --- PegProvider.snapshot --------------------------------------------------

def test_peg_snapshot_includes_target_and_rates():
    """`snapshot()` siempre expone el target (USD=1.0, dentro de tolerancia) y cada stable
    viva con su `within_tolerance` calculado contra el par 1.0."""
    peg = PegProvider(target="USD", tolerance=0.005)
    peg.update("USDT", 0.9997, source="kraken", ts=0)
    peg.update("EURT", 0.95, source="kraken", ts=0)  # depeg fuera de tolerancia
    snap = peg.snapshot()
    assert snap["USD"] == {"usd_rate": 1.0, "within_tolerance": True}
    assert snap["USDT"]["usd_rate"] == 0.9997
    assert snap["USDT"]["within_tolerance"] is True
    assert snap["EURT"]["within_tolerance"] is False


# --- _rate_from_ticker: ramas de fallback ----------------------------------

def test_rate_from_ticker_uses_mid_when_bid_ask_present():
    assert _rate_from_ticker({"bid": 0.9996, "ask": 0.9998}) == 0.9997


def test_rate_from_ticker_falls_back_to_last_then_close():
    # Sin bid/ask válidos → usa `last`.
    assert _rate_from_ticker({"bid": 0, "ask": 0, "last": 1.0001}) == 1.0001
    # Sin `last` → usa `close`.
    assert _rate_from_ticker({"close": 0.9990}) == 0.9990


def test_rate_from_ticker_none_when_no_usable_field():
    assert _rate_from_ticker({}) is None
    assert _rate_from_ticker({"bid": 0, "ask": 0, "last": 0}) is None


# --- build_peg_ingestors ---------------------------------------------------

def _settings_with_peg_source(source: str, *, peg_pairs=None) -> Settings:
    exchanges = {
        "kraken": ExchangeConfig(id="kraken", symbol="BTC/USD", quote_ccy="USD",
                                 fee_taker=0.004, withdrawal_btc=0.00005, ob_limit=25),
    }
    kw = dict(exchanges=exchanges, ingest_autostart=False, peg_source_exchange=source)
    if peg_pairs is not None:
        kw["peg_pairs"] = peg_pairs
    return Settings(**kw)


def test_build_peg_ingestors_one_per_pair():
    """Un `PegIngestor` por stablecoin en `peg_pairs`, con la fuente = `peg_source_exchange`."""
    s = _settings_with_peg_source("kraken", peg_pairs={"USDT": "USDT/USD", "EURT": "EURT/USD"})
    peg = PegProvider()
    ingestors = build_peg_ingestors(s, peg, client_factory=lambda c: object())
    assert len(ingestors) == 2
    assert {ing.stable for ing in ingestors} == {"USDT", "EURT"}
    assert all(ing.source_cfg.id == "kraken" for ing in ingestors)


def test_build_peg_ingestors_empty_when_source_missing():
    """Si `peg_source_exchange` no está en `exchanges` → lista vacía (no rompe el arranque)."""
    s = _settings_with_peg_source("inexistente")
    ingestors = build_peg_ingestors(s, PegProvider(), client_factory=lambda c: object())
    assert ingestors == []


# --- PegIngestor.close: error de cierre tolerado ---------------------------

async def test_peg_ingestor_close_tolerates_client_error():
    """`close()` no debe propagar si el cliente falla al cerrar (best-effort)."""
    class FailingCloseClient:
        async def watch_ticker(self, pair: str) -> dict:
            await asyncio.sleep(3600)

        async def close(self) -> None:
            raise RuntimeError("boom al cerrar")

    src = ExchangeConfig(id="kraken", symbol="BTC/USD", quote_ccy="USD",
                         fee_taker=0.004, withdrawal_btc=0.00005, ob_limit=25)
    ing = PegIngestor(src, "USDT", "USDT/USD", PegProvider(),
                      client_factory=lambda c: FailingCloseClient(), max_backoff=0.01)
    ing._client = FailingCloseClient()
    await ing.close()  # no debe lanzar
    assert ing._running is False


async def test_peg_ingestor_retries_on_watch_error():
    """Un error en `watch_ticker` se reintenta con backoff (sin `break`); tras el fallo
    inicial el siguiente tick actualiza el peg."""
    class FlakyClient:
        def __init__(self) -> None:
            self.calls = 0

        async def watch_ticker(self, pair: str) -> dict:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("primer fallo de red")
            if self.calls == 2:
                return {"bid": 0.9996, "ask": 0.9998, "timestamp": 7}
            await asyncio.sleep(3600)

        async def close(self) -> None:
            pass

    src = ExchangeConfig(id="kraken", symbol="BTC/USD", quote_ccy="USD",
                         fee_taker=0.004, withdrawal_btc=0.00005, ob_limit=25)
    peg = PegProvider()
    ing = PegIngestor(src, "USDT", "USDT/USD", peg,
                      client_factory=lambda c: FlakyClient(), max_backoff=0.01)
    task = asyncio.create_task(ing.run())
    for _ in range(300):
        if peg.factor_for("USDT") is not None:
            break
        await asyncio.sleep(0.01)
    await ing.close()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert peg.factor_for("USDT") == 0.9997  # se recuperó tras el reintento
