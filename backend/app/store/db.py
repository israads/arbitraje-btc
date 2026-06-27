"""C12 — Motor de base de datos async (SQLAlchemy 2.x + aiosqlite).

Crea el engine y las tablas de forma idempotente al startup. La URL se lee
de `Settings.db_url`; en tests se sobreescribe con `ARB_DB_URL` para apuntar
a `:memory:` y no contaminar el archivo de producción.
"""
from __future__ import annotations

import logging

from sqlalchemy import Column, Float, Integer, String, Text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

log = logging.getLogger("app.store.db")


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Definición de tablas — columnas simples (sin FK cross-tabla) para máxima
# portabilidad SQLite ↔ Postgres y mínima latencia de escritura.
# ---------------------------------------------------------------------------

class OpportunityRow(Base):
    """Registro de cada oportunidad que pasó por el pipeline.

    PK SURROGATE (`row_id` autoincrement): la columna `id` (opp-N) NO es única
    porque el detector recicla IDs entre reinicios (contador en memoria). Cada
    encolado inserta una fila nueva, sin descartes silenciosos por colisión.
    """

    __tablename__ = "opportunities"

    row_id = Column(Integer, primary_key=True, autoincrement=True)
    id = Column(String, nullable=False, index=True)   # informativo, NO único
    # epoch de time.time() sellado en el momento del encolado (orden cronológico
    # estable entre reinicios; t_detect es monotónico y se reinicia por proceso).
    created_at = Column(Float, nullable=False, default=0.0, index=True)
    strategy = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    buy_venue = Column(String, nullable=False)
    sell_venue = Column(String, nullable=False)
    status = Column(String, nullable=False)
    discard_reason = Column(String, nullable=True)
    q_target = Column(Float, nullable=False, default=0.0)
    vwap_buy = Column(Float, nullable=True)
    vwap_sell = Column(Float, nullable=True)
    fees = Column(Float, nullable=True)
    slippage = Column(Float, nullable=True)
    net_pnl = Column(Float, nullable=True)
    z_score = Column(Float, nullable=True)
    score = Column(Float, nullable=True)
    t_recv = Column(Float, nullable=True)
    t_detect = Column(Float, nullable=True)
    latency_ms = Column(Float, nullable=True)


class ExecutionRow(Base):
    """Registro de cada ejecución simulada.

    PK SURROGATE (`row_id`): igual que OpportunityRow, `id` (exec-opp-N) se
    recicla entre reinicios, así que es columna indexada NO única e informativa.
    """

    __tablename__ = "executions"

    row_id = Column(Integer, primary_key=True, autoincrement=True)
    id = Column(String, nullable=False, index=True)   # informativo, NO único
    created_at = Column(Float, nullable=False, default=0.0, index=True)
    opportunity_id = Column(String, nullable=False)
    matched_qty = Column(Float, nullable=False, default=0.0)
    partial = Column(Integer, nullable=False, default=0)   # bool como int
    unwound = Column(Integer, nullable=False, default=0)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    leg_risk_qty = Column(Float, nullable=False, default=0.0)
    leg_risk_mtm = Column(Float, nullable=False, default=0.0)
    leg_risk_entry_vwap = Column(Float, nullable=False, default=0.0)
    leg_risk_venue = Column(String, nullable=True)
    leg_risk_side = Column(String, nullable=True)
    exec_latency_ms = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False)
    ts = Column(Float, nullable=True)
    legs_json = Column(Text, nullable=True)   # serialización JSON de la lista de legs


class SnapshotRow(Base):
    """Punto de equity/inventario snapshotado periódicamente (equity curve)."""

    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(Float, nullable=False)
    total_usd = Column(Float, nullable=True)
    balances_json = Column(Text, nullable=True)   # JSON de la lista de balances


class AppConfigRow(Base):
    """Configuración base persistida (key-value JSON). Sobrevive reinicios y se aplica a
    `Settings` al arrancar, antes de crear el motor/portfolio."""

    __tablename__ = "app_config"

    key = Column(String, primary_key=True)
    value_json = Column(Text, nullable=False)


# ---------------------------------------------------------------------------
# Factory de engine y sesión
# ---------------------------------------------------------------------------

def make_engine(db_url: str) -> AsyncEngine:
    """Crea el engine async. `check_same_thread=False` necesario para SQLite."""
    connect_args = {}
    if "sqlite" in db_url:
        connect_args["check_same_thread"] = False
    return create_async_engine(
        db_url,
        connect_args=connect_args,
        echo=False,
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    """Crea todas las tablas de forma idempotente (CREATE TABLE IF NOT EXISTS)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("DB inicializada: tablas listas")
