"""Router `/api/v1`. SSE (C11) push de `quote`/`opportunity`; REST de snapshot en
vivo (`/quotes`, `/opportunities`). El resto son stubs hasta su story."""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from ...models.metrics import MetricsSnapshot

router = APIRouter()
log = logging.getLogger("app.api.v1")


def require_control_token(
    request: Request, x_control_token: str | None = Header(default=None)
) -> None:
    """Auth mínima de los endpoints de control. Si `settings.control_token` está vacío (dev),
    pasa siempre; si está set, exige el header `X-Control-Token` exacto. Lee el token del
    `ctx.settings` inyectado en el lifespan (respeta los settings de tests)."""
    ctx = request.app.state.ctx
    expected = getattr(getattr(ctx, "settings", None), "control_token", "") or ""
    if expected and x_control_token != expected:
        raise HTTPException(status_code=401, detail="invalid or missing X-Control-Token")


def _latest_book_ts(books: dict[str, Any]) -> float:
    """`ts_exchange` más reciente entre los libros normalizados (sello del snapshot). Sin
    libros o sin ts → 0.0 (determinista, sin leer reloj real en la respuesta)."""
    tss = [nb.ts_exchange for nb in books.values() if nb.ts_exchange is not None]
    return max(tss) if tss else 0.0


def _live_projection_books(ctx: Any) -> dict[str, Any] | None:
    """Libros vivos para la Projection Suite.

    `AppState` no expone `ctx.books`: el motor mantiene el estado operable en
    `ctx.detector.books` y el snapshot normalizado inicial en `ctx.latest_norm`. Usar ambos
    evita que `mode=live` caiga a demo mientras sí hay datos vivos.
    """
    detector = getattr(ctx, "detector", None)
    detector_books = getattr(detector, "books", None)
    if detector_books:
        return cast(dict[str, Any], detector_books)
    latest_norm = getattr(ctx, "latest_norm", None)
    if latest_norm:
        return cast(dict[str, Any], latest_norm)
    return None


@router.get("/stream")
async def stream(request: Request) -> EventSourceResponse:
    """SSE. Emite los eventos publicados en el hub (C11): `quote`, `opportunity`
    (y `execution`/`pnl`/`metrics` en stories posteriores). Cola por cliente +
    corte por desconexión."""
    ctx = request.app.state.ctx

    async def gen() -> AsyncGenerator[dict[str, str], None]:
        async for ev in ctx.hub.subscribe():
            if await request.is_disconnected():
                break
            yield {"event": ev.type, "data": json.dumps(ev.data)}

    return EventSourceResponse(
        gen(),
        ping=ctx.settings.sse_ping_seconds,
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.get("/quotes")
async def quotes(request: Request) -> dict[str, Any]:
    """Snapshot actual normalizado a USD por exchange (estado inicial del dashboard)."""
    ctx = request.app.state.ctx
    out = []
    for ex, nb in ctx.latest_norm.items():
        out.append({
            "exchange": ex,
            "symbol": nb.symbol,
            "quote_ccy": nb.quote_ccy,
            "usd_bid": nb.best_bid,
            "usd_ask": nb.best_ask,
            "price_norm_factor": nb.price_norm_factor,
            "ts_exchange": nb.ts_exchange,
        })
    return {"quotes": out, "peg": ctx.peg.snapshot() if ctx.peg else {}}


@router.get("/opportunities")
async def opportunities(
    request: Request, status: str | None = None, limit: int = 100
) -> dict[str, Any]:
    """Oportunidades recientes (embudo en vivo). El historial persistente es STORY-011."""
    ctx = request.app.state.ctx
    items = list(ctx.recent_opps)
    if status:
        items = [o for o in items if o.status.value == status]
    items = items[-limit:]
    return {
        "funnel": ctx.opp_counts,
        "opportunities": [o.model_dump(mode="json") for o in reversed(items)],
    }


# --- Stubs REST (implementación por story) ---

@router.get("/executions")
async def executions(
    request: Request, limit: int = Query(100, ge=1, le=1000)
) -> dict[str, Any]:
    """Historial persistido de ejecuciones simuladas (C12 / STORY-011).

    Devuelve las últimas `limit` ejecuciones de la DB, ordenadas cronológicamente.
    `limit` acotado a [1, 1000] (evita LIMIT -1 / DoS). Retrocompatible: si el
    writer no está inicializado devuelve lista vacía.
    """
    ctx = request.app.state.ctx
    writer = getattr(ctx, "writer", None)
    if writer is None:
        return {"executions": [], "count": 0}
    rows = await writer.get_executions(limit=limit)
    return {"executions": rows, "count": len(rows)}


@router.get("/opportunities/history")
async def opportunities_history(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    status: str | None = None,
) -> dict[str, Any]:
    """Historial persistido de oportunidades (C12 / STORY-011).

    A diferencia de `/opportunities` (buffer en memoria), este endpoint
    lee de la DB por lo que sobrevive reinicios y soporta paginación mayor.
    `limit` acotado a [1, 1000] (evita LIMIT -1 / DoS).
    """
    ctx = request.app.state.ctx
    writer = getattr(ctx, "writer", None)
    if writer is None:
        return {"opportunities": [], "count": 0}
    rows = await writer.get_opportunities(limit=limit, status=status)
    return {"opportunities": rows, "count": len(rows)}


@router.get("/balances")
async def balances(request: Request) -> dict[str, Any]:
    """Balances vivos por (venue, activo) + equity por venue y skew de inventario (C10).

    Inventario pre-posicionado con doble entrada: el snapshot incluye la equity total
    marcada a mercado contra el libro normalizado actual de cada venue."""
    ctx = request.app.state.ctx
    pf = getattr(ctx, "portfolio", None)
    if pf is None:
        # Autostart deshabilitado (p.ej. tests): cartera no inicializada → vacío honesto.
        return {"balances": [], "equity_by_venue": {}, "skew": {}, "snapshot": None}
    books = ctx.latest_norm
    ts = _latest_book_ts(books)
    snap = pf.snapshot(books, ts=ts)
    return {
        "balances": [b.model_dump() for b in pf.balances()],
        "equity_by_venue": pf.equity_by_venue(books),
        "equity_usd": pf.equity_total(books),
        "skew": pf.inventory_skew(),
        "snapshot": snap.model_dump(mode="json"),
    }


@router.get("/pnl")
async def pnl(request: Request) -> dict[str, Any]:
    """P&L vivo (C10): realized (tramo casado) + unrealized (inventario marcado a mercado)
    + total, equity y la serie de equity (timeline) para la equity curve del dashboard
    (STORY-023). El P&L plano/levemente negativo tras costes ES el punto (honestidad)."""
    ctx = request.app.state.ctx
    pf = getattr(ctx, "portfolio", None)
    if pf is None:
        return {
            "realized_pnl": 0.0, "unrealized_pnl": 0.0, "total_pnl": 0.0,
            "equity_usd": 0.0, "equity_series": [], "skew": {},
        }
    summary: dict[str, Any] = pf.pnl_summary(ctx.latest_norm)
    return summary


@router.get("/control/status")
async def control_status(request: Request) -> dict[str, Any]:
    """Estado de los circuit breakers + kill switch (C8 / STORY-018, FR-012).

    `{halted, active:[...], breakers:[{type, active, reason, since}]}`. Autostart-safe: sin
    manager inicializado devuelve `halted=false` sin breakers."""
    ctx = request.app.state.ctx
    breakers = getattr(ctx, "breakers", None)
    if breakers is None:
        return {"halted": False, "active": [], "breakers": []}
    status: dict[str, Any] = breakers.status()
    return status


@router.post("/control/kill-switch", dependencies=[Depends(require_control_token)])
async def kill_switch(request: Request) -> dict[str, Any]:
    """Kill switch MANUAL del operador (C8 / STORY-018, FR-012): HALTA toda ejecución hasta
    `/control/resume`. Idempotente. Devuelve el estado resultante de los breakers."""
    ctx = request.app.state.ctx
    breakers = getattr(ctx, "breakers", None)
    if breakers is None:
        return {"halted": False, "active": [], "breakers": []}
    breakers.trip_kill_switch()
    log.warning("kill switch ACTIVADO por el operador")
    _broadcast_breaker(ctx, breakers)
    ks_status: dict[str, Any] = breakers.status()
    return ks_status


@router.post("/control/resume", dependencies=[Depends(require_control_token)])
async def resume(request: Request) -> dict[str, Any]:
    """Reanuda tras kill switch / drawdown (C8 / STORY-018): limpia los breakers ENGANCHADOS
    y re-ancla el pico de equity al valor actual. Los breakers AUTO (vol/skew/stale) siguen
    su condición: si el riesgo persiste, `halted` seguirá `true`. Idempotente."""
    ctx = request.app.state.ctx
    breakers = getattr(ctx, "breakers", None)
    if breakers is None:
        return {"halted": False, "active": [], "breakers": []}
    pf = getattr(ctx, "portfolio", None)
    equity = pf.equity_total(ctx.latest_norm) if pf is not None else None
    breakers.resume(equity=equity)
    log.warning("RESUME por el operador (equity ancla=%s)", equity)
    _broadcast_breaker(ctx, breakers)
    resume_status: dict[str, Any] = breakers.status()
    return resume_status


def _broadcast_breaker(ctx: Any, breakers: Any) -> None:
    """Empuja el estado de breakers por SSE tras una acción manual, para que el dashboard
    refleje el cambio al instante (el monitor también lo emite al cambiar, pero una acción
    del operador debe verse YA sin esperar al siguiente tick)."""
    hub = getattr(ctx, "hub", None)
    if hub is not None:
        from ...models.events import StreamEvent

        hub.publish(StreamEvent(type="breaker", data=breakers.status()))


@router.post("/backtest", dependencies=[Depends(require_control_token)])
async def backtest(
    request: Request,
    in_sample_frac: float | None = Query(None, gt=0.0, lt=1.0),
) -> dict[str, Any]:
    """Lanza un replay (C14 / STORY-021, FR-014) sobre la grabación EN MEMORIA y devuelve las
    métricas global + in/out-of-sample (Sharpe por trade, win rate, profit/trade, max drawdown,
    profit factor). Reusa el MISMO motor/simulador del camino vivo (no una ruta paralela) y
    alimenta `sell_book_t1` con el tick futuro real del venue de venta → leg risk/unwinds reales.

    Síncrono y determinista: el replay no abre red ni reloj (sub-ms por tick). Sin grabación
    devuelve métricas nulas (autostart-safe). El resultado se guarda en `ctx.last_backtest`."""
    from ...backtest import run_backtest

    ctx = request.app.state.ctx
    recorder = getattr(ctx, "recorder", None)
    ticks = recorder.ticks() if recorder is not None else []
    result = run_backtest(ticks, ctx.settings, in_sample_frac=in_sample_frac)
    result.ts = _latest_book_ts(ctx.latest_norm)
    ctx.last_backtest = result
    dumped: dict[str, Any] = result.model_dump(mode="json")
    return dumped


@router.get("/backtest")
async def backtest_status(request: Request) -> dict[str, Any]:
    """Estado de la grabación (C14) + último resultado de replay si existe. Lanzar uno nuevo:
    `POST /backtest`."""
    ctx = request.app.state.ctx
    recorder = getattr(ctx, "recorder", None)
    last = getattr(ctx, "last_backtest", None)
    return {
        "recording": {
            "enabled": recorder.enabled if recorder is not None else False,
            "n_ticks": len(recorder) if recorder is not None else 0,
            "maxlen": recorder.maxlen if recorder is not None else None,
        },
        "last_result": last.model_dump(mode="json") if last is not None else None,
    }


@router.get("/demo")
async def demo_status(request: Request) -> dict[str, Any]:
    """Estado del fallback de demo (C16 / STORY-024, FR-018): `{active, mode, source, badge,
    since, n_replay_ticks}`. Autostart-safe: sin controlador devuelve estado vivo neutro."""
    ctx = request.app.state.ctx
    demo = getattr(ctx, "demo", None)
    if demo is None:
        return {"active": False, "mode": "auto", "source": "live", "badge": None}
    demo_st: dict[str, Any] = demo.status()
    return demo_st


@router.post("/demo", dependencies=[Depends(require_control_token)])
async def demo_set_mode(request: Request, mode: str = Query(...)) -> dict[str, Any]:
    """Fija el modo del fallback (C16): `auto` (cambia según la liveness real), `on` (fuerza
    replay — para que el jurado vea el fallback sin matar feeds), `off` (nunca replay). El
    cambio efectivo (activar/desactivar replay) lo aplica el siguiente tick del controlador."""
    if mode not in ("auto", "on", "off"):
        raise HTTPException(status_code=422, detail="mode debe ser auto|on|off")
    ctx = request.app.state.ctx
    demo = getattr(ctx, "demo", None)
    if demo is None:
        return {"active": False, "mode": "auto", "source": "live", "badge": None}
    from ...demo.fallback import Mode as _Mode
    demo.set_mode(cast(_Mode, mode))
    log.info("demo fallback: modo -> %s (operador)", mode)
    set_mode_st: dict[str, Any] = demo.status()
    return set_mode_st


@router.get("/metrics")
async def metrics(request: Request) -> dict[str, Any]:
    """Métricas del jurado (C13 / STORY-022, FR-017, NFR-001/010): embudo
    detectadas→viables→ejecutables→capturadas con MOTIVO + por estrategia; latencia p50/p99
    por etapa (detección/ejecución, en ventana, monotónica); microestructura (effective/realized
    spread, price impact, capture/fill ratio, opportunity lifetime).

    El embudo (conteos) viene de `ctx.opp_counts` (fuente única); el resto del colector C13.
    Autostart-safe: sin colector devuelve el embudo actual con agregados nulos (honesto)."""
    ctx = request.app.state.ctx
    collector = getattr(ctx, "metrics", None)
    if collector is None:
        funnel = ctx.opp_counts
        snap_empty: dict[str, Any] = MetricsSnapshot(
            detected=funnel.get("detected", 0),
            viable=funnel.get("viable", 0),
            executable=funnel.get("executable", 0),
            captured=funnel.get("captured", 0),
            discarded=funnel.get("discarded", 0),
            unwound=funnel.get("unwound", 0),
        ).model_dump(mode="json")
        return snap_empty
    snap: dict[str, Any] = collector.snapshot(ctx.opp_counts).model_dump(mode="json")
    return snap


@router.get("/validation")
async def validation() -> dict[str, Any]:
    """Arnés de validación (C15 / STORY-012, FR-021): reconciliación del ejemplo del reto
    ($109.75/BTC) + invariantes del sistema. Es la "prueba de correctitud" que el
    dashboard (HERO Edge Waterfall, STORY-023) muestra al jurado.

    Forma: `{reconciliation: {target, computed, diff, passed, ...}, invariants: [...],
    all_passed}`. Determinista y autostart-safe: construye su propio escenario reproducible
    (no depende del estado vivo ni de que haya habido trades), así responde igual con o sin
    ingesta. Sin red ni reloj real."""
    from ...validate import build_validation_report

    report = build_validation_report()
    validated: dict[str, Any] = report.model_dump(mode="json")
    return validated


@router.get("/projection")
async def projection(
    request: Request, mode: Literal["demo", "live"] = Query(default="demo")
) -> dict[str, Any]:
    """Projection Suite v2 — Capa 1: Break-even Frontier (Execution-Conditioned).

    Rejilla tamaño (BTC) × fee tier con la MISMA aritmética del pipeline (`engine.cost_model`):
    net/BTC, coste dominante, `P_survive` (prob. de sobrevivir la latencia) y Expected Capturable
    Edge por celda. `mode=demo` (cross representativo, determinista, autostart-safe) o `mode=live`
    (construida desde los books reales: ruta de mayor spread; cae a demo si no hay ruta viva)."""
    from ...projection import build_frontier

    ctx = request.app.state.ctx
    books = _live_projection_books(ctx) if mode == "live" else None
    settings = getattr(ctx, "settings", None)
    result = build_frontier(settings, books, mode=mode)
    return result.model_dump(mode="json")


@router.get("/capacity")
async def capacity(
    request: Request, mode: Literal["demo", "live"] = Query(default="demo")
) -> dict[str, Any]:
    """Projection Suite v2 — Capa 2: Capacity Curve. Edge neto total vs capital `Q` (cóncava,
    satura y cae): `Q*` donde el edge marginal cruza 0 (capacidad por oportunidad) y hard
    capacity donde el edge total cruza 0. Overlay teórico square-root law. `mode=demo|live`."""
    from ...projection import build_capacity_curve

    ctx = request.app.state.ctx
    books = _live_projection_books(ctx) if mode == "live" else None
    settings = getattr(ctx, "settings", None)
    result = build_capacity_curve(settings, books, mode=mode)
    return result.model_dump(mode="json")


@router.get("/forward")
async def forward(
    request: Request,
    n_paths: int = Query(default=5000, ge=100, le=20_000),
    n_configs: int = Query(default=1, ge=1),
) -> dict[str, Any]:
    """Projection Suite v2 — Capa 3: Forward de P&L (Monte Carlo honesto). Bootstrap estacionario
    de la distribución empírica de P&L por trade (del backtest record&replay): fan chart de equity
    (P5/P50/P95), P(P&L>0), drawdown esperado, y honestidad estadística (Sharpe/PSR/Deflated
    Sharpe/MinTRL, López de Prado). NO es un pronóstico: es la dispersión consistente con la
    muestra. `available=false` si no hay trades suficientes."""
    from ...models.projection import ForwardResult
    from ...projection import build_forward_projection

    ctx = request.app.state.ctx
    pnls = _backtest_trade_pnls(ctx)
    if not pnls:
        return ForwardResult(
            available=False,
            notes="Sin trades en la grabación: ejecuta el motor/backtest para poblar la muestra.",
        ).model_dump(mode="json")
    result = build_forward_projection(pnls, n_paths=n_paths, n_configs=n_configs)
    return result.model_dump(mode="json")


def _backtest_trade_pnls(ctx: Any) -> list[float]:
    """P&L por trade desde la grabación viva (Recorder): replay point-in-time y diferencias de
    la curva de equity realizada acumulada. Read-only; vacío si no hay grabación/trades."""
    recorder = getattr(ctx, "recorder", None)
    if recorder is None:
        return []
    ticks = recorder.ticks()
    if not ticks:
        return []
    from ...backtest import run_backtest

    result = run_backtest(ticks, ctx.settings, in_sample_frac=ctx.settings.backtest_in_sample_frac)
    curve = result.overall.equity_curve
    if not curve:
        return []
    return [curve[0], *[curve[i] - curve[i - 1] for i in range(1, len(curve))]]
