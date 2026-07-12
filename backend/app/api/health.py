"""`GET /health` — readiness para systemd/nginx/monitor (NFR-008).

Estado de feeds/conexiones/breakers se irá enriqueciendo en STORY-014/018.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, cast

from fastapi import APIRouter, Request

from ..models.enums import ConnectionStatus
from ..risk.watchdog import is_stale

router = APIRouter(tags=["ops"])


def _task_status(task: asyncio.Task[Any]) -> str:
    """Estado observable de una task del pipeline: `running`/`cancelled`/`failed`/`finished`.

    `failed` = terminó con excepción no cancelada → el subsistema murió y nadie lo reiniciará
    (NFR-008: un jurado/monitor debe poder detectarlo en /health, no en los logs)."""
    if not task.done():
        return "running"
    if task.cancelled():
        return "cancelled"
    return "failed" if task.exception() is not None else "finished"


def _operational_mode(ctx: Any) -> str:
    settings = ctx.settings
    demo = ctx.demo.status() if ctx.demo else {"active": False, "mode": "auto", "source": "live"}
    if demo.get("active"):
        if demo.get("mode") == "jury" or demo.get("source") == "deterministic":
            return "demo"
        return "replay"
    if settings.execution_mode == "testnet":
        return "testnet"
    if settings.execution_mode == "disabled":
        return "live_readonly"
    return cast(str, settings.execution_mode)


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        return {"status": "starting"}
    s = ctx.settings

    # Estado de feeds por venue (C1) + precio normalizado a USD (C3). El watchdog
    # completo de staleness es STORY-014.
    feeds: dict[str, dict[str, Any]] = {}
    now = time.monotonic()
    for ex in (e.id for e in s.enabled_exchanges):
        book = ctx.latest_books.get(ex)
        nb = ctx.latest_norm.get(ex)
        # Autoridad de estado = el watchdog (feed_status). Antes de su primer tick
        # (o con autostart off) se recomputa sobre latest_norm — la MISMA base que
        # usan el watchdog y el detector — para que /health nunca contradiga la
        # decisión real de trading (p.ej. raw fresco pero sin peg → no operable).
        status = ctx.feed_status.get(ex)
        if status is None:
            status = (
                ConnectionStatus.stale
                if nb is None or is_stale(nb.ts_recv_monotonic, now, s.staleness_ms)
                else ConnectionStatus.live
            )
        if book is None:
            feeds[ex] = {"book": False, "status": status.value, "age_ms": None}
            continue
        entry = {
            "book": True,
            "quote_ccy": book.quote_ccy,
            "age_ms": round((now - book.ts_recv_monotonic) * 1000, 1),
            "status": status.value,
            "best_bid": book.best_bid,
            "best_ask": book.best_ask,
        }
        if nb is not None:
            entry["usd_bid"] = nb.best_bid
            entry["usd_ask"] = nb.best_ask
        feeds[ex] = entry

    # Liveness de las tasks del pipeline (feeds/engine/watchdog/breakers/…): una task muerta
    # degrada el estado global — el proceso responde pero el subsistema ya no trabaja.
    tasks = {t.get_name(): _task_status(t) for t in ctx.tasks}
    if ctx.writer is not None:
        tasks["writer"] = "running" if ctx.writer.is_alive() else "failed"
    # RF-004 (PRD-011): CUALQUIER estado terminal degrada, no solo `failed`. Las tasks del
    # pipeline son bucles sin salida normal: `finished`/`cancelled` significan subsistema
    # muerto (p.ej. feeds retorna si TODOS los runners caen). No hay excepción de shutdown:
    # la cancelación ocurre en el finally del lifespan, cuando uvicorn ya no acepta
    # conexiones nuevas — una respuesta en vuelo que observe `cancelled` degrada bien y
    # después el proceso simplemente deja de responder (shutdown limpio = sin /health).
    degraded = any(st != "running" for st in tasks.values())

    return {
        "status": "degraded" if degraded else "ok",
        "app": s.app_name,
        "env": s.env,
        "version": request.app.version,
        "mode": _operational_mode(ctx),
        "execution_enabled": s.execution_mode != "disabled",
        "test_orders_enabled": s.execution_mode == "testnet" and s.enable_test_orders,
        "control_token_required": bool(s.control_token),
        "exchanges": [e.id for e in s.enabled_exchanges],
        "peg": ctx.peg.snapshot() if ctx.peg else {},
        "feeds": feeds,
        "integrity": ctx.integrity.reports() if ctx.integrity else {},
        "breakers": (
            ctx.breakers.status()
            if ctx.breakers
            else {"halted": False, "active": [], "breakers": []}
        ),
        "tasks": tasks,
        "funnel": ctx.opp_counts,
        "recent_opps": len(ctx.recent_opps),
        "sse_clients": ctx.hub.client_count,
        # C16 (STORY-024): fallback de demo — badge "DEMO DATA" cuando se reproduce grabación.
        "demo": ctx.demo.status() if ctx.demo else {"active": False, "source": "live"},
    }
