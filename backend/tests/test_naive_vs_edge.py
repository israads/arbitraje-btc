from __future__ import annotations

from app.analysis import build_naive_vs_edge
from app.config import ExchangeConfig, Settings
from app.models.enums import DiscardReason, OpportunityStatus, Strategy
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
        },
    )
    base.update(over)
    return Settings(**base)


def _opp(
    oid: str,
    *,
    vwap_buy: float | None,
    vwap_sell: float | None,
    status: OpportunityStatus,
    q: float = 1.0,
    net: float | None = None,
    discard: DiscardReason | None = None,
) -> Opportunity:
    return Opportunity(
        id=oid,
        strategy=Strategy.spatial,
        symbol="BTC/USD",
        buy_venue="binance",
        sell_venue="kraken",
        q_target=q,
        vwap_buy=vwap_buy,
        vwap_sell=vwap_sell,
        net_pnl=net,
        status=status,
        discard_reason=discard,
    )


def test_empty_session_yields_zeroed_report() -> None:
    rep = build_naive_vs_edge([], _settings())
    assert rep.sample_size == 0
    assert rep.naive_trades == 0
    assert rep.engine_trades == 0
    assert rep.survival_rate is None
    assert rep.dominant_rejection is None
    assert "todavia" in rep.headline


def test_naive_counts_positive_gross_engine_counts_captured() -> None:
    opps = [
        # captured: ingenuo y motor cuentan
        _opp("a", vwap_buy=100.0, vwap_sell=130.0, status=OpportunityStatus.captured, net=12.0),
        # discarded por fees: ingenuo lo tradearia, motor no
        _opp(
            "b", vwap_buy=100.0, vwap_sell=125.0,
            status=OpportunityStatus.discarded, discard=DiscardReason.not_profitable_fees,
        ),
        # spread negativo: ni el ingenuo lo tradea
        _opp("c", vwap_buy=100.0, vwap_sell=95.0, status=OpportunityStatus.discarded),
    ]
    rep = build_naive_vs_edge(opps, _settings())
    assert rep.sample_size == 3
    assert rep.naive_trades == 2          # a y b (spread > 0); c excluida
    assert rep.naive_gross_usd == 30.0 + 25.0
    assert rep.engine_trades == 1         # solo a capturada
    assert rep.engine_net_usd == 12.0
    assert rep.naive_gross_per_btc == 55.0 / 2.0
    assert rep.engine_net_per_btc == 12.0
    assert rep.survival_rate == 0.5
    assert rep.overstatement_usd == 55.0 - 12.0


def test_rejections_grouped_and_dominant_by_count() -> None:
    opps = [
        _opp(
            f"fees-{i}", vwap_buy=100.0, vwap_sell=110.0,
            status=OpportunityStatus.discarded, discard=DiscardReason.not_profitable_fees,
        )
        for i in range(3)
    ]
    opps.append(
        _opp(
            "peg", vwap_buy=100.0, vwap_sell=120.0,
            status=OpportunityStatus.discarded, discard=DiscardReason.peg_adverse,
        )
    )
    rep = build_naive_vs_edge(opps, _settings())
    assert rep.dominant_rejection == DiscardReason.not_profitable_fees.value
    top = rep.rejections[0]
    assert top.count == 3
    assert top.lost_gross_usd == 30.0
    assert top.label == "No rentable tras fees"
    assert len(rep.rejections) == 2


def test_missing_vwap_is_ignored_for_naive() -> None:
    opps = [_opp("x", vwap_buy=None, vwap_sell=120.0, status=OpportunityStatus.discarded)]
    rep = build_naive_vs_edge(opps, _settings())
    assert rep.naive_trades == 0
    assert rep.naive_gross_usd == 0.0
    assert rep.naive_gross_per_btc is None
