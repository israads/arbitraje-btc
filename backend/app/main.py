"""Punto de entrada FastAPI (`app.main:app`). Un proceso, un event loop (uvloop).

El `lifespan` prepara el estado compartido y lanza las tasks del pipeline (ingesta C1 →
normalización C3 → bus C4 → motor C5/C6 → simulador C9 → cartera C10 → persistencia C12 →
pump SSE C11). En tests `ingest_autostart=False` deja sólo `/health`, CORS, hub SSE y la
cartera sembrada, sin abrir conexiones a exchanges.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .api.health import router as health_router
from .api.security import ApiGuardMiddleware
from .api.v1.router import router as v1_router
from .backtest import Recorder
from .bus import BoundedQueue
from .calibration import build_shadow_sample
from .config import Settings, get_settings
from .demo import DemoFallback
from .engine import NetEvaluator, Prioritizer, SpatialDetector, StatZDetector, run_engine
from .ingest import build_ingestors, run_ingestors
from .integrity.checker import BookIntegrityChecker
from .logging_config import configure_logging
from .metrics import MetricsCollector, render_prometheus
from .models.config import SimConfig
from .models.enums import DiscardReason, OpportunityStatus
from .models.market import NormalizedBook, RawOrderBook
from .models.opportunity import Opportunity
from .normalize import Normalizer, PegProvider, build_peg_ingestors
from .risk.breakers import BreakerManager, BreakerMonitor
from .risk.watchdog import Watchdog
from .runner import Runner
from .sim import ExecutionSimulator, Portfolio, Rebalancer
from .state import AppState
from .store import BatchWriter, init_db, make_engine
from .store.config_store import apply_sim_config, load_app_config
from .stream.hub import StreamHub
from .stream.pump import StreamPublisher

log = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(settings.log_level)
    hub = StreamHub(client_queue_maxsize=settings.sse_client_queue_maxsize)
    ctx = AppState(settings=settings, hub=hub)
    app.state.ctx = ctx
    log.info(
        "startup app=%s env=%s exchanges=%s",
        settings.app_name, settings.env, [e.id for e in settings.enabled_exchanges],
    )

    # Persistencia + CONFIGURACIÓN BASE: se crea el engine y se aplica la config persistida a
    # `settings` ANTES de construir el motor/portfolio, para que usen los balances/fees/venues
    # guardados por el operador (es la config base real, no what-if).
    _db_engine = make_engine(settings.db_url)
    await init_db(_db_engine)
    ctx.db_engine = _db_engine
    _persisted = await load_app_config(_db_engine)
    if _persisted:
        applied = apply_sim_config(settings, SimConfig.model_validate(_persisted))
        if applied:
            log.info("config base aplicada: %s", ", ".join(applied))

    # C3 — peg + normalizador (STORY-003); C4 bus + C5 detector (STORY-004).
    ctx.peg = PegProvider(target=settings.quote_target, tolerance=settings.peg_tolerance)
    ctx.normalizer = Normalizer(ctx.peg)
    ctx.integrity = BookIntegrityChecker(settings.integrity_mode)  # C2/PRD-004
    ctx.bus = BoundedQueue(settings.bus_maxsize)
    ctx.detector = SpatialDetector(settings)
    ctx.stat_detector = StatZDetector(settings)  # C5 — arbitraje estadístico z-score (STORY-019)
    ctx.evaluator = NetEvaluator(settings, peg=ctx.peg)  # C6 — neto + gate peg_adverse (STORY-008)
    ctx.prioritizer = Prioritizer(settings)  # C7 — ranking por score (STORY-020)
    ctx.simulator = ExecutionSimulator(settings)  # C9 — simulador (STORY-009)
    ctx.portfolio = Portfolio(settings)  # C10 — inventario pre-posicionado + P&L (STORY-010)
    ctx.breakers = BreakerManager(settings)  # C8 — circuit breakers + kill switch (STORY-018)
    ctx.recorder = Recorder(  # C14 — grabador de ticks para replay/demo (STORY-021)
        maxlen=settings.record_maxlen, enabled=settings.record_enabled,
    )
    ctx.metrics = MetricsCollector(settings)  # C13 — métricas del jurado (STORY-022)
    publisher = StreamPublisher(
        hub,
        quote_throttle_ms=settings.quote_throttle_ms,
        metrics_throttle_ms=settings.metrics_emit_ms,
    )

    # C12 (STORY-011): escritor async/batch sobre el engine ya creado arriba. El BatchWriter
    # arranca su task de flushing y se cuelga de ctx para que los endpoints REST lo consulten.
    ctx.writer = BatchWriter(
        engine=_db_engine,
        batch_size=settings.store_batch_size,
        flush_seconds=settings.store_flush_seconds,
    )
    ctx.writer.start()

    async def _retention_loop() -> None:
        """Poda periódica: mantiene la DB acotada a `db_retention_hours` (0 = sin límite).
        Best-effort y fuera del camino caliente; lee la retención de ctx para reflejar cambios
        en caliente vía endpoint."""
        from .store.retention import prune_old_rows
        while True:
            await asyncio.sleep(settings.db_prune_interval_s)
            hours = getattr(ctx, "db_retention_hours", settings.db_retention_hours)
            await prune_old_rows(_db_engine, hours, vacuum=settings.db_vacuum_on_prune)

    ctx.db_retention_hours = settings.db_retention_hours
    if settings.db_retention_hours > 0:
        ctx.tasks.append(asyncio.create_task(_retention_loop(), name="db_retention"))

    def _move_viable_to_discarded() -> None:
        """Reconcilia el embudo cuando una opp ya contada como `viable` se descarta: retira el
        `viable` (sin bajar de 0) y suma el `discarded`. Fuente ÚNICA de la reconciliación —
        la comparten los tres gates (breakers, capital, slippage pre-trade) sin doble-conteo."""
        counts = ctx.opp_counts
        counts[OpportunityStatus.viable.value] = max(0, counts[OpportunityStatus.viable.value] - 1)
        counts[OpportunityStatus.discarded.value] += 1

    def on_opp(opp: Opportunity) -> None:
        is_viable = opp.status is OpportunityStatus.viable
        ctx.record_opportunity(opp)         # embudo C13 + buffer (cuenta viable/discarded)
        # C8 (STORY-018): GATE de circuit breakers — el motor consulta el estado ANTES de
        # operar (Apéndice F). Con cualquier breaker activo (vol/skew/drawdown/stale/kill) la
        # oportunidad viable NO se ejecuta: se reclasifica a discarded(breaker_active) y se
        # reconcilia el embudo (retira el `viable` recién contado, suma el `discarded`), igual
        # que el descarte pre-trade del simulador. Las no-viables (ya discarded) no se tocan.
        if (
            is_viable
            and ctx.breakers is not None
            and ctx.breakers.tripped
        ):
            opp.status = OpportunityStatus.discarded
            opp.discard_reason = DiscardReason.breaker_active
            _move_viable_to_discarded()
            is_viable = False  # no simular: el sistema está HALTADO
        # C7 (STORY-020): GATE de capital/inventario (FR-007 AC#4 / FR-010). Las opps llegan
        # ya rankeadas por score desc (run_engine), así que las de mayor score consumen el saldo
        # primero; cuando el venue de compra se queda sin quote o el de venta sin BTC, la opp se
        # reclasifica a discarded(insufficient_balance) y NO se simula. Mismo patrón de
        # reconciliación del embudo (viable→discarded) que el gate de breakers.
        if (
            is_viable
            and ctx.portfolio is not None
            and not ctx.portfolio.can_afford(opp)
        ):
            opp.status = OpportunityStatus.discarded
            opp.discard_reason = DiscardReason.insufficient_balance
            _move_viable_to_discarded()
            is_viable = False  # sin saldo: no se ejecuta (FR-010)
        # C9 (STORY-009): simula la ejecución TAKER de las oportunidades viables. Se hace
        # DESPUÉS de registrar la viabilidad, para que el embudo conserve el conteo de
        # `viable` y sume además `captured` (etapas distintas del ciclo de vida).
        # Retrocompatible y autostart-safe: sin red ni reloj de decisión, sólo el libro
        # actual de cada venue (el que mantiene el detector). El cableado de balances/P&L
        # (STORY-010) y persistencia (STORY-011) consumirán el `Execution` resultante.
        if is_viable and ctx.simulator is not None and ctx.detector is not None:
            buy_book = ctx.detector.books.get(opp.buy_venue)
            sell_book = ctx.detector.books.get(opp.sell_venue)
            if buy_book is not None and sell_book is not None:
                # C13 (STORY-022): etapa EXECUTABLE del embudo — la opp viable sobrevivió a los
                # gates de riesgo (breakers) y capital y tiene libros vivos en ambos venues, luego
                # se SOMETE a ejecución. `captured`/`discarded(slippage)` es ya el resultado de
                # simular. Así el embudo de 4 etapas es real: detected≥viable≥executable≥captured.
                ctx.opp_counts[OpportunityStatus.executable.value] += 1
                # C9: muta opp → captured (o discarded si el gate pre-trade de slippage la
                # rechaza, devolviendo None: en vivo no ocurre porque el evaluador ya filtró
                # y el motor pasa el mismo snapshot, sin re-lectura t+Δ).
                execution = ctx.simulator.simulate(opp, buy_book, sell_book)
            else:
                execution = None
            if execution is None:
                # Descarte pre-trade del simulador (gate de slippage): la opp se contó como
                # `viable` ANTES de simular y ahora quedó `discarded`. Reconcilia el embudo
                # (no doble-cuenta): retira el `viable` y suma el `discarded` real.
                if opp.status is OpportunityStatus.discarded:
                    _move_viable_to_discarded()
            else:
                ctx.opp_counts[OpportunityStatus.captured.value] += 1
                if execution.unwound:
                    ctx.opp_counts["unwound"] += 1  # sub-conteo de captured (STORY-016)
                if ctx.metrics is not None:  # C13: fill ratio + latencia de ejecución
                    ctx.metrics.record_execution(execution)
                # C10 (STORY-010): aplica el Execution a la cartera con doble entrada
                # (balances + realized P&L) y sella un punto de la equity curve marcando a
                # mercado con los libros vivos del detector. Autostart-safe y retrocompatible.
                if ctx.portfolio is not None:
                    ctx.portfolio.apply_execution(execution)
                    ts = execution.ts if execution.ts is not None else 0.0
                    ctx.portfolio.record_equity_point(ctx.detector.books, ts=ts)
                    # C11: push de P&L en tiempo real (throttled) — el dashboard deja de
                    # depender del polling de /pnl (sin lag de intervalo).
                    pf, books = ctx.portfolio, ctx.detector.books
                    publisher.publish_pnl(lambda: pf.pnl_summary(books))
                # C12 (STORY-011): encola la ejecución para persistencia batch.
                if ctx.writer is not None:
                    ctx.writer.enqueue_execution(execution)
        publisher.publish_opportunity(opp)  # C11 → SSE (STORY-005)
        # PRD-005: sample shadow observe-only. Se captura con el estado FINAL de la opp y
        # libros presentes; la supervivencia futura se calcula sólo bajo demanda.
        books_for_sample = (
            ctx.detector.books
            if ctx.detector is not None and ctx.detector.books
            else ctx.latest_norm
        )
        demo = getattr(ctx, "demo", None)
        source = "live"
        if demo is not None:
            demo_status = demo.status()
            if demo_status.get("active"):
                source = str(demo_status.get("source") or "demo")
        ctx.record_shadow_sample(
            build_shadow_sample(opp, books_for_sample, settings, source=source)
        )
        # C13 (STORY-022): registra la opp con su estado FINAL del tick (tras todos los gates)
        # en latencia/microestructura/lifetime/desgloses, y empuja el snapshot por SSE (THROTTLED
        # — no en cada opp). El embudo (conteos) sigue siendo `opp_counts` (fuente única).
        if ctx.metrics is not None:
            collector = ctx.metrics  # bind local: mypy no estrecha el atributo dentro del lambda
            collector.record_opportunity(opp)
            if publisher.publish_metrics(
                lambda: collector.snapshot(ctx.opp_counts).model_dump(mode="json")
            ):
                # Logging del DESGLOSE de decisiones (FR-017), throttled al ritmo del push SSE
                # (~1/s) para no inundar: embudo + motivos + latencia p50/p99 de detección.
                f = ctx.opp_counts
                dl = collector.detect_p50_p99()
                log.info(
                    "funnel detected=%d viable=%d executable=%d captured=%d discarded=%d "
                    "unwound=%d | reasons=%s | detect_p50=%.3fms p99=%.3fms",
                    f.get("detected", 0), f.get("viable", 0), f.get("executable", 0),
                    f.get("captured", 0), f.get("discarded", 0), f.get("unwound", 0),
                    collector.discard_reasons(), dl[0], dl[1],
                )
        # C12 (STORY-011): encola para persistencia batch (sin I/O directo aquí).
        if ctx.writer is not None:
            ctx.writer.enqueue_opportunity(opp)

    def feed_normalized(nb: NormalizedBook, *, record: bool, mark_live: bool) -> None:
        """Empuja un `NormalizedBook` al pipeline vivo: estado + grabación + quote SSE + bus.
        El camino vivo lo llama con record/mark_live=True; el fallback de demo (C16) lo reusa
        con record=False (no re-graba el replay → sin realimentación) y mark_live=False (no
        falsea la liveness REAL, que es lo que decide entrar/salir del replay)."""
        ctx.latest_norm[nb.exchange] = nb
        if record and ctx.recorder is not None:
            ctx.recorder.record(nb)         # C14 — graba para replay/demo (STORY-021)
        if mark_live and ctx.demo is not None:
            ctx.demo.mark_live()            # C16 — sella liveness real (STORY-024)
        publisher.publish_quote(nb)         # C11 → SSE (STORY-005)
        if ctx.bus is not None:
            ctx.bus.put_nowait(nb)

    # C1 → C3 → C4 — ingesta → normalización a USD → cola del motor + push SSE. Se
    # omite en tests (autostart=False) para no abrir conexiones a exchanges.
    def on_book(book: RawOrderBook) -> None:
        if ctx.integrity is not None and not ctx.integrity.check(book):
            return  # C2 (STORY-015): libro corrupto → no entra al estado vivo
        if ctx.demo is not None and ctx.demo.is_jury_mode:
            return  # PRD-002: la demo de jurado es determinista; no mezclar ticks live.
        ctx.latest_books[book.exchange] = book
        nb = ctx.normalizer.normalize(book) if ctx.normalizer else None
        if nb is not None:
            feed_normalized(nb, record=True, mark_live=True)

    # C16 (STORY-024): controlador de fallback a replay para demo. Inyecta ticks grabados por
    # el MISMO pipeline (record=False → sin realimentación; mark_live=False → no falsea la
    # liveness real). Se arma siempre (su `mark_live` lo llama el camino vivo), pero su tarea de
    # fondo sólo corre con autostart (en tests no hay feeds que vigilar).
    if settings.demo_fallback_enabled:
        ctx.demo = DemoFallback(
            ctx, settings,
            inject=lambda nb: feed_normalized(nb, record=False, mark_live=False),
            on_change=publisher.publish_demo,
        )

    if settings.ingest_autostart and settings.enabled_exchanges:
        ctx.ingestors = build_ingestors(settings, on_book=on_book)
        ctx.peg_ingestors = build_peg_ingestors(settings, ctx.peg)
        runners: list[Runner] = [*ctx.ingestors, *ctx.peg_ingestors]  # C1+C3 duck-typed
        ctx.tasks.append(asyncio.create_task(run_ingestors(runners), name="feeds"))
        ctx.tasks.append(
            asyncio.create_task(
                run_engine(
                    ctx.bus, ctx.detector, on_opp,
                    evaluator=ctx.evaluator, stat_detector=ctx.stat_detector,
                    prioritizer=ctx.prioritizer,
                ),
                name="engine",
            )
        )
        # C8 (STORY-014): watchdog de staleness — publica feed_status para el dashboard.
        watchdog = Watchdog(ctx, settings)
        ctx.tasks.append(asyncio.create_task(watchdog.run(), name="watchdog"))
        # C8 (STORY-018): circuit breakers — recomputa vol/skew/drawdown/stale cada tick y
        # emite el estado por SSE al cambiar. Depende de feed_status (watchdog) y portfolio.
        breaker_monitor = BreakerMonitor(
            ctx, settings, on_change=lambda mgr: publisher.publish_breaker(mgr.status())
        )
        ctx.tasks.append(asyncio.create_task(breaker_monitor.run(), name="breakers"))
        # C10 (STORY-017): rebalanceo de inventario PERIÓDICO (no por trade) — carga el coste
        # on-chain real al P&L cuando el skew de inventario supera el límite.
        if ctx.portfolio is not None:
            rebalancer = Rebalancer(ctx, settings)
            ctx.tasks.append(asyncio.create_task(rebalancer.run(), name="rebalancer"))
        # C16 (STORY-024): tarea del fallback de demo (auto-switch a replay si caen los feeds).
        if ctx.demo is not None:
            ctx.tasks.append(asyncio.create_task(ctx.demo.run(), name="demo"))
        log.info("autostart: %d feeds + %d peg + motor", len(ctx.ingestors), len(ctx.peg_ingestors))
    else:
        log.info("ingest autostart deshabilitado")

    try:
        yield
    finally:
        shutdown_runners: list[Runner] = [*ctx.ingestors, *ctx.peg_ingestors]
        for ing in shutdown_runners:
            await ing.close()
        for t in ctx.tasks:
            t.cancel()
        if ctx.tasks:
            await asyncio.gather(*ctx.tasks, return_exceptions=True)
        # C12 (STORY-011): flush final — drena la cola antes de cerrar la DB.
        if ctx.writer is not None:
            await ctx.writer.close()
        await hub.aclose()
        await _db_engine.dispose()
        log.info("shutdown complete")


API_DESCRIPTION = """
Motor de arbitraje BTC que no pregunta *dónde está más barato*, sino **cuánto queda después de
ejecutar** con profundidad de libro, fees, latencia, inventario y peg de stablecoin.

- **Correctitud:** reconciliación del ejemplo del reto ($109.75/BTC) + invariantes económicas.
- **Honestidad:** la mayoría de los spreads no sobreviven a los costes — y el dashboard muestra
  *exactamente dónde mueren*.
- **Proyección:** break-even frontier, capacity curve y forward Monte Carlo (bootstrap estacionario,
  PSR/DSR/MinTRL de López de Prado).

Todo es simulación con datos públicos: ninguna operación con dinero real. Los endpoints de control
y los overrides what-if no mutan umbrales operativos. Ver `GET /api/v1/info` para capacidades.
"""

API_VERSION = "0.1.0"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Arbitraje BTC — Motor de ejecución honesto",
        version=API_VERSION,
        description=API_DESCRIPTION,
        lifespan=lifespan,
        contact={"name": "Israel Domínguez", "url": "https://github.com/israads/arbitraje-btc"},
        license_info={"name": "Uso del challenge"},
        openapi_tags=[
            {"name": "mercado", "description": "Quotes, oportunidades y su explicación."},
            {"name": "proyección", "description": "Frontier, capacity, forward y análisis."},
            {"name": "control", "description": "Kill switch, demo y backtest (token opcional)."},
            {"name": "config", "description": "Parámetros what-if y retención de almacenamiento."},
            {"name": "sistema", "description": "Salud, métricas e información del servicio."},
        ],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Protecciones opcionales de API (default OFF): se montan solo si están configuradas.
    if settings.api_key or settings.api_rate_limit_per_min > 0:
        app.add_middleware(
            ApiGuardMiddleware,
            api_key=settings.api_key,
            rate_limit_per_min=settings.api_rate_limit_per_min,
        )

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics(request: Request) -> Response:
        return Response(
            render_prometheus(request.app.state.ctx),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    app.include_router(health_router)
    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
