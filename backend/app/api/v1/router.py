"""Router `/api/v1`. SSE (C11) push de `quote`/`opportunity`; REST de snapshot en
vivo (`/quotes`, `/opportunities`). El resto son stubs hasta su story."""
from __future__ import annotations

import asyncio
import hmac
import logging
import math
import time
from collections import OrderedDict
from collections.abc import AsyncGenerator, Callable
from functools import partial
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from sse_starlette.sse import EventSourceResponse

from ...models.config import SimConfig
from ...models.enums import DiscardReason, OpportunityStatus
from ...models.metrics import MetricsSnapshot
from ...models.params import RetentionRequest, RuntimeParamOverrides, WhatIfRequest
from ...models.preflight import PreflightRequest, TestOrderRequest
from ...models.session import SessionExport, SessionMetadata
from ...models.strategy import StrategyInfo

router = APIRouter()
log = logging.getLogger("app.api.v1")

# Las proyecciones (frontier/capacity/forward) son cómputo numpy/Monte Carlo síncrono y
# pesado. Con un único worker uvicorn (estado en memoria, NFR-008), ejecutarlas en el event
# loop lo bloquea y congela el SSE y /health. Defensa en capas:
#   1) se corren en threadpool (run_in_threadpool) → el event loop queda libre para el SSE;
#   2) serializadas por un semáforo (1 a la vez): en 2 cores el pipeline de arbitraje ya usa
#      ~1 core, así que más de un Monte Carlo simultáneo dejaría sin CPU al event loop;
#   3) cache con TTL: cada cliente/recarga NO recomputa — se recalcula como mucho 1 vez por
#      ventana, sin importar cuántos navegadores o polls lleguen (clave en 2 cores).
_PROJECTION_SEM = asyncio.Semaphore(1)
# s — las proyecciones cambian lento. ≥ que el poll pesado del cliente (30s) para que el poll
# en estado estacionario sirva de cache y no recompute Monte Carlo cada vez en el único worker.
_PROJECTION_TTL = 35.0
# LRU ACOTADO: las claves incluyen parámetros libres del cliente (latency_ms, fee_bps, n_paths…)
# — un dict sin tope sería una fuga de memoria y un vector de DoS trivial (variar query params
# crea claves ilimitadas con ForwardResult grandes). El TTL solo gobierna frescura; la cota
# gobierna memoria. 64 entradas cubren de sobra los polls del dashboard + what-if del jurado.
_PROJECTION_CACHE_MAX = 64
_PROJECTION_CACHE: OrderedDict[str, tuple[float, Any]] = OrderedDict()
_MIN_WHAT_IF_FILL_RATIO = 0.10


def _cache_get(key: str, now: float) -> Any | None:
    """Hit fresco → lo marca como recién usado (LRU) y lo devuelve; expirado/miss → None."""
    hit = _PROJECTION_CACHE.get(key)
    if hit is None or now - hit[0] >= _PROJECTION_TTL:
        return None
    _PROJECTION_CACHE.move_to_end(key)
    return hit[1]


def _cache_put(key: str, value: Any, now: float) -> None:
    """Inserta y aplica la política: purga expiradas y desaloja la menos usada si excede el tope."""
    _PROJECTION_CACHE[key] = (now, value)
    _PROJECTION_CACHE.move_to_end(key)
    for k in [k for k, (ts, _) in _PROJECTION_CACHE.items() if now - ts >= _PROJECTION_TTL]:
        del _PROJECTION_CACHE[k]
    while len(_PROJECTION_CACHE) > _PROJECTION_CACHE_MAX:
        _PROJECTION_CACHE.popitem(last=False)


async def _cached_projection(key: str, compute: Callable[[], Any]) -> Any:
    """Devuelve la proyección `key` desde cache si es fresca; si no, la computa una sola vez
    (threadpool + semáforo) y la cachea. Double-check tras el semáforo: si otra petición la
    calculó mientras esperábamos, se reusa en vez de recomputar."""
    cached = _cache_get(key, time.monotonic())
    if cached is not None:
        return cached
    async with _PROJECTION_SEM:
        cached = _cache_get(key, time.monotonic())
        if cached is not None:
            return cached
        result = await run_in_threadpool(compute)
        _cache_put(key, result, time.monotonic())
        return result


def require_control_token(
    request: Request, x_control_token: str | None = Header(default=None)
) -> None:
    """Auth mínima de los endpoints de control. Si `settings.control_token` está vacío (dev),
    pasa siempre; si está set, exige el header `X-Control-Token` exacto. Lee el token del
    `ctx.settings` inyectado en el lifespan (respeta los settings de tests). La comparación es
    constant-time (`hmac.compare_digest`) para no filtrar prefijos por timing."""
    ctx = request.app.state.ctx
    expected = ctx.settings.control_token or ""
    if expected and not hmac.compare_digest(x_control_token or "", expected):
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
    detector = ctx.detector
    detector_books = getattr(detector, "books", None)
    if detector_books:
        return cast(dict[str, Any], detector_books)
    latest_norm = ctx.latest_norm
    if latest_norm:
        return cast(dict[str, Any], latest_norm)
    return None


def _safe_session_settings(ctx: Any) -> dict[str, Any]:
    """Lista blanca de settings para export auditable.

    No serializa `control_token`, `db_url`, variables de entorno ni credenciales.
    """
    settings = ctx.settings
    return {
        "app_name": settings.app_name,
        "env": settings.env,
        "quote_target": settings.quote_target,
        "staleness_ms": settings.staleness_ms,
        "peg_tolerance": settings.peg_tolerance,
        "max_slippage": settings.max_slippage,
        "min_net_profit_usd": settings.min_net_profit_usd,
        "default_trade_qty_btc": settings.default_trade_qty_btc,
        "expected_trades_per_rebalance": settings.expected_trades_per_rebalance,
        "demo_fallback_enabled": settings.demo_fallback_enabled,
        "demo_stale_ms": settings.demo_stale_ms,
        "demo_replay_interval_ms": settings.demo_replay_interval_ms,
        "execution_mode": settings.execution_mode,
        "enable_test_orders": settings.enable_test_orders,
        "execution_request_timeout_s": settings.execution_request_timeout_s,
        "execution_local_btc_balance": settings.execution_local_btc_balance,
        "execution_local_quote_balance_usd": settings.execution_local_quote_balance_usd,
        "calibration_mode": settings.calibration_mode,
        "shadow_sample_maxlen": settings.shadow_sample_maxlen,
        "survival_latencies_ms": settings.survival_latencies_ms,
        "exchanges": {
            key: {
                "id": cfg.id,
                "symbol": cfg.symbol,
                "quote_ccy": cfg.quote_ccy,
                "fee_taker": cfg.fee_taker,
                "withdrawal_btc": cfg.withdrawal_btc,
                "ob_limit": cfg.ob_limit,
                "enabled": cfg.enabled,
            }
            for key, cfg in settings.exchanges.items()
        },
    }


def _runtime_params_snapshot(ctx: Any) -> dict[str, Any]:
    """Snapshot publico de parametros ajustables y sus overrides activos.

    Los overrides son deliberadamente read-only para el motor vivo en esta fase: se usan en
    what-if/proyecciones y se exportan para auditoria, pero no cambian ejecucion real.
    """
    settings = ctx.settings
    overrides_model = ctx.runtime_params
    overrides = overrides_model.model_dump(
        mode="json",
        exclude_none=True,
        exclude_defaults=True,
    )
    base = {
        "default_trade_qty_btc": settings.default_trade_qty_btc,
        "max_slippage": settings.max_slippage,
        "min_net_profit_usd": settings.min_net_profit_usd,
        "exec_latency_ms": settings.exec_latency_ms,
        "expected_trades_per_rebalance": settings.expected_trades_per_rebalance,
        "peg_tolerance": settings.peg_tolerance,
        "z_open": settings.z_open,
        "z_close": settings.z_close,
        "z_stop": settings.z_stop,
        "inventory_skew_limit": settings.inventory_skew_limit,
        "fee_bps": None,
        "n_paths": 2000,
    }
    effective = {
        **base,
        **{k: v for k, v in overrides.items() if k != "enabled_exchange_overrides"},
    }
    exchange_overrides = overrides.get("enabled_exchange_overrides", {})
    exchanges = {
        key: {
            "enabled": bool(exchange_overrides.get(key, cfg.enabled)),
            "configured_enabled": cfg.enabled,
            "fee_bps": cfg.fee_taker * 10_000.0,
            "withdrawal_btc": cfg.withdrawal_btc,
            "symbol": cfg.symbol,
            "quote_ccy": cfg.quote_ccy,
        }
        for key, cfg in settings.exchanges.items()
    }
    return {
        "revision": ctx.runtime_revision,
        "scope": "what_if_and_projection_only",
        "base": base,
        "overrides": overrides,
        "effective": effective,
        "exchanges": exchanges,
        "ranges": {
            "default_trade_qty_btc": {"min": 0.00001, "max": 10.0},
            "fee_bps": {"min": 0.0, "max": 100.0},
            "latency_ms": {"min": 1, "max": 10_000},
            "max_slippage": {"min": 0.0, "max": 0.02},
            "expected_trades_per_rebalance": {"min": 1.0, "max": 50.0},
            "n_paths": {"min": 100, "max": 20_000},
        },
    }


def _runtime_value(ctx: Any, key: str) -> Any:
    overrides = ctx.runtime_params
    value = getattr(overrides, key, None) if overrides is not None else None
    if value is not None:
        return value
    return getattr(ctx.settings, key)


def _export_opportunity(opp: Any) -> dict[str, Any]:
    item = cast(dict[str, Any], opp.model_dump(mode="json"))
    explanation = getattr(opp, "explanation", None)
    if explanation is not None:
        item["explanation"] = explanation.model_dump(mode="json")
    return item


def _metrics_snapshot(ctx: Any) -> dict[str, Any]:
    collector = ctx.metrics
    if collector is None:
        funnel = ctx.opp_counts
        snap = MetricsSnapshot(
            detected=funnel.get("detected", 0),
            viable=funnel.get("viable", 0),
            executable=funnel.get("executable", 0),
            captured=funnel.get("captured", 0),
            discarded=funnel.get("discarded", 0),
            unwound=funnel.get("unwound", 0),
        ).model_dump(mode="json")
    else:
        snap = cast(dict[str, Any], collector.snapshot(ctx.opp_counts).model_dump(mode="json"))
    integrity = ctx.integrity
    if integrity is not None:
        snap["integrity"] = integrity.reports()
    return snap


def _record_preflight_metric(ctx: Any, venue: str, result: str) -> None:
    collector = ctx.metrics
    if collector is not None:
        collector.record_preflight(venue, result)


def _record_test_order_metric(ctx: Any, venue: str, result: str) -> None:
    collector = ctx.metrics
    if collector is not None:
        collector.record_test_order(venue, result)


def _strategy_books(ctx: Any) -> dict[str, Any]:
    detector = ctx.detector
    detector_books = getattr(detector, "books", None)
    if detector_books:
        return cast(dict[str, Any], detector_books)
    latest_norm = ctx.latest_norm
    if latest_norm:
        return cast(dict[str, Any], latest_norm)
    return {}


def _strategy_infos(ctx: Any) -> list[StrategyInfo]:
    settings = ctx.settings
    return [
        StrategyInfo(
            id="spatial",
            enabled=True,
            mode="primary",
            description="Spot cross-exchange BTC/USD; flujo principal.",
        ),
        StrategyInfo(
            id="stat_z",
            enabled=True,
            mode="adapter",
            description="Señal z-score existente; pasa por el mismo evaluador spot.",
        ),
        StrategyInfo(
            id="triangular",
            enabled=settings.strategy_triangular_enabled,
            mode="demo_replay",
            description="Ciclos intra-venue con fees y profundidad; apagado por defecto.",
        ),
        StrategyInfo(
            id="funding_basis",
            enabled=settings.strategy_funding_enabled,
            mode="read_only",
            description="Funding/basis separado de P&L spot; apagado por defecto.",
        ),
        StrategyInfo(
            id="regional_mxn",
            enabled=settings.strategy_regional_mxn_enabled,
            mode="experimental",
            description="BTC/MXN contra BTC/USD con FX explícito; apagado por defecto.",
        ),
    ]


def _book_reference_price(ctx: Any, venue: str, side: str) -> float | None:
    book = ctx.latest_norm.get(venue)
    if book is None:
        return None
    price = book.best_ask if side == "buy" else book.best_bid
    return float(price) if price is not None else None


def _enrich_execution_request(ctx: Any, req: PreflightRequest) -> PreflightRequest:
    """Rellena símbolo/cantidad/precio desde oportunidad reciente o book vivo.

    El adapter sigue siendo puro: la API es la que conoce el estado vivo de la app.
    """
    updates: dict[str, Any] = {}
    opp = ctx.opps_by_id.get(req.opportunity_id) if req.opportunity_id else None
    if opp is not None:
        if not req.symbol:
            updates["symbol"] = opp.symbol
        if req.quantity_btc <= 0.0:
            updates["quantity_btc"] = opp.q_target
        if req.reference_price is None:
            if req.side == "buy" and req.venue == opp.buy_venue and opp.vwap_buy is not None:
                updates["reference_price"] = opp.vwap_buy
            elif req.side == "sell" and req.venue == opp.sell_venue and opp.vwap_sell is not None:
                updates["reference_price"] = opp.vwap_sell
    if req.reference_price is None and "reference_price" not in updates:
        ref = _book_reference_price(ctx, req.venue, req.side)
        if ref is not None:
            updates["reference_price"] = ref
    return req.model_copy(update=updates) if updates else req


@router.get("/stream")
async def stream(request: Request) -> EventSourceResponse:
    """SSE. Emite los eventos publicados en el hub (C11): `quote`, `opportunity`
    (y `execution`/`pnl`/`metrics` en stories posteriores). Cola por cliente +
    corte por desconexión."""
    ctx = request.app.state.ctx
    # Cota de clientes concurrentes (DoS): /stream está exento del ApiGuardMiddleware
    # (streaming + BaseHTTPMiddleware no conviven) y cada cliente cuesta una cola acotada
    # en memoria. Sin tope, N conexiones sostenidas agotan memoria en el deploy público.
    max_clients = ctx.settings.sse_max_clients
    if max_clients > 0 and ctx.hub.client_count >= max_clients:
        raise HTTPException(status_code=503, detail="too many SSE clients; retry later")

    async def gen() -> AsyncGenerator[dict[str, str], None]:
        async for ev in ctx.hub.subscribe():
            if await request.is_disconnected():
                break
            yield {"event": ev.type, "data": ev.data_json}

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


@router.get("/config/public")
async def public_config(request: Request) -> dict[str, Any]:
    """Configuracion saneada para Strategy Lab.

    No expone tokens, rutas internas ni credenciales; solo parametros economicos y venues.
    """
    ctx = request.app.state.ctx
    return {
        "settings": _safe_session_settings(ctx),
        "runtime": _runtime_params_snapshot(ctx),
    }


@router.get("/params")
async def params(request: Request) -> dict[str, Any]:
    """Parametros ajustables de Strategy Lab y overrides activos."""
    ctx = request.app.state.ctx
    return _runtime_params_snapshot(ctx)


@router.patch("/params", dependencies=[Depends(require_control_token)])
async def params_patch(request: Request, body: RuntimeParamOverrides) -> dict[str, Any]:
    """Guarda overrides de Strategy Lab sin mutar el motor vivo.

    Sirve para what-if/proyecciones/export auditable. La ejecucion real queda separada para no
    cambiar umbrales operativos por un movimiento de UI.
    """
    ctx = request.app.state.ctx
    current = ctx.runtime_params
    incoming = body.model_dump(exclude_unset=True)
    if "enabled_exchange_overrides" in incoming:
        merged_ex = dict(current.enabled_exchange_overrides)
        merged_ex.update(cast(dict[str, bool], incoming["enabled_exchange_overrides"]))
        incoming["enabled_exchange_overrides"] = merged_ex
    ctx.runtime_params = current.model_copy(update=incoming)
    ctx.runtime_revision = ctx.runtime_revision + 1
    _PROJECTION_CACHE.clear()
    return _runtime_params_snapshot(ctx)


@router.post("/params/reset", dependencies=[Depends(require_control_token)])
async def params_reset(request: Request) -> dict[str, Any]:
    """Limpia overrides de Strategy Lab."""
    ctx = request.app.state.ctx
    ctx.runtime_params = RuntimeParamOverrides()
    ctx.runtime_revision = ctx.runtime_revision + 1
    _PROJECTION_CACHE.clear()
    return _runtime_params_snapshot(ctx)


@router.get("/analysis/wins", tags=["proyección"])
async def analysis_wins(
    request: Request, limit: int = Query(default=50, ge=1, le=500)
) -> dict[str, Any]:
    """Evidencia de ganancias: oportunidades CAPTURADAS y rentables (net > 0), persistidas.

    Es el registro de los spreads que SÍ sobrevivieron a los costes — prueba de que el motor no
    solo descarta, también captura cuando hay edge real. Lee de la DB (sobrevive reinicios).
    """
    ctx = request.app.state.ctx
    writer = ctx.writer
    if writer is None:
        return {"wins": [], "count": 0, "total_net_usd": 0.0, "best_net_per_btc": None}
    rows = await writer.get_opportunities(limit=limit, status="captured")
    wins: list[dict[str, Any]] = []
    total = 0.0
    best_per_btc: float | None = None
    for r in rows:
        net = r.get("net_pnl")
        if net is None or net <= 0:
            continue
        q = r.get("q_target") or 0.0
        per_btc = net / q if q > 0 else None
        total += net
        if per_btc is not None and (best_per_btc is None or per_btc > best_per_btc):
            best_per_btc = per_btc
        wins.append({
            "id": r.get("id"),
            "created_at": r.get("created_at"),
            "buy_venue": r.get("buy_venue"),
            "sell_venue": r.get("sell_venue"),
            "q_target": q,
            "net_usd": net,
            "net_per_btc": per_btc,
        })
    return {
        "wins": wins,
        "count": len(wins),
        "total_net_usd": total,
        "best_net_per_btc": best_per_btc,
    }


def _sim_config_snapshot(ctx: Any) -> dict[str, Any]:
    """Config base editable actual (de settings): balances/fees/venues + umbrales económicos."""
    s = ctx.settings
    return {
        "exchanges": {
            key: {
                "enabled": cfg.enabled,
                "fee_taker": cfg.fee_taker,
                "fee_bps": cfg.fee_taker * 10_000.0,
                "initial_btc": cfg.initial_btc,
                "initial_quote": cfg.initial_quote,
                "quote_ccy": cfg.quote_ccy,
                "symbol": cfg.symbol,
            }
            for key, cfg in s.exchanges.items()
        },
        "default_trade_qty_btc": s.default_trade_qty_btc,
        "min_net_profit_usd": s.min_net_profit_usd,
        "max_slippage": s.max_slippage,
        "exec_latency_ms": s.exec_latency_ms,
    }


@router.get("/config/sim", tags=["config"])
async def config_sim(request: Request) -> dict[str, Any]:
    """Configuración base editable de la simulación (balances, fees, venues, umbrales)."""
    return _sim_config_snapshot(request.app.state.ctx)


@router.put("/config/sim", tags=["config"], dependencies=[Depends(require_control_token)])
async def config_sim_put(request: Request, body: SimConfig) -> dict[str, Any]:
    """Guarda la configuración BASE (persistente) y aplica las ediciones hot al motor.

    A diferencia de /params (what-if read-only), esto SÍ cambia la config real: muta
    fees/balances/umbrales en settings; re-siembra el portfolio SOLO si cambian los balances
    iniciales. `enabled` NO es editable en caliente (PRD-009 RF-004): un cambio devuelve 409
    `venue_restart_required` (se edita en la config de despliegue + reinicio). Persiste en la
    DB, así sobrevive reinicios. Sigue siendo simulación: no opera con dinero real.

    Orden sin aplicación parcial (RF-007): 422 venue desconocido → 409 enabled → preparar
    sobre copias (sin mutar ctx) → persistir → aplicar runtime sin await intermedio.
    """
    from ...models.config import SimConfig as _SimConfig
    from ...sim import Portfolio
    from ...store.config_store import (
        apply_sim_config,
        diff_sim_config,
        load_app_config,
        save_app_config,
    )

    ctx = request.app.state.ctx
    engine = ctx.db_engine
    if engine is None:
        raise HTTPException(status_code=503, detail="db not initialized")

    # 422 — claves de venue que no existen en Settings (antes que cualquier otro rechazo).
    unknown = sorted(set(body.exchanges) - set(ctx.settings.exchanges))
    if unknown:
        raise HTTPException(status_code=422, detail=f"venues desconocidos: {', '.join(unknown)}")

    # 409 — cambio EXPLÍCITO de `enabled` respecto al runtime: requiere reinicio (RF-004).
    diverging = sorted(
        venue
        for venue, ov in body.exchanges.items()
        if ov.enabled is not None and ov.enabled != ctx.settings.exchanges[venue].enabled
    )
    if diverging:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "venue_restart_required",
                "venues": diverging,
                "message": (
                    "Cambiar los venues activos requiere editar la configuración de "
                    "despliegue y reiniciar el servicio."
                ),
            },
        )

    # Merge sobre lo ya persistido (envíos parciales no borran lo anterior).
    persisted = await load_app_config(engine)
    base = _SimConfig.model_validate(persisted) if persisted else _SimConfig()
    incoming = body.model_dump(exclude_unset=True)
    merged_ex = {**base.exchanges}
    for venue, ov in body.exchanges.items():
        prev = merged_ex.get(venue)
        merged_ex[venue] = prev.model_copy(update=ov.model_dump(exclude_unset=True)) if prev else ov
    merged = base.model_copy(update={k: v for k, v in incoming.items() if k != "exchanges"})
    merged.exchanges = merged_ex

    # PREPARAR sobre copias profundas (nada de esto muta ctx; todo lo falible ocurre aquí):
    # diff real "solo si difiere" (presencia ≠ cambio) y, si cambian los balances iniciales,
    # el portfolio re-sembrado. `enabled` queda fuera del camino hot (RF-004).
    applied = diff_sim_config(ctx.settings, merged, include_enabled=False)
    reseed = any(".initial_btc=" in c or ".initial_quote=" in c for c in applied)
    new_portfolio: Portfolio | None = None
    if reseed and ctx.portfolio is not None:
        prepared_settings = ctx.settings.model_copy(deep=True)
        apply_sim_config(prepared_settings, merged, include_enabled=False)
        new_portfolio = Portfolio(prepared_settings)

    # PERSISTIR en transacción; un fallo aquí deja runtime, portfolio y cache intactos.
    await save_app_config(engine, merged.model_dump(mode="json", exclude_none=True))

    # APLICAR runtime, sin await intermedio: un lector ve el estado anterior o el nuevo,
    # nunca una mezcla. El portfolio preparado se enlaza a la instancia canónica de Settings.
    apply_sim_config(ctx.settings, merged, include_enabled=False)
    if new_portfolio is not None:
        new_portfolio.settings = ctx.settings
        ctx.portfolio = new_portfolio  # balances nuevos → punto de partida limpio
    _PROJECTION_CACHE.clear()
    return {"applied": applied, "config": _sim_config_snapshot(ctx)}


@router.get("/info", tags=["sistema"])
async def info(request: Request) -> dict[str, Any]:
    """Metadata del servicio y capacidades — punto de entrada para clientes y el MCP server.

    Read-only y barato: nombre, versión, modo (demo/live), venues habilitados y catálogo de
    capacidades de consulta. No expone tokens ni credenciales.
    """
    ctx = request.app.state.ctx
    settings = ctx.settings
    demo = ctx.demo.status() if ctx.demo else {}
    return {
        "service": "arbitraje-btc",
        "version": "0.1.0",
        "thesis": "cuánto queda tras ejecutar con profundidad, fees, latencia, inventario y peg",
        "mode": "demo" if demo.get("active") else "live",
        "quote_target": settings.quote_target,
        "enabled_venues": [e.id for e in settings.enabled_exchanges],
        "capabilities": [
            "quotes", "opportunities", "opportunity_explain", "naive_vs_edge",
            "projection_frontier", "capacity", "forward_montecarlo", "survival_calibration",
            "pnl", "metrics", "validation", "storage", "session_export",
        ],
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


@router.get("/storage")
async def storage(request: Request) -> dict[str, Any]:
    """Uso de almacenamiento de la DB + estimación de retención.

    Mide tamaño real, tasa de inserción y bytes/fila desde la propia DB, y proyecta el tamaño
    en estado estacionario para 1/6/12/18/24 h. Read-only.
    """
    from ...store.retention import measure_storage

    ctx = request.app.state.ctx
    engine = ctx.db_engine
    if engine is None:
        raise HTTPException(status_code=503, detail="db not initialized")
    hours = ctx.db_retention_hours
    stats = await measure_storage(engine, ctx.settings.db_url, hours)
    return stats.to_dict()


@router.patch("/storage/retention", dependencies=[Depends(require_control_token)])
async def storage_retention(request: Request, body: RetentionRequest) -> dict[str, Any]:
    """Cambia la ventana de retención en caliente (0 = sin límite) y poda de inmediato.

    Es operación de mantenimiento real (afecta la poda), no what-if: el operador decide cuánto
    histórico conservar segun el espacio en disco.
    """
    from ...store.retention import measure_storage, prune_old_rows

    ctx = request.app.state.ctx
    engine = ctx.db_engine
    if engine is None:
        raise HTTPException(status_code=503, detail="db not initialized")
    ctx.db_retention_hours = body.retention_hours
    deleted = await prune_old_rows(
        engine, body.retention_hours, vacuum=body.vacuum or ctx.settings.db_vacuum_on_prune
    )
    stats = await measure_storage(engine, ctx.settings.db_url, body.retention_hours)
    return {"deleted": deleted, "storage": stats.to_dict()}


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


@router.get("/opportunities/{opportunity_id}/explain")
async def opportunity_explain(request: Request, opportunity_id: str) -> dict[str, Any]:
    """Explicación auditable de una oportunidad reciente (PRD-001).

    El payload completo no viaja en SSE para no inflar el stream; se consulta bajo demanda
    desde el buffer en memoria.
    """
    ctx = request.app.state.ctx
    opp = ctx.opps_by_id.get(opportunity_id)
    if opp is None:
        raise HTTPException(status_code=404, detail="opportunity not found")
    if opp.explanation is None:
        raise HTTPException(status_code=409, detail="opportunity explanation unavailable")
    return cast(dict[str, Any], opp.explanation.model_dump(mode="json"))


@router.post("/opportunities/{opportunity_id}/what-if")
async def opportunity_what_if(
    request: Request,
    opportunity_id: str,
    body: WhatIfRequest,
) -> dict[str, Any]:
    """Recalcula una oportunidad reciente con parametros alternativos.

    Usa los libros vivos actuales de la misma ruta. No registra oportunidad, no ejecuta orden y
    no altera el embudo: es analisis explainable para Strategy Lab.
    """
    from ...engine.cost_model import NetBreakdown, compute_net
    from ...engine.explain import build_opportunity_explanation

    ctx = request.app.state.ctx
    opp = ctx.opps_by_id.get(opportunity_id)
    if opp is None:
        raise HTTPException(status_code=404, detail="opportunity not found")
    books = _strategy_books(ctx)
    buy_book = books.get(opp.buy_venue)
    sell_book = books.get(opp.sell_venue)
    if buy_book is None or sell_book is None:
        raise HTTPException(status_code=409, detail="route books unavailable")

    runtime_size = ctx.runtime_params.default_trade_qty_btc
    q_requested = (
        body.size_btc
        if body.size_btc is not None
        else runtime_size
        if runtime_size is not None
        else opp.q_target
        if opp.q_target > 0.0
        else ctx.settings.default_trade_qty_btc
    )
    if q_requested <= 0.0 or not math.isfinite(q_requested):
        raise HTTPException(status_code=422, detail="size_btc must be finite and positive")

    runtime_fee_bps = ctx.runtime_params.fee_bps

    def _fee(venue: str, explicit_bps: float | None) -> float:
        bps = explicit_bps if explicit_bps is not None else body.fee_bps
        if bps is None:
            bps = runtime_fee_bps
        if bps is not None:
            return bps / 10_000.0
        cfg = ctx.settings.exchanges.get(venue)
        return cfg.fee_taker if cfg is not None else 0.0

    buy_cfg = ctx.settings.exchanges.get(opp.buy_venue)
    sell_cfg = ctx.settings.exchanges.get(opp.sell_venue)
    trades = (
        body.expected_trades_per_rebalance
        if body.expected_trades_per_rebalance is not None
        else float(_runtime_value(ctx, "expected_trades_per_rebalance"))
    )
    wd_buy = buy_cfg.withdrawal_btc if buy_cfg is not None else 0.0
    wd_sell = sell_cfg.withdrawal_btc if sell_cfg is not None else 0.0
    top_ask = buy_book.best_ask
    top_bid = sell_book.best_bid
    nb = compute_net(
        buy_book.asks,
        sell_book.bids,
        q_requested,
        fee_buy=_fee(opp.buy_venue, body.fee_buy_bps),
        fee_sell=_fee(opp.sell_venue, body.fee_sell_bps),
        rebalance_btc=(wd_buy + wd_sell) / trades,
        top_ask=top_ask,
        top_bid=top_bid,
    )

    max_slippage = (
        body.max_slippage
        if body.max_slippage is not None
        else float(_runtime_value(ctx, "max_slippage"))
    )
    min_net_profit_usd = (
        body.min_net_profit_usd
        if body.min_net_profit_usd is not None
        else float(_runtime_value(ctx, "min_net_profit_usd"))
    )
    slip_buy_rel = nb.slippage_buy / top_ask if top_ask and top_ask > 0.0 else 0.0
    slip_sell_rel = nb.slippage_sell / top_bid if top_bid and top_bid > 0.0 else 0.0

    breakdown: NetBreakdown | None = nb
    status = OpportunityStatus.discarded
    reason: DiscardReason | None
    if (
        not math.isfinite(nb.filled)
        or nb.filled <= 0.0
        or nb.filled < _MIN_WHAT_IF_FILL_RATIO * q_requested
    ):
        reason = DiscardReason.thin_book
        breakdown = None
    elif slip_buy_rel > max_slippage or slip_sell_rel > max_slippage:
        reason = DiscardReason.slippage_over_limit
    elif nb.net > min_net_profit_usd:
        status = OpportunityStatus.viable
        reason = None
    else:
        reason = DiscardReason.not_profitable_fees

    q_effective = nb.filled if nb.filled > 0.0 and math.isfinite(nb.filled) else 0.0
    what_opp = opp.model_copy(deep=True, update={
        "q_target": q_effective,
        "vwap_buy": nb.vwap_buy if breakdown is not None else None,
        "vwap_sell": nb.vwap_sell if breakdown is not None else None,
        "fees": nb.fees if breakdown is not None else None,
        "slippage": nb.slippage_cost if breakdown is not None else None,
        "net_pnl": nb.net if breakdown is not None else None,
        "status": status,
        "discard_reason": reason,
    })
    explanation = build_opportunity_explanation(
        what_opp,
        buy_book,
        sell_book,
        ctx.settings,
        breakdown=breakdown,
    )
    explanation.notes.extend([
        "what_if",
        f"requested_size_btc={q_requested:.8f}",
        f"max_slippage={max_slippage:.8f}",
    ])
    current_net = opp.net_pnl
    delta = (
        explanation.engine.net_usd - current_net
        if explanation.engine.net_usd is not None and current_net is not None
        else None
    )
    return {
        "opportunity_id": opportunity_id,
        "source": "live_route_books",
        "overrides": body.model_dump(mode="json", exclude_none=True),
        "current": (
            opp.explanation.model_dump(mode="json")
            if opp.explanation is not None
            else None
        ),
        "what_if": explanation.model_dump(mode="json"),
        "delta_net_usd": delta,
        "diagnostics": {
            "filled_btc": nb.filled,
            "depth_limited": nb.depth_limited,
            "slip_buy_rel": slip_buy_rel,
            "slip_sell_rel": slip_sell_rel,
            "min_fill_ratio": _MIN_WHAT_IF_FILL_RATIO,
        },
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
    writer = ctx.writer
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
    writer = ctx.writer
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
    pf = ctx.portfolio
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
    pf = ctx.portfolio
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
    breakers = ctx.breakers
    if breakers is None:
        return {"halted": False, "active": [], "breakers": []}
    status: dict[str, Any] = breakers.status()
    return status


@router.get("/execution/status")
async def execution_status(request: Request) -> dict[str, Any]:
    """Estado público y saneado de la capa PRD-003.

    No incluye API keys, secrets, firmas ni rutas internas.
    """
    from ...execution import build_execution_status

    ctx = request.app.state.ctx
    status_model = build_execution_status(ctx.settings)
    return status_model.model_dump(mode="json")


@router.post("/execution/preflight", dependencies=[Depends(require_control_token)])
async def execution_preflight(request: Request, body: PreflightRequest) -> dict[str, Any]:
    """Valida una orden contra reglas de testnet/dry-run sin operar dinero real."""
    from ...execution import (
        ExecutionDisabled,
        UnsupportedExecutionVenue,
        ensure_execution_enabled,
        get_execution_adapter,
    )

    ctx = request.app.state.ctx
    try:
        ensure_execution_enabled(ctx.settings)
        enriched = _enrich_execution_request(ctx, body)
        adapter = get_execution_adapter(ctx.settings, enriched.venue)
    except ExecutionDisabled as exc:
        _record_preflight_metric(ctx, body.venue, "blocked")
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UnsupportedExecutionVenue as exc:
        _record_preflight_metric(ctx, body.venue, "unsupported")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = await adapter.preflight(enriched)
    _record_preflight_metric(ctx, result.venue, "accepted" if result.accepted else "rejected")
    log.info(
        "execution preflight venue=%s symbol=%s accepted=%s",
        result.venue,
        result.symbol,
        result.accepted,
    )
    return result.model_dump(mode="json")


@router.post("/execution/test-order", dependencies=[Depends(require_control_token)])
async def execution_test_order(request: Request, body: TestOrderRequest) -> dict[str, Any]:
    """Envía una test order determinista/testnet sólo con flags duros activos."""
    from ...execution import (
        TestOrdersDisabled,
        UnsupportedExecutionVenue,
        ensure_test_orders_enabled,
        get_execution_adapter,
    )

    ctx = request.app.state.ctx
    try:
        ensure_test_orders_enabled(ctx.settings)
        enriched = _enrich_execution_request(ctx, body)
        adapter = get_execution_adapter(ctx.settings, enriched.venue)
    except TestOrdersDisabled as exc:
        _record_test_order_metric(ctx, body.venue, "blocked")
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UnsupportedExecutionVenue as exc:
        _record_test_order_metric(ctx, body.venue, "unsupported")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = await adapter.test_order(TestOrderRequest(**enriched.model_dump()))
    _record_test_order_metric(ctx, result.venue, result.status)
    log.info(
        "execution test-order venue=%s symbol=%s accepted=%s status=%s",
        result.venue,
        result.symbol,
        result.accepted,
        result.status,
    )
    return result.model_dump(mode="json")


@router.post("/control/kill-switch", dependencies=[Depends(require_control_token)])
async def kill_switch(request: Request) -> dict[str, Any]:
    """Kill switch MANUAL del operador (C8 / STORY-018, FR-012): HALTA toda ejecución hasta
    `/control/resume`. Idempotente. Devuelve el estado resultante de los breakers."""
    ctx = request.app.state.ctx
    breakers = ctx.breakers
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
    breakers = ctx.breakers
    if breakers is None:
        return {"halted": False, "active": [], "breakers": []}
    pf = ctx.portfolio
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
    hub = ctx.hub
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
    recorder = ctx.recorder
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
    recorder = ctx.recorder
    last = ctx.last_backtest
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
    demo = ctx.demo
    if demo is None:
        return {"active": False, "mode": "auto", "source": "live", "badge": None}
    demo_st: dict[str, Any] = demo.status()
    return demo_st


@router.post("/demo", dependencies=[Depends(require_control_token)])
async def demo_set_mode(request: Request, mode: str = Query(...)) -> dict[str, Any]:
    """Fija el modo del fallback (C16): `auto` (cambia según la liveness real), `on` (fuerza
    replay — para que el jurado vea el fallback sin matar feeds), `jury` (escenarios
    deterministas PRD-002), `off` (nunca replay)."""
    if mode not in ("auto", "on", "off", "jury"):
        raise HTTPException(status_code=422, detail="mode debe ser auto|on|off|jury")
    ctx = request.app.state.ctx
    demo = ctx.demo
    if demo is None:
        return {"active": False, "mode": "auto", "source": "live", "badge": None}
    from ...demo.fallback import Mode as _Mode
    demo.set_mode(cast(_Mode, mode))
    demo.tick(time.monotonic())
    log.info("demo fallback: modo -> %s (operador)", mode)
    set_mode_st: dict[str, Any] = demo.status()
    return set_mode_st


@router.get("/demo/scenarios")
async def demo_scenarios(request: Request) -> dict[str, Any]:
    """Escenarios deterministas disponibles para demo de jurado."""
    ctx = request.app.state.ctx
    demo = ctx.demo
    if demo is not None:
        return {"scenarios": demo.jury_scenarios()}
    from ...demo.scenarios import build_jury_scenarios

    return {
        "scenarios": [
            {
                "name": s.name,
                "description": s.description,
                "kind": s.kind,
                "expected_result": s.expected_result,
            }
            for s in build_jury_scenarios()
        ]
    }


@router.post("/demo/scenario/{name}", dependencies=[Depends(require_control_token)])
@router.post("/demo/scenarios/{name}", dependencies=[Depends(require_control_token)])
async def demo_select_scenario(request: Request, name: str) -> dict[str, Any]:
    """Selecciona un escenario especifico y fuerza modo jury."""
    ctx = request.app.state.ctx
    demo = ctx.demo
    if demo is None:
        return {"active": False, "mode": "auto", "source": "live", "badge": None}
    if not demo.select_jury_scenario(name):
        raise HTTPException(status_code=404, detail="scenario not found")
    demo.tick(time.monotonic())
    log.info("demo fallback: escenario jury -> %s (operador)", name)
    st: dict[str, Any] = demo.status()
    return st


@router.get("/session/export")
async def session_export(request: Request) -> dict[str, Any]:
    """Export auditable de la sesión actual (PRD-002).

    El payload usa lista blanca de configuración para evitar filtrar tokens,
    credenciales o rutas internas sensibles.
    """
    from ...validate import build_validation_report

    ctx = request.app.state.ctx
    settings = ctx.settings
    demo = ctx.demo
    breakers = ctx.breakers
    recorder = ctx.recorder
    export = SessionExport(
        metadata=SessionMetadata(
            app=settings.app_name,
            env=settings.env,
            version="0.1.0",
            exported_at=time.time(),
        ),
        settings=_safe_session_settings(ctx),
        runtime_params=_runtime_params_snapshot(ctx),
        quotes=[
            cast(dict[str, Any], nb.model_dump(mode="json"))
            for nb in ctx.latest_norm.values()
        ],
        opportunities=[_export_opportunity(o) for o in reversed(list(ctx.recent_opps))],
        metrics=_metrics_snapshot(ctx),
        breakers=breakers.status() if breakers is not None else {
            "halted": False,
            "active": [],
            "breakers": [],
        },
        demo=demo.status() if demo is not None else {
            "active": False,
            "mode": "auto",
            "source": "live",
            "badge": None,
        },
        calibration={
            "mode": settings.calibration_mode,
            "n_shadow_samples": len(ctx.shadow_samples),
            "shadow_samples": [
                sample.model_dump(mode="json")
                for sample in list(ctx.shadow_samples)[-500:]
            ],
        },
        validation=build_validation_report().model_dump(mode="json"),
        recording={
            "enabled": recorder.enabled if recorder is not None else False,
            "n_ticks": len(recorder) if recorder is not None else 0,
            "maxlen": recorder.maxlen if recorder is not None else None,
        },
    )
    return export.model_dump(mode="json")


@router.get("/metrics")
async def metrics(request: Request) -> dict[str, Any]:
    """Métricas del jurado (C13 / STORY-022, FR-017, NFR-001/010): embudo
    detectadas→viables→ejecutables→capturadas con MOTIVO + por estrategia; latencia p50/p99
    por etapa (detección/ejecución, en ventana, monotónica); microestructura (effective/realized
    spread, price impact, capture/fill ratio, opportunity lifetime).

    El embudo (conteos) viene de `ctx.opp_counts` (fuente única); el resto del colector C13.
    Autostart-safe: sin colector devuelve el embudo actual con agregados nulos (honesto)."""
    ctx = request.app.state.ctx
    collector = ctx.metrics
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
        integrity = ctx.integrity
        if integrity is not None:
            snap_empty["integrity"] = integrity.reports()
        return snap_empty
    snap: dict[str, Any] = collector.snapshot(ctx.opp_counts).model_dump(mode="json")
    integrity = ctx.integrity
    if integrity is not None:
        snap["integrity"] = integrity.reports()
    return snap


@router.get("/strategies")
async def strategies(request: Request) -> dict[str, Any]:
    """Inventario de módulos de estrategia (PRD-008).

    Las extensiones P3 son opt-in y read-only/demo al inicio; el flujo principal sigue siendo
    `spatial` spot cross-exchange.
    """
    ctx = request.app.state.ctx
    return {"strategies": [info.model_dump(mode="json") for info in _strategy_infos(ctx)]}


@router.get("/strategies/triangular/opportunities")
async def strategy_triangular_opportunities(request: Request) -> dict[str, Any]:
    """Oportunidades triangulares intra-venue demo/replay (PRD-008)."""
    from ...strategies import TriangularStrategy

    ctx = request.app.state.ctx
    strategy = TriangularStrategy(ctx.settings)
    books = _strategy_books(ctx)
    opportunities = strategy.find_opportunities(list(books.values()))
    notes = []
    if not strategy.enabled:
        notes.append("strategy disabled by config")
    if strategy.enabled and not opportunities:
        notes.append("no three-leg cycle passed fee and depth validation")
    return {
        "strategy": strategy.id,
        "enabled": strategy.enabled,
        "mode": "demo_replay",
        "opportunities": [opp.model_dump(mode="json") for opp in opportunities],
        "notes": notes,
    }


@router.get("/strategies/funding/opportunities")
async def strategy_funding_opportunities(request: Request) -> dict[str, Any]:
    """Funding/basis read-only (PRD-008).

    El repo todavía no ingiere funding rates live; la ruta existe para mantener el contrato
    separado del P&L spot.
    """
    from ...strategies import FundingBasisStrategy

    ctx = request.app.state.ctx
    strategy = FundingBasisStrategy(ctx.settings)
    return {
        "strategy": strategy.id,
        "enabled": strategy.enabled,
        "mode": "read_only",
        "opportunities": [],
        "notes": [
            "strategy disabled by config"
            if not strategy.enabled
            else "funding rates feed not configured; read-only contract only"
        ],
    }


@router.get("/strategies/regional/mxn")
async def strategy_regional_mxn(request: Request) -> dict[str, Any]:
    """Corredor regional BTC/MXN experimental (PRD-008)."""
    from ...strategies import RegionalMXNStrategy

    ctx = request.app.state.ctx
    strategy = RegionalMXNStrategy(ctx.settings)
    notes = []
    opportunities = []
    fx = ctx.settings.strategy_mxn_usd_rate
    if not strategy.enabled:
        notes.append("strategy disabled by config")
    elif fx is None:
        notes.append("ARB_STRATEGY_MXN_USD_RATE is required")
    else:
        opportunities = [
            opp.model_dump(mode="json")
            for opp in strategy.find_opportunities(_strategy_books(ctx), usd_mxn=fx)
        ]
        if not opportunities:
            notes.append("no BTC/MXN and BTC/USD books available")
    return {
        "strategy": strategy.id,
        "enabled": strategy.enabled,
        "mode": "experimental",
        "usd_mxn": fx,
        "opportunities": opportunities,
        "notes": notes,
    }


@router.get("/integrity")
async def integrity(request: Request) -> dict[str, Any]:
    """Reportes enriquecidos de integridad por venue (PRD-004)."""
    ctx = request.app.state.ctx
    checker = ctx.integrity
    if checker is None:
        return {}
    return cast(dict[str, Any], checker.reports())


@router.get("/analysis/naive-vs-edge")
async def analysis_naive_vs_edge(request: Request) -> dict[str, Any]:
    """Contraste agregado de sesion: lo que un detector de spreads ingenuo contaria como
    ganancia bruta vs el neto que el motor realmente captura, con atribucion de la fuga por
    razon de descarte. Es la tesis del proyecto hecha agregado, sobre `recent_opps`.

    Forma: `NaiveVsEdgeReport`. Read-only, sin red ni reloj; agrega oportunidades ya evaluadas.
    """
    from ...analysis import build_naive_vs_edge

    ctx = request.app.state.ctx
    report = build_naive_vs_edge(list(ctx.recent_opps), ctx.settings)
    result: dict[str, Any] = report.model_dump(mode="json")
    return result


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


@router.get("/calibration/survival")
async def calibration_survival(
    request: Request,
    latency_ms: int = Query(default=100, ge=1, le=10_000),
    observation_limit: int = Query(default=50, ge=0, le=500),
) -> dict[str, Any]:
    """Calibración observe-only de P_survive contra supervivencia observada (PRD-005)."""
    from ...calibration import build_survival_report

    ctx = request.app.state.ctx
    recorder = ctx.recorder
    ticks = recorder.ticks() if recorder is not None else []
    report = build_survival_report(
        list(ctx.shadow_samples),
        ticks,
        ctx.settings,
        latency_ms=latency_ms,
        observation_limit=observation_limit,
    )
    return report.model_dump(mode="json")


@router.get("/projection")
async def projection(
    request: Request,
    mode: Literal["demo", "live"] = Query(default="demo"),
    latency_ms: float | None = Query(default=None, ge=1.0, le=10_000.0),
) -> dict[str, Any]:
    """Projection Suite v2 — Capa 1: Break-even Frontier (Execution-Conditioned).

    Rejilla tamaño (BTC) × fee tier con la MISMA aritmética del pipeline (`engine.cost_model`):
    net/BTC, coste dominante, `P_survive` (prob. de sobrevivir la latencia) y Expected Capturable
    Edge por celda. `mode=demo` (cross representativo, determinista, autostart-safe) o `mode=live`
    (construida desde los books reales: ruta de mayor spread; cae a demo si no hay ruta viva)."""
    from ...projection import build_frontier

    ctx = request.app.state.ctx
    books = _live_projection_books(ctx) if mode == "live" else None
    settings = ctx.settings
    cache_mode = "live" if mode == "live" and books is not None else "demo"
    result = await _cached_projection(
        f"frontier:{cache_mode}:lat={latency_ms}",
        partial(build_frontier, settings, books, mode=mode, latency_ms=latency_ms),
    )
    return cast(dict[str, Any], result.model_dump(mode="json"))


@router.get("/capacity")
async def capacity(
    request: Request,
    mode: Literal["demo", "live"] = Query(default="demo"),
    fee_bps: float | None = Query(default=None, ge=0.0, le=100.0),
) -> dict[str, Any]:
    """Projection Suite v2 — Capa 2: Capacity Curve. Edge neto total vs capital `Q` (cóncava,
    satura y cae): `Q*` donde el edge marginal cruza 0 (capacidad por oportunidad) y hard
    capacity donde el edge total cruza 0. Overlay teórico square-root law. `mode=demo|live`."""
    from ...projection import build_capacity_curve

    ctx = request.app.state.ctx
    books = _live_projection_books(ctx) if mode == "live" else None
    settings = ctx.settings
    cache_mode = "live" if mode == "live" and books is not None else "demo"
    fee = fee_bps / 10_000.0 if fee_bps is not None else None
    result = await _cached_projection(
        f"capacity:{cache_mode}:fee={fee_bps}",
        partial(build_capacity_curve, settings, books, mode=mode, fee=fee),
    )
    return cast(dict[str, Any], result.model_dump(mode="json"))


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

    # `_backtest_trade_pnls` corre un backtest/replay PESADO; debe ir dentro del cómputo
    # cacheado+threadpool (antes corría en el event loop en cada request y lo congelaba).
    def _compute_forward() -> ForwardResult:
        pnls = _backtest_trade_pnls(ctx)
        if not pnls:
            return ForwardResult(
                available=False,
                notes=(
                    "Sin trades en la grabación: ejecuta el motor/backtest "
                    "para poblar la muestra."
                ),
            )
        return build_forward_projection(pnls, n_paths=n_paths, n_configs=n_configs)

    result = await _cached_projection(f"forward:{n_paths}:{n_configs}", _compute_forward)
    return cast(dict[str, Any], result.model_dump(mode="json"))


def _backtest_trade_pnls(ctx: Any) -> list[float]:
    """P&L por trade desde la grabación viva (Recorder): replay point-in-time y diferencias de
    la curva de equity realizada acumulada. Read-only; vacío si no hay grabación/trades."""
    recorder = ctx.recorder
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
