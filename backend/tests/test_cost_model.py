"""engine/cost_model — fuente única de la economía de un cruce.

Determinista. Verifica la identidad del neto, la descomposición, el coste dominante y que
reproduce EXACTAMENTE el cálculo del evaluador (anti-drift).
"""
from __future__ import annotations

import pytest

from app.engine.cost_model import compute_net


def test_net_identity_holds():
    """net == gross − fees − rebalance, con la descomposición coherente."""
    nb = compute_net(
        [(100.0, 5.0)], [(110.0, 5.0)], 1.0,
        fee_buy=0.0010, fee_sell=0.0040, rebalance_btc=0.00025,
        top_ask=100.0, top_bid=110.0,
    )
    assert nb.filled == 1.0
    assert nb.gross == pytest.approx((110.0 - 100.0) * 1.0)
    assert nb.fees == pytest.approx(100.0 * 0.0010 + 110.0 * 0.0040)
    assert nb.rebalance == pytest.approx(0.00025 * 100.0)
    assert nb.net == pytest.approx(nb.gross - nb.fees - nb.rebalance)
    assert nb.net_per_btc == pytest.approx(nb.net / nb.filled)


def test_no_liquidity_returns_empty():
    nb = compute_net([], [(110.0, 5.0)], 1.0, fee_buy=0.0, fee_sell=0.0)
    assert nb.filled == 0.0 and nb.net == 0.0 and nb.dominant_cost == "none"


def test_depth_limited_flag():
    nb = compute_net([(100.0, 0.3)], [(110.0, 5.0)], 1.0, fee_buy=0.0, fee_sell=0.0)
    assert nb.filled == pytest.approx(0.3)
    assert nb.depth_limited is True


def test_slippage_vs_top():
    """VWAP por encima del top ⇒ slippage_buy>0; slippage_cost agregado en USD."""
    nb = compute_net(
        [(100.0, 0.5), (102.0, 0.5)], [(120.0, 0.5), (118.0, 0.5)], 1.0,
        fee_buy=0.0, fee_sell=0.0, top_ask=100.0, top_bid=120.0,
    )
    assert nb.vwap_buy == pytest.approx(101.0)
    assert nb.vwap_sell == pytest.approx(119.0)
    assert nb.slippage_buy == pytest.approx(1.0)   # 101 − 100
    assert nb.slippage_sell == pytest.approx(1.0)  # 120 − 119
    assert nb.slippage_cost == pytest.approx(2.0)  # (1+1)*1


def test_dominant_cost_picks_largest():
    # fees dominan: fee alto, rebalance bajo, sin slippage.
    nb = compute_net(
        [(100.0, 5.0)], [(110.0, 5.0)], 1.0,
        fee_buy=0.05, fee_sell=0.05, rebalance_btc=0.00001, top_ask=100.0, top_bid=110.0,
    )
    assert nb.dominant_cost == "fees"


def test_matches_evaluator_arithmetic():
    """Anti-drift: el cost_model reproduce el neto del evaluador en el escenario tesis del reto
    (gross $12 < fees $500 → net −$513.048)."""
    nb = compute_net(
        [(100_000.0, 5.0)], [(100_012.0, 5.0)], 1.0,
        fee_buy=0.0010, fee_sell=0.0040,
        rebalance_btc=(0.0002 + 0.00005), top_ask=100_000.0, top_bid=100_012.0,
    )
    assert nb.fees == pytest.approx(500.048)
    assert nb.rebalance == pytest.approx(25.0)
    assert nb.net == pytest.approx(-513.048)
