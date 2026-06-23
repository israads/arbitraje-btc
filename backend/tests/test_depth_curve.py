"""PRD-007: DepthCurve debe reconciliar exactamente con walk_book."""
from __future__ import annotations

import math

import pytest

from app.engine.bookmath import walk_book
from app.engine.cost_model import compute_net, compute_net_from_curves
from app.engine.depth_curve import DepthCurve


def _assert_vwap_equal(levels: list[tuple[float, float]], q: float) -> None:
    curve = DepthCurve.from_levels(levels, "ask")
    expected = walk_book(levels, q)
    actual = curve.vwap(q)
    assert actual[0] == pytest.approx(expected[0])
    assert actual[1] == pytest.approx(expected[1])


def test_depth_curve_matches_walk_book_exact_fill() -> None:
    _assert_vwap_equal([(100.0, 0.5), (102.0, 0.5)], 1.0)


def test_depth_curve_matches_walk_book_partial_fill_inside_level() -> None:
    _assert_vwap_equal([(100.0, 0.5), (110.0, 2.0), (120.0, 3.0)], 1.25)


def test_depth_curve_empty_book() -> None:
    curve = DepthCurve.from_levels([], "bid")
    assert curve.depth == 0.0
    assert curve.best_price is None
    assert curve.vwap(1.0) == (0.0, 0.0)


def test_depth_curve_q_greater_than_depth_fills_available() -> None:
    _assert_vwap_equal([(100.0, 0.5), (102.0, 0.5)], 10.0)


def test_depth_curve_skips_invalid_levels_like_walk_book() -> None:
    levels = [
        (99.0, 0.0),
        (float("nan"), 1.0),
        (100.0, 0.5),
        (101.0, float("inf")),
        (102.0, 0.5),
    ]
    _assert_vwap_equal(levels, 1.0)


def test_depth_curve_preserves_input_order_like_walk_book() -> None:
    """No reordena niveles: el caller debe pasar asks asc. o bids desc., igual que walk_book."""
    levels = [(110.0, 0.5), (100.0, 0.5)]
    _assert_vwap_equal(levels, 0.75)


def test_compute_net_from_curves_matches_compute_net() -> None:
    asks = [(100.0, 0.5), (101.0, 1.0), (103.0, 2.0)]
    bids = [(110.0, 0.4), (109.0, 1.2), (107.0, 2.0)]
    ask_curve = DepthCurve.from_levels(asks, "ask")
    bid_curve = DepthCurve.from_levels(bids, "bid")
    for q in (0.0, 0.25, 1.0, 3.0, 10.0):
        old = compute_net(
            asks,
            bids,
            q,
            fee_buy=0.001,
            fee_sell=0.002,
            rebalance_btc=0.0001,
            top_ask=asks[0][0],
            top_bid=bids[0][0],
        )
        new = compute_net_from_curves(
            ask_curve,
            bid_curve,
            q,
            fee_buy=0.001,
            fee_sell=0.002,
            rebalance_btc=0.0001,
            top_ask=asks[0][0],
            top_bid=bids[0][0],
        )
        assert new == old


def test_depth_curve_outputs_are_finite_for_finite_books() -> None:
    curve = DepthCurve.from_levels([(100.0 + i, 0.1) for i in range(50)], "ask")
    vwap, filled = curve.vwap(2.5)
    assert math.isfinite(vwap)
    assert filled == pytest.approx(2.5)
