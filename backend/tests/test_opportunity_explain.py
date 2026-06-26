from __future__ import annotations

import time

import pytest

from app.config import ExchangeConfig, Settings
from app.engine.evaluator import NetEvaluator
from app.models.enums import OpportunityStatus, Strategy
from app.models.market import NormalizedBook
from app.models.opportunity import Opportunity


def _settings(**over) -> Settings:
    base = dict(
        min_net_profit_usd=0.0,
        max_slippage=1.0,
        default_trade_qty_btc=1.0,
        exchanges={
            "binance": ExchangeConfig(
                id="binance", symbol="BTC/USDT", quote_ccy="USDT",
                fee_taker=0.0010, withdrawal_btc=0.0002, ob_limit=20,
            ),
            "kraken": ExchangeConfig(
                id="kraken", symbol="BTC/USD", quote_ccy="USD",
                fee_taker=0.0040, withdrawal_btc=0.00005, ob_limit=25,
            ),
        },
    )
    base.update(over)
    return Settings(**base)


def _book(ex: str, bids, asks, ts: float) -> NormalizedBook:
    return NormalizedBook(
        exchange=ex,
        symbol="BTC/USD",
        quote_ccy="USD",
        bids=bids,
        asks=asks,
        price_norm_factor=1.0,
        ts_recv_monotonic=ts,
    )


def _detected(oid: str = "opp-explain-1") -> Opportunity:
    return Opportunity(
        id=oid,
        strategy=Strategy.spatial,
        symbol="BTC/USD",
        buy_venue="binance",
        sell_venue="kraken",
        q_target=1.0,
        status=OpportunityStatus.detected,
    )


def _evaluated_opportunity() -> Opportunity:
    t = time.monotonic()
    ev = NetEvaluator(_settings())
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)], ts=t)
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)], ts=t)
    return ev.evaluate(_detected(), buy, sell)


def test_evaluator_attaches_explanation_without_changing_public_dump():
    opp = _evaluated_opportunity()

    assert opp.explanation is not None
    assert opp.explanation.naive.spread_usd_per_btc == pytest.approx(10.0)
    assert opp.explanation.naive.would_trade is True
    assert opp.explanation.engine.trades is True
    assert opp.explanation.engine.net_usd == pytest.approx(9.435)
    assert {c.key for c in opp.explanation.breakdown} >= {
        "gross", "fees_buy", "fees_sell", "slippage", "rebalance", "net",
    }

    dumped = opp.model_dump(mode="json")
    assert "explanation" not in dumped


def test_opportunity_explain_endpoint_returns_contract(client):
    opp = _evaluated_opportunity()
    client.app.state.ctx.record_opportunity(opp)

    r = client.get(f"/api/v1/opportunities/{opp.id}/explain")

    assert r.status_code == 200
    data = r.json()
    assert data["id"] == opp.id
    assert data["route"] == {
        "symbol": "BTC/USD",
        "buy_venue": "binance",
        "sell_venue": "kraken",
    }
    assert data["naive"]["would_trade"] is True
    assert data["engine"]["status"] == "viable"
    assert data["engine"]["net_usd"] == pytest.approx(9.435)
    assert [c["key"] for c in data["breakdown"]][-1] == "net"


def test_opportunity_what_if_recalculates_against_live_route_books(client):
    t = time.monotonic()
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)], ts=t)
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)], ts=t)
    opp = NetEvaluator(_settings()).evaluate(_detected("opp-what-if"), buy, sell)
    ctx = client.app.state.ctx
    ctx.latest_norm[buy.exchange] = buy
    ctx.latest_norm[sell.exchange] = sell
    ctx.record_opportunity(opp)

    r = client.post(
        f"/api/v1/opportunities/{opp.id}/what-if",
        json={"size_btc": 0.5, "fee_bps": 0.0, "max_slippage": 1.0},
    )

    assert r.status_code == 200
    data = r.json()
    assert data["opportunity_id"] == opp.id
    assert data["what_if"]["q_target"] == pytest.approx(0.5)
    assert data["what_if"]["engine"]["status"] == "viable"
    assert data["what_if"]["engine"]["net_usd"] == pytest.approx(4.975)
    assert "what_if" in data["what_if"]["notes"]


def test_opportunity_explain_endpoint_404_for_unknown_id(client):
    r = client.get("/api/v1/opportunities/missing/explain")
    assert r.status_code == 404


def test_opportunity_explain_endpoint_409_without_explanation(client):
    opp = _detected("no-explanation")
    client.app.state.ctx.record_opportunity(opp)

    r = client.get(f"/api/v1/opportunities/{opp.id}/explain")

    assert r.status_code == 409


def test_opportunities_endpoint_does_not_embed_explanation(client):
    opp = _evaluated_opportunity()
    client.app.state.ctx.record_opportunity(opp)

    r = client.get("/api/v1/opportunities")

    assert r.status_code == 200
    data = r.json()
    assert data["opportunities"][0]["id"] == opp.id
    assert "explanation" not in data["opportunities"][0]
