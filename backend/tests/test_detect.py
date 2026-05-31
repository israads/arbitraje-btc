"""C5 — detección espacial naive sobre books normalizados (FR-004)."""
from __future__ import annotations

import time

from app.config import Settings
from app.engine.detector import SpatialDetector
from app.models.enums import OpportunityStatus, Strategy
from app.models.market import NormalizedBook


def _nb(ex: str, bid: float, ask: float, ts: float) -> NormalizedBook:
    return NormalizedBook(
        exchange=ex, symbol="BTC/USD", quote_ccy="USD",
        bids=[(bid, 1.0)], asks=[(ask, 1.0)], price_norm_factor=1.0, ts_recv_monotonic=ts,
    )


def test_no_cross_no_opportunity():
    d = SpatialDetector(Settings())
    t = time.monotonic()
    assert d.on_book(_nb("binance", 100, 101, t)) == []   # un solo venue
    assert d.on_book(_nb("kraken", 99, 100.5, t)) == []   # libros solapados, sin cruce


def test_detects_spatial_cross():
    d = SpatialDetector(Settings())
    t = time.monotonic()
    d.on_book(_nb("binance", 100, 101, t))
    opps = d.on_book(_nb("kraken", 102, 103, t))          # ask_binance 101 < bid_kraken 102
    assert len(opps) == 1
    o = opps[0]
    assert o.strategy == Strategy.spatial
    assert o.buy_venue == "binance" and o.sell_venue == "kraken"
    assert o.vwap_buy == 101 and o.vwap_sell == 102
    assert o.status == OpportunityStatus.detected
    assert o.t_detect is not None
    assert o.latency_ms is not None and o.latency_ms >= 0


def test_excludes_venue_without_book():
    d = SpatialDetector(Settings())
    t = time.monotonic()
    empty = NormalizedBook(
        exchange="kraken", symbol="BTC/USD", quote_ccy="USD",
        bids=[], asks=[], price_norm_factor=1.0, ts_recv_monotonic=t,
    )
    d.on_book(empty)
    assert d.on_book(_nb("binance", 100, 101, t)) == []   # kraken sin datos no participa


# ---------------------------------------------------------------------------
# STORY-013 — Tests de detección con 3 venues (binance + kraken + coinbase)
# ---------------------------------------------------------------------------

def test_three_venues_all_pairs_evaluated():
    """Con 3 venues, el detector evalúa los 6 pares ordenados (compra en A, venta en B).

    Escenario: coinbase ofrece el ask más bajo (mejor compra), kraken el bid más alto
    (mejor venta). La oportunidad real es coinbase→kraken; binance no participa
    porque su spread no cruza con ningún otro.
      binance:  bid=50_100, ask=50_200   (spread 100, precio intermedio)
      kraken:   bid=50_300, ask=50_400   (bid alto → mejor venta)
      coinbase: bid=49_900, ask=50_000   (ask bajo → mejor compra)
    Cruce: ask_coinbase(50_000) < bid_kraken(50_300) → opp coinbase→kraken.
    También: ask_coinbase(50_000) < bid_binance(50_100) → opp coinbase→binance.
    NO hay cruce: ask_binance < bid_kraken? 50_200 < 50_300 → sí también.
    """
    d = SpatialDetector(Settings())
    t = time.monotonic()
    d.on_book(_nb("binance",  50_100, 50_200, t))
    d.on_book(_nb("kraken",   50_300, 50_400, t))
    opps = d.on_book(_nb("coinbase", 49_900, 50_000, t))

    # Debe haber al menos 1 oportunidad con coinbase como buy_venue
    buy_coinbase = [o for o in opps if o.buy_venue == "coinbase"]
    assert len(buy_coinbase) >= 1, "coinbase debe ser buy_venue en al menos 1 opp"

    # La mejor opp: coinbase→kraken (mayor spread bruto)
    cb_kraken = [o for o in opps if o.buy_venue == "coinbase" and o.sell_venue == "kraken"]
    assert len(cb_kraken) == 1
    o = cb_kraken[0]
    assert o.vwap_buy == 50_000     # ask coinbase
    assert o.vwap_sell == 50_300    # bid kraken
    assert o.strategy == Strategy.spatial
    assert o.status == OpportunityStatus.detected


def test_three_venues_coinbase_best_sell():
    """Coinbase con bid alto es la mejor venta; binance ofrece el ask más bajo.

      binance:  bid=50_000, ask=50_100   (ask bajo → mejor compra)
      kraken:   bid=50_050, ask=50_200   (cruce parcial)
      coinbase: bid=50_400, ask=50_500   (bid alto → mejor venta)
    Cruce: ask_binance(50_100) < bid_coinbase(50_400) → opp binance→coinbase.
    También: ask_binance(50_100) < bid_kraken(50_050)? No (50_100 > 50_050).
    También: ask_kraken(50_200) < bid_coinbase(50_400)? Sí → opp kraken→coinbase.
    """
    d = SpatialDetector(Settings())
    t = time.monotonic()
    d.on_book(_nb("binance",  50_000, 50_100, t))
    d.on_book(_nb("kraken",   50_050, 50_200, t))
    opps = d.on_book(_nb("coinbase", 50_400, 50_500, t))

    sell_coinbase = [o for o in opps if o.sell_venue == "coinbase"]
    assert len(sell_coinbase) >= 1, "coinbase debe ser sell_venue en al menos 1 opp"

    # binance→coinbase debe estar presente
    bn_cb = [o for o in opps if o.buy_venue == "binance" and o.sell_venue == "coinbase"]
    assert len(bn_cb) == 1
    assert bn_cb[0].vwap_buy == 50_100    # ask binance
    assert bn_cb[0].vwap_sell == 50_400   # bid coinbase


def test_three_venues_no_cross_no_opps():
    """Sin cruce entre ningún par de los 3 venues → lista vacía."""
    d = SpatialDetector(Settings())
    t = time.monotonic()
    d.on_book(_nb("binance",  50_000, 50_100, t))
    d.on_book(_nb("kraken",   50_050, 50_200, t))
    opps = d.on_book(_nb("coinbase", 49_900, 50_250, t))
    # ask_binance=50_100 < bid_kraken=50_050? No
    # ask_binance=50_100 < bid_coinbase=49_900? No
    # ask_kraken=50_200 < bid_binance=50_000? No
    # ask_kraken=50_200 < bid_coinbase=49_900? No
    # ask_coinbase=50_250 < bid_binance=50_000? No
    # ask_coinbase=50_250 < bid_kraken=50_050? No
    assert opps == []


def test_three_venues_peg_factor_one_usd():
    """Coinbase (BTC/USD) tiene price_norm_factor=1.0 → precios sin modificar."""
    nb_cb = NormalizedBook(
        exchange="coinbase", symbol="BTC/USD", quote_ccy="USD",
        bids=[(50_000.0, 1.0)], asks=[(50_100.0, 1.0)],
        price_norm_factor=1.0, ts_recv_monotonic=time.monotonic(),
    )
    assert nb_cb.price_norm_factor == 1.0
    assert nb_cb.best_bid == 50_000.0
    assert nb_cb.best_ask == 50_100.0
