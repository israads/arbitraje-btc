"""Projection Suite v2 — Capa 1: Break-even Frontier (Execution-Conditioned).

Verifica forma e invariantes narrativos (demo determinista): el edge muere a fee alto y
sobrevive en una banda a fee bajo; P_survive ∈ [0,1]; 3 óptimos; modo live cae a demo sin books.
"""
from __future__ import annotations

import time

from app.models.market import NormalizedBook
from app.projection.frontier import build_edge_frontier, build_frontier


def test_frontier_shape_is_consistent():
    f = build_frontier(mode="demo")
    n_sizes = len(f.sizes_btc)
    n_tiers = len(f.fee_tiers)
    assert n_sizes >= 4 and n_tiers >= 3
    layers = (f.matrix, f.net_usd, f.p_survive, f.expected_edge, f.depth_limited, f.dominant_cost)
    for layer in layers:
        assert len(layer) == n_tiers
        assert all(len(row) == n_sizes for row in layer)


def test_retail_tier_never_captures():
    """El fee tier más caro (VIP0, 10 bps, primera fila) no captura en ningún tamaño."""
    f = build_frontier(mode="demo")
    retail = f.matrix[0]
    assert all(v is not None and v < 0 for v in retail)


def test_sweet_spot_exists_and_is_intermediate():
    """Existe edge unitario positivo (banda de supervivencia) en un tamaño intermedio."""
    f = build_frontier(mode="demo")
    best = f.best.by_unit_edge
    assert best is not None
    assert best.net_per_btc > 0
    assert best.size_btc not in (f.sizes_btc[0], f.sizes_btc[-1])


def test_three_optima_present():
    """F3: la frontier expone óptimo por edge unitario, total y ajustado a riesgo."""
    f = build_frontier(mode="demo")
    assert f.best.by_unit_edge is not None
    assert f.best.by_total_edge is not None
    assert f.best.by_risk_adjusted is not None


def test_p_survive_within_bounds():
    f = build_frontier(mode="demo")
    for row in f.p_survive:
        for p in row:
            assert p is None or (0.0 <= p <= 1.0)


def test_dominant_cost_labels_valid():
    f = build_frontier(mode="demo")
    valid = {"fees", "slippage", "rebalance", "none"}
    assert all(c in valid for row in f.dominant_cost for c in row)


def test_live_without_books_falls_back_to_demo():
    f = build_frontier(mode="live", books=None)
    assert f.mode == "demo"
    assert f.route is None


def test_live_with_books_picks_route():
    """Con books cruzados, modo live elige la ruta de mayor spread y la marca."""
    t = time.monotonic()
    books = {
        "binance": NormalizedBook(
            exchange="binance", symbol="BTC/USD", quote_ccy="USD",
            bids=[(69_990.0, 5.0)], asks=[(70_000.0, 5.0)], ts_recv_monotonic=t,
        ),
        "kraken": NormalizedBook(
            exchange="kraken", symbol="BTC/USD", quote_ccy="USD",
            bids=[(70_090.0, 5.0)], asks=[(70_100.0, 5.0)], ts_recv_monotonic=t,
        ),
    }
    f = build_frontier(None, books, mode="live")
    assert f.mode == "live"
    assert f.route == {"buy": "binance", "sell": "kraken", "symbol": "BTC/USD"}
    assert f.gross_top_per_btc > 0  # 70090 − 70000


def test_deterministic():
    a = build_frontier(mode="demo").matrix
    b = build_frontier(mode="demo").matrix
    assert a == b


def test_compat_build_edge_frontier_returns_dict():
    d = build_edge_frontier()
    assert isinstance(d, dict)
    assert "matrix" in d and "best" in d and "sizes_btc" in d


def test_legacy_validate_projection_shim_returns_v2_shape():
    """El import legado sigue vivo y delega a la Projection Suite v2."""
    from app.validate.projection import build_edge_frontier as legacy_build_edge_frontier

    d = legacy_build_edge_frontier()
    assert d["mode"] == "demo"
    assert "p_survive" in d and "expected_edge" in d
