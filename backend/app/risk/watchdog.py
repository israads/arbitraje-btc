"""C8 (parte staleness) — Watchdog de datos stale (STORY-014, FR-002).

Marca cada venue como `live`/`stale` comparando la antigüedad del último book
(`now_monotonic − ts_recv_monotonic`) contra `staleness_ms`, y lo publica en
`AppState.feed_status` para el dashboard (`/health`) y futuros breakers
(STORY-018). La EXCLUSIÓN de venues stale de la detección la hace el detector
(C5) de forma race-free con el MISMO predicado `is_stale` y el mismo umbral, sin
depender del intervalo del watchdog. El peg tiene su propia frescura en el
evaluador (C6).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from ..config import Settings
from ..models.enums import ConnectionStatus

if TYPE_CHECKING:
    from ..state import AppState

logger = logging.getLogger("app.risk.watchdog")


def is_stale(ts_recv_monotonic: float, now: float, staleness_ms: float) -> bool:
    """True si el book lleva MÁS de `staleness_ms` sin actualizarse (frontera estricta)."""
    return (now - ts_recv_monotonic) * 1000.0 > staleness_ms


class Watchdog:
    """Tarea de fondo que mantiene `AppState.feed_status` por venue (C8)."""

    def __init__(self, state: AppState, settings: Settings) -> None:
        self._state = state
        self._settings = settings
        self._stop = asyncio.Event()

    def evaluate(self, now: float) -> dict[str, ConnectionStatus]:
        """Estado de cada venue habilitado en `now` (monotónico). Pura, testeable.

        Un venue sin book aún (nunca recibido) cuenta como `stale` (no disponible).
        """
        staleness_ms = self._settings.staleness_ms
        books = self._state.latest_norm
        out: dict[str, ConnectionStatus] = {}
        for e in self._settings.enabled_exchanges:
            book = books.get(e.id)
            if book is None or is_stale(book.ts_recv_monotonic, now, staleness_ms):
                out[e.id] = ConnectionStatus.stale
            else:
                out[e.id] = ConnectionStatus.live
        return out

    async def run(self) -> None:
        interval = self._settings.watchdog_interval_ms / 1000.0
        prev: dict[str, ConnectionStatus] = {}
        while not self._stop.is_set():
            await asyncio.sleep(interval)
            status = self.evaluate(time.monotonic())
            self._state.feed_status = status
            for ex, st in status.items():
                before = prev.get(ex)
                if before is not None and before != st:
                    logger.warning("feed %s: %s -> %s", ex, before.value, st.value)
                prev[ex] = st

    def stop(self) -> None:
        self._stop.set()
