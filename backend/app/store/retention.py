"""Retención y medición de almacenamiento de la DB (C12).

Las `opportunities` se insertan a ~36/s en operación real (~28 MB/h, ~670 MB/día). Sin poda
la DB crece sin límite (en pruebas llegó a 14 GB en ~21 días). Aquí vive:

- `measure_storage`: mide tamaño real, filas, tasa de inserción y bytes/fila DESDE la propia DB,
  y proyecta el almacenamiento en estado estacionario para varias ventanas de retención.
- `prune_old_rows`: borra filas más viejas que la ventana de retención (DELETE por `created_at`).

Es operación de mantenimiento: corre en una task de fondo aparte del camino caliente.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger("app.store.retention")

# Ventanas ofrecidas en la UI (horas). 0 = sin límite.
RETENTION_CHOICES_H: tuple[int, ...] = (1, 6, 12, 18, 24)


@dataclass
class StorageEstimate:
    retention_hours: float
    bytes: int

    @property
    def mb(self) -> float:
        return self.bytes / 1e6


@dataclass
class StorageStats:
    file_bytes: int = 0              # tamaño real del archivo en disco
    page_size: int = 0
    page_count: int = 0
    opp_rows: int = 0
    exec_rows: int = 0
    span_seconds: float = 0.0        # rango temporal cubierto por las opportunities
    rows_per_second: float = 0.0     # tasa media de inserción observada
    bytes_per_row: float = 0.0       # bytes/fila reales (incluye índices/overhead)
    retention_hours: float = 0.0     # política activa
    disk_free_bytes: int = 0
    estimates: list[StorageEstimate] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "file_bytes": self.file_bytes,
            "file_mb": round(self.file_bytes / 1e6, 1),
            "file_gb": round(self.file_bytes / 1e9, 3),
            "page_size": self.page_size,
            "page_count": self.page_count,
            "opp_rows": self.opp_rows,
            "exec_rows": self.exec_rows,
            "span_seconds": round(self.span_seconds, 1),
            "span_days": round(self.span_seconds / 86_400.0, 2),
            "rows_per_second": round(self.rows_per_second, 2),
            "rows_per_hour": round(self.rows_per_second * 3600.0),
            "bytes_per_row": round(self.bytes_per_row, 1),
            "mb_per_hour": round(self.rows_per_second * 3600.0 * self.bytes_per_row / 1e6, 2),
            "mb_per_day": round(self.rows_per_second * 86_400.0 * self.bytes_per_row / 1e6, 1),
            "retention_hours": self.retention_hours,
            "disk_free_bytes": self.disk_free_bytes,
            "disk_free_gb": round(self.disk_free_bytes / 1e9, 1),
            "estimates": [
                {"retention_hours": e.retention_hours, "bytes": e.bytes, "mb": round(e.mb, 1)}
                for e in self.estimates
            ],
        }


def _sqlite_path(db_url: str) -> str | None:
    """Extrae la ruta del archivo de un db_url SQLite. None si es :memory: u otro motor."""
    if "sqlite" not in db_url or ":memory:" in db_url:
        return None
    # sqlite+aiosqlite:///./arbitraje.db  ->  ./arbitraje.db   (descarta query params)
    _, _, tail = db_url.partition(":///")
    path = tail.split("?", 1)[0]
    return path or None


def _disk_usage(path: str | None) -> tuple[int, int]:
    """(tamaño_archivo, espacio_libre) en bytes. Síncrono a propósito: son stat() rápidos,
    aislados aquí para no disparar ASYNC240 dentro de la corrutina de medición."""
    if path is None or not os.path.exists(path):
        return 0, 0
    file_bytes = os.path.getsize(path)
    try:
        usage = os.statvfs(os.path.dirname(os.path.abspath(path)) or ".")
        free = usage.f_bavail * usage.f_frsize
    except (OSError, AttributeError):
        free = 0
    return file_bytes, free


async def measure_storage(engine: AsyncEngine, db_url: str, retention_hours: float) -> StorageStats:
    """Mide el estado de almacenamiento y proyecta la estimación por retención.

    `count(*)` es O(filas): barato tras la poda (tabla pequeña), pero crece con el tamaño si la
    retención está desactivada. El span se obtiene por PK (primera/última fila), que sí es O(1).
    """
    stats = StorageStats(retention_hours=retention_hours)
    stats.file_bytes, stats.disk_free_bytes = _disk_usage(_sqlite_path(db_url))

    async with engine.connect() as conn:
        stats.page_size = int((await conn.execute(text("PRAGMA page_size"))).scalar() or 0)
        stats.page_count = int((await conn.execute(text("PRAGMA page_count"))).scalar() or 0)
        free_pages = int((await conn.execute(text("PRAGMA freelist_count"))).scalar() or 0)
        if not stats.file_bytes:
            stats.file_bytes = stats.page_size * stats.page_count
        # Bytes "vivos": excluye páginas libres no recuperadas tras DELETE sin VACUUM, para no
        # inflar bytes/fila (y la estimación) cuando el archivo quedó hinchado.
        live_bytes = max(0, stats.page_count - free_pages) * stats.page_size
        opp_c = (await conn.execute(text("SELECT count(*) FROM opportunities"))).scalar()
        exec_c = (await conn.execute(text("SELECT count(*) FROM executions"))).scalar()
        stats.opp_rows = int(opp_c or 0)
        stats.exec_rows = int(exec_c or 0)
        if stats.opp_rows > 0:
            q_first = "SELECT created_at FROM opportunities ORDER BY row_id ASC LIMIT 1"
            q_last = "SELECT created_at FROM opportunities ORDER BY row_id DESC LIMIT 1"
            first = (await conn.execute(text(q_first))).scalar()
            last = (await conn.execute(text(q_last))).scalar()
            if first is not None and last is not None and last > first:
                stats.span_seconds = float(last) - float(first)
                stats.rows_per_second = stats.opp_rows / stats.span_seconds

    total_rows = stats.opp_rows + stats.exec_rows
    if total_rows > 0 and live_bytes > 0:
        stats.bytes_per_row = live_bytes / total_rows

    # Proyección en estado estacionario: filas/s × ventana × bytes/fila.
    if stats.rows_per_second > 0 and stats.bytes_per_row > 0:
        for h in RETENTION_CHOICES_H:
            est_bytes = int(stats.rows_per_second * 3600.0 * h * stats.bytes_per_row)
            stats.estimates.append(StorageEstimate(retention_hours=float(h), bytes=est_bytes))
    return stats


async def prune_old_rows(
    engine: AsyncEngine,
    retention_hours: float,
    *,
    now: float | None = None,
    vacuum: bool = False,
) -> dict[str, int]:
    """Borra opportunities/executions con `created_at` < (now - retention). No-op si <= 0.

    Devuelve `{"opportunities": n, "executions": m}`. Best-effort: una excepción se loggea y
    se devuelve lo contado hasta el fallo (la task de fondo no debe tumbar el proceso).
    """
    if retention_hours <= 0:
        return {"opportunities": 0, "executions": 0}
    cutoff = (now if now is not None else time.time()) - retention_hours * 3600.0
    deleted = {"opportunities": 0, "executions": 0}
    try:
        async with engine.begin() as conn:
            for table in ("opportunities", "executions"):
                res = await conn.execute(
                    text(f"DELETE FROM {table} WHERE created_at < :cutoff"),
                    {"cutoff": cutoff},
                )
                deleted[table] = res.rowcount or 0
        if vacuum and (deleted["opportunities"] or deleted["executions"]):
            # VACUUM recupera espacio en disco; fuera de transacción y costoso → opt-in.
            async with engine.connect() as conn:
                await conn.execute(text("VACUUM"))
        if deleted["opportunities"] or deleted["executions"]:
            log.info(
                "poda: -%d opportunities, -%d executions (retención %.1fh)",
                deleted["opportunities"], deleted["executions"], retention_hours,
            )
    except Exception:
        log.exception("Error en prune_old_rows (continuando)")
    return deleted
