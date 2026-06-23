"""Profiling reproducible del motor/proyecciones (PRD-007).

Uso:
    uv run python scripts/profile_engine.py
    uv run python scripts/profile_engine.py --json
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Callable
from typing import Any

from app.config import get_settings
from app.engine.bookmath import walk_book
from app.engine.depth_curve import DepthCurve
from app.engine.evaluator import NetEvaluator
from app.models.enums import Strategy
from app.models.market import NormalizedBook
from app.models.opportunity import Opportunity
from app.projection.capacity import build_capacity_curve
from app.projection.frontier import build_frontier


def _levels(start: float, step: float, n: int, qty: float) -> list[tuple[float, float]]:
    return [(start + i * step, qty + (i % 5) * qty * 0.1) for i in range(n)]


ASKS = _levels(70_000.0, 0.5, 250, 0.05)
BIDS = _levels(70_100.0, -0.5, 250, 0.05)
QS = [0.05 + i * 0.03 for i in range(200)]


def _percentile(samples: list[float], q: float) -> float:
    ordered = sorted(samples)
    if not ordered:
        return 0.0
    rank = max(1, min(len(ordered), round(q / 100.0 * len(ordered) + 0.499999)))
    return ordered[rank - 1]


def _time_samples(fn: Callable[[], Any], iterations: int) -> list[float]:
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


def _summary(samples: list[float]) -> dict[str, float]:
    return {
        "p50_ms": _percentile(samples, 50),
        "p95_ms": _percentile(samples, 95),
        "p99_ms": _percentile(samples, 99),
        "mean_ms": statistics.fmean(samples) if samples else 0.0,
    }


def _profile_walk_vs_curve(iterations: int) -> dict[str, Any]:
    ask_curve = DepthCurve.from_levels(ASKS, "ask")
    walk_samples: list[float] = []
    curve_samples: list[float] = []
    max_abs_diff = 0.0
    for i in range(iterations):
        q = QS[i % len(QS)]
        t0 = time.perf_counter()
        w = walk_book(ASKS, q)
        walk_samples.append((time.perf_counter() - t0) * 1000.0)
        t0 = time.perf_counter()
        c = ask_curve.vwap(q)
        curve_samples.append((time.perf_counter() - t0) * 1000.0)
        max_abs_diff = max(max_abs_diff, abs(w[0] - c[0]), abs(w[1] - c[1]))
    walk = _summary(walk_samples)
    curve = _summary(curve_samples)
    return {
        "walk_book": walk,
        "depth_curve": curve,
        "speedup_p95": (
            walk["p95_ms"] / curve["p95_ms"] if curve["p95_ms"] > 0.0 else None
        ),
        "equivalence_max_abs_diff": max_abs_diff,
    }


def _profile_evaluator(iterations: int) -> dict[str, Any]:
    settings = get_settings().model_copy(deep=True)
    settings.default_trade_qty_btc = 1.0
    evaluator = NetEvaluator(settings)
    buy_book = NormalizedBook(
        exchange="binance",
        symbol="BTC/USD",
        quote_ccy="USD",
        bids=[(69_990.0, 1.0)],
        asks=ASKS,
        ts_recv_monotonic=1.0,
    )
    sell_book = NormalizedBook(
        exchange="kraken",
        symbol="BTC/USD",
        quote_ccy="USD",
        bids=BIDS,
        asks=[(70_110.0, 1.0)],
        ts_recv_monotonic=1.0,
    )

    def one() -> None:
        opp = Opportunity(
            id="profile",
            strategy=Strategy.spatial,
            symbol="BTC/USD",
            buy_venue="binance",
            sell_venue="kraken",
        )
        evaluator.evaluate(opp, buy_book, sell_book)

    t0 = time.perf_counter()
    samples = _time_samples(one, iterations)
    elapsed = time.perf_counter() - t0
    out = _summary(samples)
    out["ticks_processed_per_s"] = iterations / elapsed if elapsed > 0.0 else 0.0
    return out


def _profile_projection(iterations: int) -> dict[str, Any]:
    frontier_samples = _time_samples(lambda: build_frontier(mode="demo"), iterations)
    capacity_samples = _time_samples(lambda: build_capacity_curve(mode="demo"), iterations)
    return {
        "frontier_demo": _summary(frontier_samples),
        "capacity_demo": _summary(capacity_samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=2_000)
    parser.add_argument("--projection-iterations", type=int, default=100)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = {
        "walk_vs_depth_curve": _profile_walk_vs_curve(args.iterations),
        "evaluate": _profile_evaluator(args.iterations),
        "projection": _profile_projection(args.projection_iterations),
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    walk = result["walk_vs_depth_curve"]["walk_book"]
    curve = result["walk_vs_depth_curve"]["depth_curve"]
    evaluate = result["evaluate"]
    projection = result["projection"]
    print(f"ticks_processed_per_s={evaluate['ticks_processed_per_s']:.2f}")
    print(f"evaluate_p50_ms={evaluate['p50_ms']:.6f}")
    print(f"evaluate_p95_ms={evaluate['p95_ms']:.6f}")
    print(f"evaluate_p99_ms={evaluate['p99_ms']:.6f}")
    print(f"walk_book_p95_ms={walk['p95_ms']:.6f}")
    print(f"depth_curve_p95_ms={curve['p95_ms']:.6f}")
    speedup = result["walk_vs_depth_curve"]["speedup_p95"]
    print(f"depth_curve_speedup_p95={speedup:.2f}x" if speedup else "depth_curve_speedup_p95=n/a")
    print(
        "depth_curve_equivalence_max_abs_diff="
        f"{result['walk_vs_depth_curve']['equivalence_max_abs_diff']:.12f}"
    )
    print(f"projection_demo_p95_ms={projection['frontier_demo']['p95_ms']:.6f}")
    print(f"capacity_demo_p95_ms={projection['capacity_demo']['p95_ms']:.6f}")


if __name__ == "__main__":
    main()
