"""C12 — Escritor async por lotes (batch writer). FR-013.

El camino caliente (on_opp) llama a `enqueue_*` que es O(1) sin I/O: solo
inserta en una `asyncio.Queue` en memoria. Una task de fondo (`_flush_loop`)
vacía la cola en lotes periódicamente o al alcanzar `batch_size` registros.

Garantías:
- La persistencia es best-effort: un error de DB se loggea pero NO tumba el
  pipeline de trading.
- El flush final en shutdown (`close()`) drena la cola antes de cerrar.
- Concurrencia 0 por diseño: un único writer (esta task) escribe en la DB.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import Any

from sqlalchemy import insert as sa_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ..models.execution import Execution
from ..models.opportunity import Opportunity
from .db import Base, ExecutionRow, OpportunityRow, SnapshotRow, make_session_factory

log = logging.getLogger("app.store.writer")

# Tipo del item en la cola: ("opportunity" | "execution" | "snapshot", dict)
_QueueItem = tuple[str, dict[str, Any]]


def _clean(value: Any) -> Any:
    """Sanea NaN/Inf → None en floats (JSON inválido para el cliente si no).

    Recursivo sobre dict/list para limpiar también estructuras anidadas (legs,
    balances) antes de serializarlas a JSON.
    """
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _dumps_safe(obj: Any) -> str:
    """Serializa a JSON saneando NaN/Inf → None (nunca emite `NaN` literal)."""
    return json.dumps(_clean(obj))


class BatchWriter:
    """Escritor async por lotes. Un único consumidor de la cola interna.

    Parámetros
    ----------
    engine:
        AsyncEngine de SQLAlchemy (ya inicializado con `init_db`).
    batch_size:
        Número máximo de registros por lote (vacía antes si se alcanza).
    flush_seconds:
        Intervalo de flush periódico aunque no se alcance `batch_size`.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        batch_size: int = 100,
        flush_seconds: float = 1.0,
    ) -> None:
        self._engine = engine
        self._batch_size = batch_size
        self._flush_seconds = flush_seconds
        self._session_factory: async_sessionmaker[AsyncSession] = make_session_factory(engine)
        # Cola acotada: si el producer es muy rápido (improbable, es best-effort)
        # descartamos sin bloquear el camino caliente.
        self._queue: asyncio.Queue[_QueueItem] = asyncio.Queue(maxsize=10_000)
        self._task: asyncio.Task[None] | None = None
        self._running = False
        # Throttle del log de descartes: bajo overflow sostenido (mercado activo,
        # CPU escasa) un warning POR registro llega a >400 líneas/s — eso quema
        # loop y disco. Se agrega en un contador y se reporta como máximo cada 5 s.
        self._drops_since_log = 0
        self._last_drop_log = 0.0

    # ------------------------------------------------------------------
    # API de encolado (camino caliente — sin I/O de DB)
    # ------------------------------------------------------------------

    def enqueue_opportunity(self, opp: Opportunity) -> None:
        """Encola una oportunidad. Nunca bloquea; descarta si la cola está llena.

        Sella `created_at` (epoch real) en el encolado para orden cronológico
        estable entre reinicios, y sanea NaN/Inf de los floats.
        """
        row = {
            "id": opp.id,
            "created_at": time.time(),
            "strategy": opp.strategy.value,
            "symbol": opp.symbol,
            "buy_venue": opp.buy_venue,
            "sell_venue": opp.sell_venue,
            "status": opp.status.value,
            "discard_reason": opp.discard_reason.value if opp.discard_reason else None,
            "q_target": _clean(opp.q_target),
            "vwap_buy": _clean(opp.vwap_buy),
            "vwap_sell": _clean(opp.vwap_sell),
            "fees": _clean(opp.fees),
            "slippage": _clean(opp.slippage),
            "net_pnl": _clean(opp.net_pnl),
            "z_score": _clean(opp.z_score),
            "score": _clean(opp.score),
            "t_recv": _clean(opp.t_recv),
            "t_detect": _clean(opp.t_detect),
            "latency_ms": _clean(opp.latency_ms),
        }
        self._put_nowait("opportunity", row)

    def enqueue_execution(self, exc: Execution) -> None:
        """Encola una ejecución simulada. Nunca bloquea.

        Sella `created_at` y sanea NaN/Inf tanto en floats como en los legs
        serializados a JSON (evita `NaN` literal en la respuesta al cliente).
        """
        row = {
            "id": exc.id,
            "created_at": time.time(),
            "opportunity_id": exc.opportunity_id,
            "matched_qty": _clean(exc.matched_qty),
            "partial": int(exc.partial),
            "unwound": int(exc.unwound),
            "realized_pnl": _clean(exc.realized_pnl),
            "leg_risk_qty": _clean(exc.leg_risk_qty),
            "leg_risk_mtm": _clean(exc.leg_risk_mtm),
            "leg_risk_entry_vwap": _clean(exc.leg_risk_entry_vwap),
            "leg_risk_venue": exc.leg_risk_venue,
            "leg_risk_side": exc.leg_risk_side.value if exc.leg_risk_side else None,
            "exec_latency_ms": exc.exec_latency_ms,
            "status": exc.status.value,
            "ts": _clean(exc.ts),
            "legs_json": _dumps_safe([leg.model_dump() for leg in exc.legs]),
        }
        self._put_nowait("execution", row)

    def enqueue_snapshot(self, ts: float, total_usd: float | None, balances: list[Any]) -> None:
        """Encola un snapshot de equity/inventario."""
        row = {
            "ts": _clean(ts),
            "total_usd": _clean(total_usd),
            "balances_json": _dumps_safe(balances),
        }
        self._put_nowait("snapshot", row)

    def _put_nowait(self, kind: str, data: dict[str, Any]) -> None:
        """Inserta en la cola sin bloquear. Descarta (con log agregado) si está llena."""
        try:
            self._queue.put_nowait((kind, data))
        except asyncio.QueueFull:
            self._drops_since_log += 1
            now = time.monotonic()
            if now - self._last_drop_log >= 5.0:
                log.warning(
                    "Cola de persistencia llena; %d registros descartados desde el último "
                    "aviso (último: %s)",
                    self._drops_since_log,
                    kind,
                )
                self._drops_since_log = 0
                self._last_drop_log = now

    # ------------------------------------------------------------------
    # Ciclo de flushing (task de fondo)
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Lanza la task de flush. Debe llamarse dentro del event loop."""
        self._running = True
        self._task = asyncio.create_task(self._flush_loop(), name="persistence_flush")

    def is_alive(self) -> bool:
        """`True` si la task de flush sigue viva (para /health). Una task muerta
        significa persistencia caída el resto de la sesión."""
        return self._task is not None and not self._task.done()

    async def close(self) -> None:
        """Detiene el escritor y hace flush final de lo que quede en la cola.

        Shutdown cooperativo: la cancelación de la task se captura DENTRO de
        `_flush_loop`, que persiste su buffer en vuelo antes de re-propagar.
        Aquí drenamos además la cola restante. Así no se pierde ningún registro
        encolado ni el lote que estaba a medio camino.
        """
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Flush final: drena la cola antes de cerrar (no perder registros en shutdown).
        await self._flush_all()

    async def _flush_loop(self) -> None:
        """Loop de flushing: vacía la cola al alcanzar batch_size o por timeout.

        Robusto ante:
        - CancelledError (shutdown): persiste el buffer en vuelo antes de re-propagar.
        - Cualquier otra excepción del ciclo: se loggea y se continúa (la task
          NO debe morir y dejar la persistencia inerte el resto de la sesión).
        """
        buffer: list[_QueueItem] = []
        while self._running:
            try:
                try:
                    # Espera hasta flush_seconds o hasta que llegue un item.
                    item = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=self._flush_seconds,
                    )
                    buffer.append(item)
                    self._queue.task_done()
                    # Drena síncronamente lo que ya esté disponible (sin await).
                    while not self._queue.empty() and len(buffer) < self._batch_size:
                        try:
                            extra = self._queue.get_nowait()
                            buffer.append(extra)
                            self._queue.task_done()
                        except asyncio.QueueEmpty:
                            break
                except TimeoutError:
                    pass  # timeout periódico → flush de lo acumulado

                if buffer:
                    await self._flush_buffer(buffer)
                    buffer = []
            except asyncio.CancelledError:
                # Shutdown: no perder el lote en vuelo. Lo persistimos con escudo
                # ante la cancelación y re-propagamos para terminar la task.
                if buffer:
                    await asyncio.shield(self._flush_buffer(buffer))
                raise
            except Exception:
                # Cinturón de seguridad: una excepción inesperada del ciclo no
                # debe matar la task. Loggea, descarta el buffer problemático y
                # sigue (best-effort).
                log.exception("Error en _flush_loop (continuando, persistencia viva)")
                buffer = []

    async def _flush_all(self) -> None:
        """Drena toda la cola y la persiste (llamado en shutdown)."""
        buffer: list[_QueueItem] = []
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                buffer.append(item)
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break
        if buffer:
            await self._flush_buffer(buffer)

    async def _flush_buffer(self, buffer: list[_QueueItem]) -> None:
        """Persiste un lote en una única transacción.

        Sin `OR IGNORE`: con PK surrogate cada registro inserta su propia fila
        (no hay colisión de IDs reciclados). Si el INSERT por lote falla (p.ej.
        un registro corrupto que SQLite rechaza), se hace fallback a inserción
        REGISTRO-POR-REGISTRO para no perder los sanos.
        """
        if not buffer:
            return
        opps = [d for k, d in buffer if k == "opportunity"]
        execs = [d for k, d in buffer if k == "execution"]
        snaps = [d for k, d in buffer if k == "snapshot"]
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    if opps:
                        await session.execute(sa_insert(OpportunityRow).values(opps))
                    if execs:
                        await session.execute(sa_insert(ExecutionRow).values(execs))
                    if snaps:
                        await session.execute(sa_insert(SnapshotRow).values(snaps))
            log.debug(
                "flush: %d opps, %d execs, %d snaps",
                len(opps), len(execs), len(snaps),
            )
        except Exception:
            log.exception(
                "Error en flush por lote; fallback a inserción registro-por-registro"
            )
            await self._flush_row_by_row(opps, OpportunityRow)
            await self._flush_row_by_row(execs, ExecutionRow)
            await self._flush_row_by_row(snaps, SnapshotRow)

    async def _flush_row_by_row(self, rows: list[dict[str, Any]], model: type[Base]) -> None:
        """Inserta fila por fila (best-effort): persiste las sanas y loggea las que
        fallen. Evita que un único registro corrupto tire el lote entero."""
        for row in rows:
            try:
                async with self._session_factory() as session:
                    async with session.begin():
                        await session.execute(sa_insert(model).values([row]))
            except Exception:
                log.exception(
                    "Registro descartado en fallback (%s): %r", model.__tablename__, row
                )

    # ------------------------------------------------------------------
    # Consultas de historial (usadas por los endpoints REST)
    # ------------------------------------------------------------------

    async def get_executions(self, limit: int = 100) -> list[dict[str, Any]]:
        """Devuelve las últimas `limit` ejecuciones persistidas.

        Orden cronológico por `created_at` (epoch del encolado) DESC, con
        desempate por `row_id` DESC. Correcto incluso entre reinicios (no usa
        `ts`, que es monotónico por proceso)."""
        from sqlalchemy import desc, select
        async with self._session_factory() as session:
            result = await session.execute(
                select(ExecutionRow)
                .order_by(desc(ExecutionRow.created_at), desc(ExecutionRow.row_id))
                .limit(limit)
            )
            rows = result.scalars().all()
        return [_execution_row_to_dict(r) for r in rows]

    async def get_opportunities(
        self, limit: int = 100, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Devuelve las últimas `limit` oportunidades persistidas.

        Orden cronológico por `created_at` DESC + `row_id` DESC (ver
        `get_executions`)."""
        from sqlalchemy import desc, select
        async with self._session_factory() as session:
            q = select(OpportunityRow).order_by(
                desc(OpportunityRow.created_at), desc(OpportunityRow.row_id)
            )
            if status:
                q = q.where(OpportunityRow.status == status)
            q = q.limit(limit)
            result = await session.execute(q)
            rows = result.scalars().all()
        return [_opportunity_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Helpers de serialización fila → dict
# ---------------------------------------------------------------------------

def _execution_row_to_dict(r: ExecutionRow) -> dict[str, Any]:
    legs = []
    if r.legs_json:
        try:
            legs = json.loads(str(r.legs_json))
        except Exception:
            pass
    return {
        "id": r.id,
        "created_at": r.created_at,
        "opportunity_id": r.opportunity_id,
        "matched_qty": r.matched_qty,
        "partial": bool(r.partial),
        "unwound": bool(r.unwound),
        "realized_pnl": r.realized_pnl,
        "leg_risk_qty": r.leg_risk_qty,
        "leg_risk_mtm": r.leg_risk_mtm,
        "leg_risk_entry_vwap": r.leg_risk_entry_vwap,
        "leg_risk_venue": r.leg_risk_venue,
        "leg_risk_side": r.leg_risk_side,
        "exec_latency_ms": r.exec_latency_ms,
        "status": r.status,
        "ts": r.ts,
        "legs": legs,
    }


def _opportunity_row_to_dict(r: OpportunityRow) -> dict[str, Any]:
    return {
        "id": r.id,
        "created_at": r.created_at,
        "strategy": r.strategy,
        "symbol": r.symbol,
        "buy_venue": r.buy_venue,
        "sell_venue": r.sell_venue,
        "status": r.status,
        "discard_reason": r.discard_reason,
        "q_target": r.q_target,
        "vwap_buy": r.vwap_buy,
        "vwap_sell": r.vwap_sell,
        "fees": r.fees,
        "slippage": r.slippage,
        "net_pnl": r.net_pnl,
        "z_score": r.z_score,
        "score": r.score,
        "t_recv": r.t_recv,
        "t_detect": r.t_detect,
        "latency_ms": r.latency_ms,
    }
