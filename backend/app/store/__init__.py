"""C12 — Persistencia async/batch. FR-013.

Buffer + escritura por lotes desde un único writer async (fuera del camino caliente);
repos para oportunidades/ejecuciones/balances/P&L/métricas. SQLite→Postgres.

Implementación: STORY-011.
"""
from .db import Base, init_db, make_engine
from .writer import BatchWriter

__all__ = ["init_db", "make_engine", "Base", "BatchWriter"]
