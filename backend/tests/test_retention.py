from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import insert as sa_insert
from sqlalchemy import text

from app.store.db import OpportunityRow, init_db, make_engine
from app.store.retention import measure_storage, prune_old_rows

NOW = 1_800_000_000.0


def _opp_row(i: int, created_at: float) -> dict:
    return {
        "id": f"opp-{i}",
        "created_at": created_at,
        "strategy": "spatial",
        "symbol": "BTC/USD",
        "buy_venue": "binance",
        "sell_venue": "kraken",
        "status": "detected",
        "q_target": 1.0,
        "vwap_buy": 100.0,
        "vwap_sell": 110.0,
    }


async def _seed(engine, rows: list[dict]) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa_insert(OpportunityRow).values(rows))


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'ret.db'}"


async def test_measure_storage_reports_rows_and_estimates(db_url: str) -> None:
    engine = make_engine(db_url)
    await init_db(engine)
    # 100 filas repartidas en 1 hora → tasa medible.
    rows = [_opp_row(i, NOW - 3600.0 + i * 36.0) for i in range(100)]
    await _seed(engine, rows)

    stats = await measure_storage(engine, db_url, retention_hours=24.0)
    assert stats.opp_rows == 100
    assert stats.span_seconds > 0
    assert stats.rows_per_second > 0
    assert stats.bytes_per_row > 0
    assert stats.retention_hours == 24.0
    # Una estimación por cada ventana ofrecida, creciente con las horas.
    assert len(stats.estimates) == 5
    by_h = {e.retention_hours: e.bytes for e in stats.estimates}
    assert by_h[1] < by_h[24]
    await engine.dispose()


async def test_prune_removes_old_rows_only(db_url: str) -> None:
    engine = make_engine(db_url)
    await init_db(engine)
    old = [_opp_row(i, NOW - 10 * 3600.0) for i in range(5)]      # 10 h de antigüedad
    fresh = [_opp_row(100 + i, NOW - 1 * 3600.0) for i in range(7)]  # 1 h
    await _seed(engine, old + fresh)

    deleted = await prune_old_rows(engine, retention_hours=5.0, now=NOW)
    assert deleted["opportunities"] == 5

    async with engine.connect() as conn:
        remaining = (await conn.execute(text("SELECT count(*) FROM opportunities"))).scalar()
    assert remaining == 7
    await engine.dispose()


async def test_prune_zero_retention_is_noop(db_url: str) -> None:
    engine = make_engine(db_url)
    await init_db(engine)
    await _seed(engine, [_opp_row(i, NOW - 100 * 3600.0) for i in range(3)])

    deleted = await prune_old_rows(engine, retention_hours=0.0, now=NOW)
    assert deleted == {"opportunities": 0, "executions": 0}

    async with engine.connect() as conn:
        remaining = (await conn.execute(text("SELECT count(*) FROM opportunities"))).scalar()
    assert remaining == 3
    await engine.dispose()
