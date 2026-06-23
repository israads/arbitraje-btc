"""Prometheus text exposition for operational metrics (PRD-006)."""
from __future__ import annotations

import math
import time
from typing import Any, cast

from ..models.enums import OpportunityStatus
from ..models.metrics import MetricsSnapshot


def _escape_label(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_value(value: object) -> str | None:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return format(value, ".17g")
    return None


def render_prometheus(ctx: Any) -> str:
    """Renderiza métricas de `AppState` en formato Prometheus 0.0.4.

    Lee las mismas fuentes que `/health` y `/api/v1/metrics`; no abre red, no serializa
    secretos y mantiene labels de cardinalidad acotada.
    """
    lines: list[str] = []
    declared: set[str] = set()

    def declare(name: str, typ: str, help_text: str) -> None:
        if name in declared:
            return
        declared.add(name)
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {typ}")

    def sample(
        name: str,
        value: object,
        *,
        labels: dict[str, object] | None = None,
        typ: str = "gauge",
        help_text: str = "",
    ) -> None:
        formatted = _format_value(value)
        if formatted is None:
            return
        declare(name, typ, help_text or name)
        if labels:
            label_text = ",".join(f'{k}="{_escape_label(v)}"' for k, v in sorted(labels.items()))
            lines.append(f"{name}{{{label_text}}} {formatted}")
        else:
            lines.append(f"{name} {formatted}")

    sample("arb_up", 1, help_text="Exporter is able to render application state.")

    funnel = getattr(ctx, "opp_counts", {})
    collector = getattr(ctx, "metrics", None)
    if collector is None:
        snap = MetricsSnapshot(
            detected=funnel.get(OpportunityStatus.detected.value, 0),
            viable=funnel.get(OpportunityStatus.viable.value, 0),
            executable=funnel.get(OpportunityStatus.executable.value, 0),
            captured=funnel.get(OpportunityStatus.captured.value, 0),
            discarded=funnel.get(OpportunityStatus.discarded.value, 0),
            unwound=funnel.get("unwound", 0),
        )
    else:
        snap = collector.snapshot(funnel)
    data = snap.model_dump(mode="json")

    for status in ("detected", "viable", "executable", "captured", "discarded", "unwound"):
        sample(
            f"arb_opportunities_{status}_total",
            data.get(status, 0),
            typ="counter",
            help_text=f"Opportunity funnel counter for status {status}.",
        )
        sample(
            "arb_opportunities_total",
            data.get(status, 0),
            labels={"status": status},
            typ="counter",
            help_text="Opportunity funnel counters by lifecycle status.",
        )

    for reason, count in data.get("discard_reasons", {}).items():
        sample(
            "arb_opportunities_discarded_total",
            count,
            labels={"reason": reason},
            typ="counter",
            help_text="Discarded opportunities by bounded reason.",
        )
        sample(
            "arb_discard_total",
            count,
            labels={"reason": reason},
            typ="counter",
            help_text="Discarded opportunities by bounded reason.",
        )

    for strategy, statuses in data.get("by_strategy", {}).items():
        for status, count in statuses.items():
            sample(
                "arb_strategy_opportunities_total",
                count,
                labels={"strategy": strategy, "status": status},
                typ="counter",
                help_text="Opportunity counters by strategy and lifecycle status.",
            )

    for venue, results in data.get("preflight_results", {}).items():
        for result, count in results.items():
            sample(
                "arb_preflight_total",
                count,
                labels={"venue": venue, "result": result},
                typ="counter",
                help_text="Execution preflight requests by venue and result.",
            )

    for venue, results in data.get("test_order_results", {}).items():
        for result, count in results.items():
            sample(
                "arb_test_order_total",
                count,
                labels={"venue": venue, "result": result},
                typ="counter",
                help_text="Execution test-order requests by venue and result.",
            )

    for stage_key in ("detect_latency", "exec_latency"):
        stage = data.get(stage_key)
        if not stage:
            continue
        labels = {"stage": stage["stage"]}
        sample(
            "arb_latency_ms",
            stage.get("p50_ms"),
            labels={**labels, "quantile": "0.50"},
            help_text="Pipeline latency percentiles in milliseconds.",
        )
        sample(
            "arb_latency_ms",
            stage.get("p99_ms"),
            labels={**labels, "quantile": "0.99"},
            help_text="Pipeline latency percentiles in milliseconds.",
        )
        prd_name = (
            "arb_engine_detect_latency_ms"
            if stage["stage"] == "detect"
            else "arb_execution_latency_ms"
        )
        sample(
            prd_name,
            stage.get("p50_ms"),
            labels={"quantile": "0.50"},
            help_text="PRD-006 latency percentile alias in milliseconds.",
        )
        sample(
            prd_name,
            stage.get("p99_ms"),
            labels={"quantile": "0.99"},
            help_text="PRD-006 latency percentile alias in milliseconds.",
        )
        sample(
            "arb_latency_max_ms",
            stage.get("max_ms"),
            labels=labels,
            help_text="Maximum observed pipeline latency in milliseconds.",
        )
        sample(
            "arb_latency_samples",
            stage.get("count"),
            labels=labels,
            help_text="Latency sample count in the current process window.",
        )

    for key in ("effective_spread", "expected_net_spread", "realized_spread", "price_impact"):
        sample(
            "arb_spread_usd_per_btc",
            data.get(key),
            labels={"kind": key},
            help_text="Spread and impact metrics in USD per BTC.",
        )
    sample("arb_capture_ratio", data.get("capture_ratio"), help_text="Captured over detected.")
    sample("arb_fill_ratio", data.get("fill_ratio"), help_text="Average matched quantity ratio.")
    sample(
        "arb_opportunity_lifetime_ms",
        data.get("opp_lifetime_p50_ms"),
        labels={"quantile": "0.50"},
        help_text="Opportunity lifetime percentiles in milliseconds.",
    )
    sample(
        "arb_opportunity_lifetime_ms",
        data.get("opp_lifetime_p99_ms"),
        labels={"quantile": "0.99"},
        help_text="Opportunity lifetime percentiles in milliseconds.",
    )

    integrity = getattr(ctx, "integrity", None)
    if integrity is not None:
        for exchange, report in integrity.reports().items():
            base = {"exchange": exchange, "validator": report.get("validator", "generic")}
            sample(
                "arb_integrity_accepted_total",
                report.get("accepted", 0),
                labels=base,
                typ="counter",
                help_text="Accepted order books by exchange integrity validator.",
            )
            sample(
                "arb_integrity_rejected_total",
                report.get("rejected", 0),
                labels={**base, "reason": report.get("last_reason") or "none"},
                typ="counter",
                help_text="Rejected order books by exchange integrity validator.",
            )
            sample(
                "arb_integrity_sequence_gaps_total",
                report.get("sequence_gaps", 0),
                labels=base,
                typ="counter",
                help_text="Observed sequence gaps by exchange integrity validator.",
            )
            sample(
                "arb_integrity_checksum_failures_total",
                report.get("checksum_failures", 0),
                labels=base,
                typ="counter",
                help_text="Observed checksum failures by exchange integrity validator.",
            )

    breakers = getattr(ctx, "breakers", None)
    breaker_status = breakers.status() if breakers is not None else {
        "halted": False,
        "active": [],
        "breakers": [],
    }
    sample("arb_breaker_halted", breaker_status.get("halted", False), help_text="Global halt flag.")
    breaker_items = breaker_status.get("breakers", [])
    if not isinstance(breaker_items, list):
        breaker_items = []
    for breaker_obj in breaker_items:
        if not isinstance(breaker_obj, dict):
            continue
        breaker = cast(dict[str, Any], breaker_obj)
        sample(
            "arb_breaker_active",
            breaker.get("active", False),
            labels={"type": breaker.get("type", "unknown")},
            help_text="Circuit breaker active state by type.",
        )

    demo = getattr(ctx, "demo", None)
    demo_status = demo.status() if demo is not None else {
        "active": False,
        "mode": "auto",
        "source": "live",
        "n_replay_ticks": 0,
    }
    sample(
        "arb_demo_active",
        demo_status.get("active", False),
        labels={
            "mode": demo_status.get("mode", "auto"),
            "source": demo_status.get("source", "live"),
        },
        help_text="Demo fallback active state.",
    )
    sample(
        "arb_demo_replay_ticks",
        demo_status.get("n_replay_ticks", 0),
        help_text="Ticks available for demo replay.",
    )

    settings = getattr(ctx, "settings", None)
    now = time.monotonic()
    if settings is not None:
        sample(
            "arb_execution_enabled",
            settings.execution_mode != "disabled",
            help_text="Protected execution layer enabled flag.",
        )
        sample(
            "arb_test_orders_enabled",
            settings.execution_mode == "testnet" and settings.enable_test_orders,
            help_text="Test order endpoint enabled flag.",
        )
        latest_books = getattr(ctx, "latest_books", {})
        latest_norm = getattr(ctx, "latest_norm", {})
        feed_status = getattr(ctx, "feed_status", {})
        for exchange in (cfg.id for cfg in settings.enabled_exchanges):
            status_obj = feed_status.get(exchange)
            feed_status_value = cast(str | None, getattr(status_obj, "value", None))
            if feed_status_value is None:
                feed_status_value = "live" if exchange in latest_norm else "unknown"
            sample(
                "arb_feed_live",
                1 if feed_status_value == "live" else 0,
                labels={"exchange": exchange},
                help_text="Whether the exchange feed is live.",
            )
            sample(
                "arb_feed_status",
                1,
                labels={"exchange": exchange, "status": feed_status_value},
                help_text="Current feed status, one sample per exchange/status.",
            )
            book = latest_books.get(exchange)
            if book is not None:
                age_ms = (now - book.ts_recv_monotonic) * 1000.0
                sample(
                    "arb_book_age_ms",
                    age_ms,
                    labels={"exchange": exchange},
                    help_text="Raw book age in milliseconds.",
                )
                sample(
                    "arb_feed_book_age_ms",
                    age_ms,
                    labels={"exchange": exchange},
                    help_text="Raw book age in milliseconds.",
                )

    return "\n".join(lines) + "\n"
