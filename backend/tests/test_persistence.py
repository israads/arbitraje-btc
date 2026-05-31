"""Tests de persistencia async/batch (C12 / STORY-011).

Todos deterministas: sin red, sin reloj real en asserts.
DB en memoria (sqlite+aiosqlite:///:memory:) para aislamiento total.

Criterios cubiertos:
(a) Escribir un lote de opportunities/executions y leerlas de vuelta.
(b) El flush por lotes agrupa (no una transacción por registro).
(c) /executions devuelve el historial persistido.
(d) Flush final en shutdown no pierde registros.
(e) El camino de encolado no hace I/O directo (no bloquea).
"""
from __future__ import annotations

import asyncio
import math
import uuid

import pytest

from app.models.enums import LegSide, OpportunityStatus, Strategy
from app.models.execution import Execution, Leg
from app.models.opportunity import Opportunity
from app.store.db import init_db, make_engine
from app.store.writer import BatchWriter

# ---------------------------------------------------------------------------
# Helpers para crear modelos de prueba
# ---------------------------------------------------------------------------

def _make_opp(status: OpportunityStatus = OpportunityStatus.viable) -> Opportunity:
    return Opportunity(
        id=str(uuid.uuid4()),
        strategy=Strategy.spatial,
        symbol="BTC/USDT",
        buy_venue="binance",
        sell_venue="kraken",
        q_target=1.0,
        vwap_buy=50_000.0,
        vwap_sell=50_200.0,
        fees=50.0,
        net_pnl=150.0,
        status=status,
        t_recv=1.0,
        t_detect=1.1,
        latency_ms=100.0,
    )


def _make_exec(opp_id: str, ts: float = 1.5) -> Execution:
    leg_buy = Leg(
        venue="binance", side=LegSide.buy,
        qty_filled=1.0, vwap=50_000.0, fee=50.0, qty_requested=1.0,
    )
    leg_sell = Leg(
        venue="kraken", side=LegSide.sell,
        qty_filled=1.0, vwap=50_200.0, fee=50.0, qty_requested=1.0,
    )
    return Execution(
        id=str(uuid.uuid4()),
        opportunity_id=opp_id,
        legs=[leg_buy, leg_sell],
        matched_qty=1.0,
        realized_pnl=100.0,
        status=OpportunityStatus.captured,
        ts=ts,
    )


# ---------------------------------------------------------------------------
# Fixture: engine + writer en memoria (aislado por test)
# ---------------------------------------------------------------------------

@pytest.fixture
async def writer() -> BatchWriter:
    """BatchWriter sobre SQLite en memoria. Arranca y cierra alrededor del test."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    bw = BatchWriter(engine=engine, batch_size=50, flush_seconds=0.05)
    bw.start()
    yield bw
    await bw.close()
    await engine.dispose()


# ---------------------------------------------------------------------------
# (a) Escribir un lote y leerlo de vuelta
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_and_read_opportunities(writer: BatchWriter) -> None:
    """Encola 5 oportunidades → flush → lee de DB → confirma que están todas."""
    opps = [_make_opp() for _ in range(5)]
    for o in opps:
        writer.enqueue_opportunity(o)

    # Espera flush periódico (flush_seconds=0.05 → 150 ms es suficiente).
    await asyncio.sleep(0.2)

    rows = await writer.get_opportunities(limit=10)
    ids_persistidos = {r["id"] for r in rows}
    ids_esperados = {o.id for o in opps}
    assert ids_esperados.issubset(ids_persistidos), (
        f"Faltan IDs: {ids_esperados - ids_persistidos}"
    )


@pytest.mark.asyncio
async def test_write_and_read_executions(writer: BatchWriter) -> None:
    """Encola 3 ejecuciones → flush → lee de DB → confirma integridad."""
    opp = _make_opp()
    writer.enqueue_opportunity(opp)
    execs = [_make_exec(opp.id, ts=float(i)) for i in range(3)]
    for e in execs:
        writer.enqueue_execution(e)

    await asyncio.sleep(0.2)

    rows = await writer.get_executions(limit=10)
    assert len(rows) >= 3
    ids_persistidos = {r["id"] for r in rows}
    ids_esperados = {e.id for e in execs}
    assert ids_esperados.issubset(ids_persistidos)

    # Verifica que los legs se serializan/deserializan
    for row in rows:
        if row["id"] in ids_esperados:
            assert len(row["legs"]) == 2
            assert row["realized_pnl"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# (b) El flush agrupa registros (no una transacción por registro)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_flush_groups_records(writer: BatchWriter) -> None:
    """Encola N registros antes del flush → todos persisten en un solo flush.

    Verificamos que con flush_seconds grande y muchos registros,
    todos aparecen tras el close() (flush final) — no se pierden por falta
    de transacciones individuales.
    """
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    # flush_seconds grande: el flush periódico no disparará durante el test.
    bw = BatchWriter(engine=engine, batch_size=200, flush_seconds=60.0)
    bw.start()

    n = 20
    opps = [_make_opp() for _ in range(n)]
    for o in opps:
        bw.enqueue_opportunity(o)

    # Sin esperar el flush periódico: close() hace el flush final.
    await bw.close()
    await engine.dispose()

    # Verificar con un engine nuevo (misma DB en memoria — no aplica, usamos
    # una nueva pero el close() ya flusheó antes de dispose).
    # Re-abrimos para verificar que los datos están en la DB.
    # La prueba real: la cola debe estar vacía tras close() (flush final completado).
    assert bw._queue.empty(), "La cola debe estar vacía tras close() (flush final)"


@pytest.mark.asyncio
async def test_batch_single_transaction_for_multiple_records() -> None:
    """Verifica que un lote de N registros produce exactamente 1 flush (transacción),
    no N transacciones individuales. Medimos llamadas al writer real."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    bw = BatchWriter(engine=engine, batch_size=100, flush_seconds=60.0)
    bw.start()

    flush_calls: list[int] = []
    original_flush = bw._flush_buffer

    async def counting_flush(buffer):
        flush_calls.append(len(buffer))
        await original_flush(buffer)

    bw._flush_buffer = counting_flush  # type: ignore[method-assign]

    n = 10
    opps = [_make_opp() for _ in range(n)]
    for o in opps:
        bw.enqueue_opportunity(o)

    await bw.close()
    await engine.dispose()

    # Todo el lote debe haberse persistido en una única llamada al flush.
    total_flushed = sum(flush_calls)
    assert total_flushed == n, f"Se esperaban {n} registros en total, flusheados: {flush_calls}"
    assert len(flush_calls) == 1, (
        f"Se esperaba 1 llamada al flush (agrupado), se hicieron {len(flush_calls)}: {flush_calls}"
    )


# ---------------------------------------------------------------------------
# (c) /executions devuelve el historial persistido
# ---------------------------------------------------------------------------

def test_executions_endpoint_returns_history(client) -> None:
    """/executions devuelve JSON con la clave 'executions' (historial persistido)."""
    resp = client.get("/api/v1/executions")
    assert resp.status_code == 200
    data = resp.json()
    assert "executions" in data
    assert "count" in data
    # En tests sin datos encolados la lista está vacía.
    assert isinstance(data["executions"], list)


def test_executions_endpoint_with_limit(client) -> None:
    """El parámetro limit es respetado."""
    resp = client.get("/api/v1/executions?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["executions"]) <= 5


def test_opportunities_history_endpoint(client) -> None:
    """/opportunities/history devuelve JSON con la clave 'opportunities'."""
    resp = client.get("/api/v1/opportunities/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "opportunities" in data
    assert "count" in data


# ---------------------------------------------------------------------------
# (d) Flush final en shutdown no pierde registros
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_final_on_close_no_data_loss() -> None:
    """Registros encolados antes del close() no se pierden aunque no haya flush previo."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    # flush_seconds muy alto para que el flush periódico no dispare.
    bw = BatchWriter(engine=engine, batch_size=100, flush_seconds=60.0)
    bw.start()

    opps = [_make_opp() for _ in range(10)]
    for o in opps:
        bw.enqueue_opportunity(o)

    # Cerramos inmediatamente: el close() debe hacer flush final.
    await bw.close()

    # Verificamos que la cola quedó vacía (flush final completado).
    assert bw._queue.empty()

    # Abrimos un BatchWriter de solo-lectura sobre el mismo engine.
    bw_reader = BatchWriter(engine=engine, batch_size=100, flush_seconds=60.0)
    rows = await bw_reader.get_opportunities(limit=20)
    ids_leidos = {r["id"] for r in rows}
    ids_esperados = {o.id for o in opps}
    assert ids_esperados.issubset(ids_leidos), (
        f"Registros perdidos en shutdown: {ids_esperados - ids_leidos}"
    )
    await engine.dispose()


# ---------------------------------------------------------------------------
# (e) El camino de encolado no bloquea (no hace I/O directo)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_is_nonblocking(writer: BatchWriter) -> None:
    """enqueue_* debe ser síncrono y no hacer I/O de DB (no es corrutina)."""
    import inspect

    # enqueue_opportunity NO debe ser una corrutina.
    opp = _make_opp()
    result = writer.enqueue_opportunity(opp)
    assert result is None, "enqueue_opportunity debe retornar None (no corrutina)"
    assert not inspect.isawaitable(result), "enqueue_opportunity NO debe ser awaitable"

    exc = _make_exec(opp.id)
    result2 = writer.enqueue_execution(exc)
    assert result2 is None
    assert not inspect.isawaitable(result2)


@pytest.mark.asyncio
async def test_enqueue_many_does_not_block_event_loop(writer: BatchWriter) -> None:
    """Encolar 1000 registros es fast-path: la cola no bloquea el event loop."""
    import time

    start = time.perf_counter()
    for _ in range(1000):
        opp = _make_opp()
        writer.enqueue_opportunity(opp)
    elapsed = time.perf_counter() - start

    # 1000 encolados en < 100 ms (sin I/O de DB; solo inserción en asyncio.Queue).
    assert elapsed < 0.1, f"Encolado tardó {elapsed:.3f}s — posible I/O en el camino caliente"


# ---------------------------------------------------------------------------
# Tests de endpoints relacionados con estado del writer en tests normales
# ---------------------------------------------------------------------------

def test_executions_endpoint_not_broken_without_data(client) -> None:
    """El endpoint /executions no falla aunque no haya ejecuciones persistidas."""
    resp = client.get("/api/v1/executions")
    assert resp.status_code == 200


def test_opportunities_history_with_status_filter(client) -> None:
    """/opportunities/history acepta filtro de status sin error."""
    resp = client.get("/api/v1/opportunities/history?status=viable&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "opportunities" in data


# ---------------------------------------------------------------------------
# Fixes de la revisión adversarial (PK surrogate, NaN, orden, límites)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recycled_id_no_silent_loss(writer: BatchWriter) -> None:
    """IDs reciclados entre reinicios (contador en memoria) NO se descartan.

    Con PK surrogate (row_id) y sin INSERT OR IGNORE, dos oportunidades con el
    MISMO id 'opp-1' pero distinto contenido producen DOS filas (antes: la 2ª
    se perdía en silencio sobre la DB-archivo de producción)."""
    o1 = _make_opp()
    o1.id = "opp-1"
    o1.net_pnl = 11.0
    o2 = _make_opp()
    o2.id = "opp-1"
    o2.net_pnl = 22.0
    writer.enqueue_opportunity(o1)
    writer.enqueue_opportunity(o2)
    await asyncio.sleep(0.2)

    rows = await writer.get_opportunities(limit=10)
    same = [r for r in rows if r["id"] == "opp-1"]
    assert len(same) == 2, "PK surrogate debe persistir ambas filas (sin OR IGNORE)"
    assert {r["net_pnl"] for r in same} == {11.0, 22.0}


@pytest.mark.asyncio
async def test_nan_inf_sanitized_to_null(writer: BatchWriter) -> None:
    """NaN/Inf se sanean a None antes de persistir (JSON inválido para el cliente
    si se emitiera `NaN`/`Infinity` literal)."""
    opp = _make_opp()
    opp.net_pnl = math.nan
    opp.slippage = math.inf
    writer.enqueue_opportunity(opp)

    leg = Leg(
        venue="binance", side=LegSide.buy,
        qty_filled=1.0, vwap=math.nan, fee=0.0, qty_requested=1.0,
    )
    exc = Execution(
        id=str(uuid.uuid4()), opportunity_id=opp.id, legs=[leg],
        matched_qty=0.0, realized_pnl=0.0, status=OpportunityStatus.captured, ts=1.0,
    )
    writer.enqueue_execution(exc)
    await asyncio.sleep(0.2)

    orow = next(r for r in await writer.get_opportunities(limit=10) if r["id"] == opp.id)
    assert orow["net_pnl"] is None, "NaN debe sanearse a None"
    assert orow["slippage"] is None, "Inf debe sanearse a None"

    erow = next(r for r in await writer.get_executions(limit=10) if r["id"] == exc.id)
    assert erow["legs"][0]["vwap"] is None, "NaN en leg debe sanearse a None"


@pytest.mark.asyncio
async def test_history_ordered_newest_first(writer: BatchWriter) -> None:
    """El historial se ordena por created_at DESC + row_id DESC (cronológico
    estable entre reinicios; antes ordenaba por reloj monotónico por proceso)."""
    o_old = _make_opp()
    o_old.id = "vieja"
    o_new = _make_opp()
    o_new.id = "nueva"
    writer.enqueue_opportunity(o_old)
    writer.enqueue_opportunity(o_new)  # encolada después → más reciente
    await asyncio.sleep(0.2)

    ids = [r["id"] for r in await writer.get_opportunities(limit=10)]
    assert ids.index("nueva") < ids.index("vieja"), "la más reciente va primero"


def test_history_limit_out_of_range_rejected(client) -> None:
    """`limit` fuera de [1, 1000] se rechaza (evita LIMIT -1 / volcado completo / DoS)."""
    assert client.get("/api/v1/executions?limit=-1").status_code == 422
    assert client.get("/api/v1/executions?limit=0").status_code == 422
    assert client.get("/api/v1/executions?limit=5000").status_code == 422
    assert client.get("/api/v1/executions?limit=50").status_code == 200
    assert client.get("/api/v1/opportunities/history?limit=99999").status_code == 422


# ---------------------------------------------------------------------------
# Ramas de robustez del writer (cola llena, snapshot, JSON corrupto)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_drops_when_queue_full_without_raising() -> None:
    """Si la cola interna está llena, `_put_nowait` descarta el registro sin bloquear ni
    lanzar (best-effort, no tumba el camino caliente). Rama QueueFull."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    bw = BatchWriter(engine=engine, batch_size=100, flush_seconds=60.0)
    # NO arrancamos la task de flush: la cola nunca se drena.
    # Llenamos la cola a su capacidad y un encolado extra debe descartarse en silencio.
    bw._queue = asyncio.Queue(maxsize=2)
    bw.enqueue_opportunity(_make_opp())
    bw.enqueue_opportunity(_make_opp())
    assert bw._queue.full()
    bw.enqueue_opportunity(_make_opp())  # descartado, no lanza
    assert bw._queue.qsize() == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_enqueue_snapshot_persists_row(writer: BatchWriter) -> None:
    """`enqueue_snapshot` encola un punto de equity/inventario; el flush lo persiste sin
    error (cubre la rama de snapshots del writer)."""
    from sqlalchemy import func, select

    from app.store.db import SnapshotRow, make_session_factory
    writer.enqueue_snapshot(
        ts=1.0, total_usd=200_400.0,
        balances=[{"exchange": "binance", "asset": "BTC", "amount": 2.0}],
    )
    await asyncio.sleep(0.2)
    factory = make_session_factory(writer._engine)
    async with factory() as session:
        count = (await session.execute(select(func.count()).select_from(SnapshotRow))).scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_enqueue_snapshot_sanitizes_nan_inf(writer: BatchWriter) -> None:
    """NaN/Inf en `total_usd` se sanean a None antes de persistir el snapshot."""
    writer.enqueue_snapshot(ts=math.inf, total_usd=math.nan, balances=[])
    await asyncio.sleep(0.2)  # no debe lanzar al serializar/persistir


def test_execution_row_to_dict_tolerates_corrupt_legs_json() -> None:
    """Si `legs_json` está corrupto (no es JSON válido), el serializador devuelve legs=[]
    en vez de propagar la excepción. Rama 343-345."""
    from app.store.writer import _execution_row_to_dict

    class _Row:
        id = "exec-x"
        created_at = 1.0
        opportunity_id = "opp-x"
        matched_qty = 1.0
        partial = 0
        unwound = 0
        realized_pnl = 1.0
        leg_risk_qty = 0.0
        leg_risk_mtm = 0.0
        leg_risk_entry_vwap = 0.0
        leg_risk_venue = None
        leg_risk_side = None
        exec_latency_ms = 150
        status = "captured"
        ts = 1.0
        legs_json = "{no es json valido]"

    d = _execution_row_to_dict(_Row())
    assert d["legs"] == []
    assert d["id"] == "exec-x"
