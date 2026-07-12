"""C11 — el publisher convierte la salida del pipeline en eventos SSE y los
publica al hub; las quotes van throttled por venue (STORY-005)."""
from __future__ import annotations

import asyncio

from app.models.enums import OpportunityStatus, Strategy
from app.models.market import NormalizedBook
from app.models.opportunity import Opportunity
from app.stream.hub import StreamHub
from app.stream.pump import StreamPublisher


def _nb(ex: str = "binance") -> NormalizedBook:
    return NormalizedBook(
        exchange=ex, symbol="BTC/USDT", quote_ccy="USDT",
        bids=[(100.0, 1.0)], asks=[(101.0, 1.0)], price_norm_factor=0.999,
        ts_recv_monotonic=1.0,
    )


async def test_publish_quote_event():
    hub = StreamHub()
    pub = StreamPublisher(hub, quote_throttle_ms=0)
    gen = hub.subscribe()
    task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    pub.publish_quote(_nb())
    ev = await asyncio.wait_for(task, 1.0)
    assert ev.type == "quote"
    assert ev.data["exchange"] == "binance"
    assert ev.data["usd_ask"] == 101.0 and ev.data["usd_bid"] == 100.0
    await gen.aclose()


async def test_quote_throttle_drops_burst():
    hub = StreamHub()
    pub = StreamPublisher(hub, quote_throttle_ms=10_000)  # ventana enorme
    gen = hub.subscribe()
    task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    pub.publish_quote(_nb())   # pasa
    pub.publish_quote(_nb())   # throttled (mismo venue)
    ev = await asyncio.wait_for(task, 1.0)
    assert ev.type == "quote"
    nxt = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0.05)
    assert not nxt.done()      # no llegó un segundo evento (throttled)
    nxt.cancel()
    try:
        await nxt               # drena la cancelación antes de cerrar el generador
    except asyncio.CancelledError:
        pass


async def test_publish_pnl_event_and_throttle():
    """publish_pnl emite un evento `pnl` (build perezoso) y respeta el throttle: el segundo
    push dentro de la ventana NO se emite y NO invoca build (C11, push en tiempo real)."""
    hub = StreamHub()
    pub = StreamPublisher(hub, pnl_throttle_ms=10_000)  # ventana enorme
    gen = hub.subscribe()
    task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    calls = {"n": 0}

    def build() -> dict:
        calls["n"] += 1
        return {"total_pnl": -1.25, "equity_usd": 200_000.0}

    assert pub.publish_pnl(build) is True
    ev = await asyncio.wait_for(task, 1.0)
    assert ev.type == "pnl"
    assert ev.data["total_pnl"] == -1.25
    assert pub.publish_pnl(build) is False   # throttled
    assert calls["n"] == 1                    # build no se invocó la 2ª vez (perezoso)
    await gen.aclose()


async def test_publish_opportunity_event():
    hub = StreamHub()
    pub = StreamPublisher(hub)
    gen = hub.subscribe()
    task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    opp = Opportunity(
        id="opp-1", strategy=Strategy.spatial, symbol="BTC/USD",
        buy_venue="binance", sell_venue="kraken", status=OpportunityStatus.detected,
    )
    pub.publish_opportunity(opp)
    ev = await asyncio.wait_for(task, 1.0)
    assert ev.type == "opportunity"
    assert ev.data["buy_venue"] == "binance"
    assert ev.data["strategy"] == "spatial"      # enum serializado a str
    assert ev.data["status"] == "detected"
    await gen.aclose()


async def test_publish_metrics_stamps_monotonic_snapshot():
    hub = StreamHub()
    pub = StreamPublisher(hub, metrics_throttle_ms=0)
    gen = hub.subscribe()
    task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    assert pub.publish_metrics(lambda: {"captured": 0, "discard_reasons": {}}) is True
    ev = await asyncio.wait_for(task, 1.0)
    assert ev.type == "metrics"
    assert isinstance(ev.data["asof_monotonic"], float)
    await gen.aclose()
