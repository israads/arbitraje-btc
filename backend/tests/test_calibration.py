"""PRD-005: calibración observe-only de supervivencia."""
from __future__ import annotations

from app.calibration import build_shadow_sample, build_survival_report, evaluate_survival
from app.config import ExchangeConfig, Settings
from app.models.calibration import ShadowOpportunitySample
from app.models.enums import OpportunityStatus, Strategy
from app.models.market import NormalizedBook
from app.models.opportunity import Opportunity


def _settings(**overrides: object) -> Settings:
    exchanges = {
        "buy": ExchangeConfig(
            id="buy",
            symbol="BTC/USD",
            quote_ccy="USD",
            fee_taker=0.0,
            withdrawal_btc=0.0,
            ob_limit=10,
        ),
        "sell": ExchangeConfig(
            id="sell",
            symbol="BTC/USD",
            quote_ccy="USD",
            fee_taker=0.0,
            withdrawal_btc=0.0,
            ob_limit=10,
        ),
    }
    return Settings(exchanges=exchanges, ingest_autostart=False, **overrides)


def _book(
    venue: str,
    *,
    ts: float,
    bid: float = 100.0,
    ask: float = 101.0,
    bid_qty: float = 2.0,
    ask_qty: float = 2.0,
) -> NormalizedBook:
    return NormalizedBook(
        exchange=venue,
        symbol="BTC/USD",
        quote_ccy="USD",
        bids=[(bid, bid_qty)],
        asks=[(ask, ask_qty)],
        price_norm_factor=1.0,
        ts_recv_monotonic=ts,
    )


def _opp(**overrides: object) -> Opportunity:
    data = {
        "id": "opp-1",
        "strategy": Strategy.spatial,
        "symbol": "BTC/USD",
        "buy_venue": "buy",
        "sell_venue": "sell",
        "q_target": 1.0,
        "vwap_buy": 100.0,
        "vwap_sell": 110.0,
        "fees": 1.0,
        "slippage": 0.0,
        "net_pnl": 9.0,
        "status": OpportunityStatus.viable,
        "t_detect": 1.0,
        "latency_ms": 0.4,
    }
    data.update(overrides)
    return Opportunity(**data)


def _sample(**overrides: object) -> ShadowOpportunitySample:
    data = {
        "id": "opp-1",
        "ts_detect": 1.0,
        "strategy": "spatial",
        "symbol": "BTC/USD",
        "buy_venue": "buy",
        "sell_venue": "sell",
        "q_target": 1.0,
        "gross_usd": 10.0,
        "net_usd": 9.0,
        "net_per_btc": 9.0,
        "fees_usd": 1.0,
        "slippage_usd": 0.0,
        "status": "viable",
    }
    data.update(overrides)
    return ShadowOpportunitySample(**data)


def test_shadow_sample_contains_required_features() -> None:
    settings = _settings()
    opp = _opp()
    sample = build_shadow_sample(
        opp,
        {"buy": _book("buy", ts=0.99), "sell": _book("sell", ts=0.98, bid=110.0)},
        settings,
        source="live",
    )
    assert sample.id == opp.id
    assert sample.net_usd == 9.0
    assert sample.net_per_btc == 9.0
    assert sample.book_age_buy_ms is not None
    assert sample.book_age_sell_ms is not None
    assert sample.spread_bps is not None
    assert sample.p_survive_estimated is not None
    assert {"spread_bps", "source", "peg_factor_buy", "peg_factor_sell"} <= set(sample.features)


def test_survival_observed_true_when_future_net_positive() -> None:
    obs = evaluate_survival(
        _sample(),
        [_book("buy", ts=1.1, ask=100.0), _book("sell", ts=1.1, bid=110.0)],
        [100],
        _settings(),
    )
    assert obs[0].observed is True
    assert obs[0].future_net_usd == 10.0


def test_survival_observed_false_when_future_net_negative() -> None:
    obs = evaluate_survival(
        _sample(),
        [_book("buy", ts=1.1, ask=100.0), _book("sell", ts=1.1, bid=99.0)],
        [100],
        _settings(),
    )
    assert obs[0].observed is False
    assert obs[0].future_net_usd == -1.0


def test_survival_missing_future_book() -> None:
    obs = evaluate_survival(_sample(), [_book("buy", ts=1.1)], [100], _settings())
    assert obs[0].observed is None
    assert obs[0].reason == "missing_future_book"


def test_survival_does_not_use_ticks_before_target() -> None:
    obs = evaluate_survival(
        _sample(),
        [
            _book("buy", ts=1.05, ask=100.0),
            _book("sell", ts=1.05, bid=200.0),
            _book("buy", ts=1.1, ask=100.0),
            _book("sell", ts=1.1, bid=99.0),
        ],
        [100],
        _settings(),
    )
    assert obs[0].observed is False
    assert obs[0].future_net_usd == -1.0


def test_calibration_bucket_counts() -> None:
    settings = _settings()
    samples = [_sample(id="a", net_per_btc=20.0), _sample(id="b", net_per_btc=20.0)]
    ticks = [
        _book("buy", ts=1.1, ask=100.0),
        _book("sell", ts=1.1, bid=110.0),
        _book("buy", ts=1.2, ask=100.0),
        _book("sell", ts=1.2, bid=110.0),
    ]
    report = build_survival_report(samples, ticks, settings, latency_ms=100)
    assert report.n_samples == 2
    assert report.n_observed == 2
    assert sum(bucket.n for bucket in report.buckets) == 2
    assert any(bucket.observed_rate == 1.0 for bucket in report.buckets)


def test_calibration_endpoint_contract(client) -> None:
    ctx = client.app.state.ctx
    ctx.record_shadow_sample(_sample())
    ctx.recorder.record(_book("buy", ts=1.1, ask=100.0))
    ctx.recorder.record(_book("sell", ts=1.1, bid=110.0))
    r = client.get("/api/v1/calibration/survival?latency_ms=100")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "observe_only"
    assert body["latency_ms"] == 100
    assert body["n_samples"] == 1
    assert body["n_observed"] == 1
    assert len(body["buckets"]) == 5


def test_observe_only_does_not_change_decisions() -> None:
    settings = _settings()
    opp = _opp(status=OpportunityStatus.viable)
    before = opp.model_dump(mode="json")
    sample = build_shadow_sample(
        opp,
        {"buy": _book("buy", ts=0.9), "sell": _book("sell", ts=0.9)},
        settings,
    )
    build_survival_report(
        [sample],
        [_book("buy", ts=1.1, ask=100.0), _book("sell", ts=1.1, bid=90.0)],
        settings,
        latency_ms=100,
    )
    assert opp.model_dump(mode="json") == before
