from __future__ import annotations

import pytest

from app.config import Settings
from app.engine.detector import SpatialDetector
from app.engine.statz import StatZDetector
from app.metrics import MetricsCollector
from app.models.enums import Strategy
from app.models.market import NormalizedBook
from app.models.opportunity import Opportunity
from app.models.strategy import FundingRate
from app.strategies import (
    FundingBasisStrategy,
    RegionalMXNStrategy,
    SpatialStrategyAdapter,
    StatZStrategyAdapter,
    TriangularStrategy,
)


def _book(
    exchange: str,
    symbol: str,
    quote: str,
    *,
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
) -> NormalizedBook:
    return NormalizedBook(
        exchange=exchange,
        symbol=symbol,
        quote_ccy=quote,
        bids=bids,
        asks=asks,
        ts_recv_monotonic=1.0,
    )


def _tri_books(*, eth_usd_bid: float = 6.0, eth_usd_qty: float = 300.0) -> list[NormalizedBook]:
    return [
        _book(
            "binance",
            "BTC/USD",
            "USD",
            bids=[(99.0, 20.0)],
            asks=[(100.0, 20.0)],
        ),
        _book(
            "binance",
            "ETH/BTC",
            "BTC",
            bids=[(0.049, 300.0)],
            asks=[(0.05, 300.0)],
        ),
        _book(
            "binance",
            "ETH/USD",
            "USD",
            bids=[(eth_usd_bid, eth_usd_qty)],
            asks=[(6.1, 300.0)],
        ),
    ]


def test_strategy_adapters_keep_existing_detector_contract():
    settings = Settings()
    spatial = SpatialStrategyAdapter(SpatialDetector(settings))
    statz = StatZStrategyAdapter(StatZDetector(settings))
    book = _book("binance", "BTC/USD", "USD", bids=[(100.0, 1.0)], asks=[(101.0, 1.0)])

    assert spatial.id == Strategy.spatial.value
    assert statz.id == Strategy.stat_z.value
    assert spatial.on_book(book, {"binance": book}) == []
    assert statz.on_book(book, {"binance": book}) == []


def test_triangular_cycle_detected_when_fee_adjusted_positive():
    strategy = TriangularStrategy(Settings(strategy_triangular_enabled=True))

    opps = strategy.find_opportunities(_tri_books(), venue="binance")

    assert len(opps) == 1
    opp = opps[0]
    assert opp.strategy == Strategy.triangular
    assert opp.status == "viable"
    assert opp.buy_venue == "binance" and opp.sell_venue == "binance"
    assert opp.legs is not None and len(opp.legs) == 3
    assert opp.strategy_payload["depth_validated"] is True
    assert opp.strategy_payload["net_profit"] == pytest.approx(196.4035988)


def test_triangular_cycle_rejected_when_fee_negative():
    strategy = TriangularStrategy(Settings(strategy_triangular_enabled=True))

    assert strategy.find_opportunities(_tri_books(eth_usd_bid=5.0), venue="binance") == []


def test_triangular_cycle_rejected_when_depth_cannot_fill_size():
    strategy = TriangularStrategy(Settings(strategy_triangular_enabled=True))

    assert strategy.find_opportunities(_tri_books(eth_usd_qty=10.0), venue="binance") == []


def test_funding_opportunity_separates_apr_and_mark_risk():
    settings = Settings(strategy_funding_enabled=True, strategy_funding_hedge_cost_bps=5.0)
    strategy = FundingBasisStrategy(settings)
    spot = _book("kraken", "BTC/USD", "USD", bids=[(99.0, 1.0)], asks=[(101.0, 1.0)])
    rate = FundingRate(
        venue="binance_perp",
        symbol="BTC/USD",
        rate=0.0001,
        next_funding_ts=123.0,
        mark_price=101.0,
        index_price=100.5,
    )

    opps = strategy.find_opportunities([rate], {"kraken": spot})

    assert len(opps) == 1
    opp = opps[0]
    assert opp.funding_apr == pytest.approx(10.95)
    assert opp.expected_carry_apr == pytest.approx(10.90)
    assert opp.basis_bps == pytest.approx(100.0)
    assert opp.risk == "read_only_no_spot_pnl_mixing"


def test_mxn_normalization_uses_fx_rate_and_requires_it():
    strategy = RegionalMXNStrategy(
        Settings(strategy_regional_mxn_enabled=True, strategy_mxn_fiat_fee_bps=20.0)
    )
    mxn = _book(
        "bitso",
        "BTC/MXN",
        "MXN",
        bids=[(1_499_000.0, 1.0)],
        asks=[(1_501_000.0, 1.0)],
    )
    usd = _book("kraken", "BTC/USD", "USD", bids=[(69_900.0, 1.0)], asks=[(70_100.0, 1.0)])

    opp = strategy.compare(mxn, usd, usd_mxn=20.0)

    assert opp.btc_mxn_as_usd == pytest.approx(75_000.0)
    assert opp.gross_spread_usd == pytest.approx(5_000.0)
    assert opp.gross_spread_bps == pytest.approx(714.2857142857)
    assert opp.net_spread_bps == pytest.approx(694.2857142857)
    with pytest.raises(ValueError, match="fx rate is required"):
        strategy.compare(mxn, usd, usd_mxn=None)


def test_strategy_metrics_are_separated_for_new_modules():
    collector = MetricsCollector(Settings())
    collector.record_opportunity(
        Opportunity(
            id="tri-1",
            strategy=Strategy.triangular,
            symbol="USD triangular",
            buy_venue="binance",
            sell_venue="binance",
            status="viable",
        )
    )
    collector.record_opportunity(
        Opportunity(
            id="mxn-1",
            strategy=Strategy.regional_mxn,
            symbol="BTC/MXN",
            buy_venue="bitso",
            sell_venue="kraken",
            status="detected",
        )
    )

    snap = collector.snapshot({"detected": 2, "viable": 1})

    assert snap.by_strategy["triangular"]["viable"] == 1
    assert snap.by_strategy["regional_mxn"]["detected"] == 1


def test_strategy_endpoints_are_disabled_by_default(client):
    strategies = client.get("/api/v1/strategies").json()["strategies"]
    by_id = {item["id"]: item for item in strategies}
    assert by_id["spatial"]["enabled"] is True
    assert by_id["triangular"]["enabled"] is False
    assert by_id["funding_basis"]["enabled"] is False
    assert by_id["regional_mxn"]["enabled"] is False

    tri = client.get("/api/v1/strategies/triangular/opportunities").json()
    funding = client.get("/api/v1/strategies/funding/opportunities").json()
    mxn = client.get("/api/v1/strategies/regional/mxn").json()
    assert tri["enabled"] is False and tri["opportunities"] == []
    assert funding["enabled"] is False and funding["opportunities"] == []
    assert mxn["enabled"] is False and mxn["opportunities"] == []


def test_triangular_api_uses_live_books_when_enabled(client):
    ctx = client.app.state.ctx
    ctx.settings.strategy_triangular_enabled = True
    for book in _tri_books():
        ctx.latest_norm[f"{book.exchange}:{book.symbol}"] = book

    r = client.get("/api/v1/strategies/triangular/opportunities")

    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert len(body["opportunities"]) == 1
    assert body["opportunities"][0]["strategy"] == "triangular"
