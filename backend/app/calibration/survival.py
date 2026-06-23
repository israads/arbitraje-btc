"""Evaluación observe-only de supervivencia con ticks futuros del recorder."""
from __future__ import annotations

from collections.abc import Sequence

from ..config import Settings
from ..engine.cost_model import compute_net
from ..models.calibration import (
    CalibrationConfidence,
    ShadowOpportunitySample,
    SurvivalCalibrationBucket,
    SurvivalCalibrationReport,
    SurvivalObservation,
)
from ..models.market import NormalizedBook
from ..projection.survival import p_survive

_BUCKETS: tuple[tuple[float, float], ...] = (
    (0.0, 0.2),
    (0.2, 0.4),
    (0.4, 0.6),
    (0.6, 0.8),
    (0.8, 1.0000001),
)


def _confidence(n: int) -> CalibrationConfidence:
    if n >= 100:
        return "high"
    if n >= 30:
        return "medium"
    return "low"


def _fee(settings: Settings, venue: str) -> float:
    cfg = settings.exchanges.get(venue)
    return cfg.fee_taker if cfg is not None else 0.0


def _withdrawal(settings: Settings, venue: str) -> float:
    cfg = settings.exchanges.get(venue)
    return cfg.withdrawal_btc if cfg is not None else 0.0


def _future_book(
    ticks: Sequence[NormalizedBook], venue: str, target_ts: float
) -> NormalizedBook | None:
    for tick in ticks:
        if tick.exchange == venue and tick.ts_recv_monotonic >= target_ts:
            return tick
    return None


def evaluate_survival(
    sample: ShadowOpportunitySample,
    ticks: Sequence[NormalizedBook],
    latencies_ms: Sequence[int],
    settings: Settings,
) -> list[SurvivalObservation]:
    """Evalúa si una muestra sobrevive a cada latencia sin usar ticks anteriores al target."""
    out: list[SurvivalObservation] = []
    ordered = sorted(ticks, key=lambda nb: nb.ts_recv_monotonic)
    for latency in latencies_ms:
        target_ts = sample.ts_detect + latency / 1000.0
        buy_book = _future_book(ordered, sample.buy_venue, target_ts)
        sell_book = _future_book(ordered, sample.sell_venue, target_ts)
        if buy_book is None or sell_book is None:
            out.append(
                SurvivalObservation(
                    opportunity_id=sample.id,
                    latency_ms=latency,
                    observed=None,
                    reason="missing_future_book",
                )
            )
            continue
        breakdown = compute_net(
            buy_book.asks,
            sell_book.bids,
            sample.q_target,
            fee_buy=_fee(settings, sample.buy_venue),
            fee_sell=_fee(settings, sample.sell_venue),
            rebalance_btc=(
                _withdrawal(settings, sample.buy_venue)
                + _withdrawal(settings, sample.sell_venue)
            )
            / settings.expected_trades_per_rebalance,
            top_ask=buy_book.best_ask,
            top_bid=sell_book.best_bid,
        )
        survived = breakdown.net > settings.min_net_profit_usd
        out.append(
            SurvivalObservation(
                opportunity_id=sample.id,
                latency_ms=latency,
                observed=survived,
                future_net_usd=breakdown.net,
            )
        )
    return out


def _bucket_index(p: float) -> int:
    for idx, (low, high) in enumerate(_BUCKETS):
        if low <= p < high:
            return idx
    return len(_BUCKETS) - 1


def build_survival_report(
    samples: Sequence[ShadowOpportunitySample],
    ticks: Sequence[NormalizedBook],
    settings: Settings,
    *,
    latency_ms: int,
    observation_limit: int = 50,
) -> SurvivalCalibrationReport:
    observations: list[SurvivalObservation] = []
    bucket_hits: list[list[bool]] = [[] for _ in _BUCKETS]
    for sample in samples:
        obs = evaluate_survival(sample, ticks, [latency_ms], settings)[0]
        observations.append(obs)
        if obs.observed is None or sample.net_per_btc is None:
            continue
        estimate = p_survive(sample.net_per_btc, latency_ms)
        bucket_hits[_bucket_index(estimate)].append(obs.observed)

    buckets: list[SurvivalCalibrationBucket] = []
    for idx, (low, high) in enumerate(_BUCKETS):
        hits = bucket_hits[idx]
        n = len(hits)
        observed_rate = (sum(1 for h in hits if h) / n) if n else None
        estimated_mid = min(1.0, (low + min(high, 1.0)) / 2.0)
        abs_error = (
            abs(observed_rate - estimated_mid) if observed_rate is not None else None
        )
        buckets.append(
            SurvivalCalibrationBucket(
                p_low=low,
                p_high=min(high, 1.0),
                n=n,
                estimated_mid=estimated_mid,
                observed_rate=observed_rate,
                abs_error=abs_error,
                confidence=_confidence(n),
            )
        )

    n_observed = sum(1 for obs in observations if obs.observed is not None)
    return SurvivalCalibrationReport(
        mode=settings.calibration_mode,
        latency_ms=latency_ms,
        n_samples=len(samples),
        n_observed=n_observed,
        n_missing=len(observations) - n_observed,
        confidence=_confidence(n_observed),
        buckets=buckets,
        observations=observations[-observation_limit:] if observation_limit > 0 else [],
    )
