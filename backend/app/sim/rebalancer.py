"""C10 (parte rebalanceo) — Tarea periódica de rebalanceo de inventario (STORY-017, FR-011).

Dispara `Portfolio.rebalance()` cada `rebalance_interval_ms` con los libros vivos del
detector. La DECISIÓN y el cómputo (detectar skew sobre el límite, mover BTC, cargar el
coste on-chain real al P&L) viven en `Portfolio.rebalance` —pura y determinista—; esta clase
sólo aporta la cadencia PERIÓDICA (NO por trade, AC de STORY-017), igual que el watchdog
(C8) aporta la cadencia del chequeo de staleness. Sin libros (o sin portfolio/detector) no
hace nada: autostart-safe.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from ..config import Settings

if TYPE_CHECKING:
    from ..state import AppState

logger = logging.getLogger("app.sim.rebalancer")


class Rebalancer:
    """Tarea de fondo que rebalancea el inventario periódicamente (C10)."""

    def __init__(self, state: AppState, settings: Settings) -> None:
        self._state = state
        self._settings = settings
        self._stop = asyncio.Event()

    async def run(self) -> None:
        interval = self._settings.rebalance_interval_ms / 1000.0
        while not self._stop.is_set():
            await asyncio.sleep(interval)
            # Un fallo en un tick (libro inesperado, regresión aritmética) NO debe matar la
            # tarea de fondo en silencio: se loguea y se sigue. `CancelledError` se re-lanza
            # para respetar la cancelación del shutdown (no se traga).
            try:
                pf = self._state.portfolio
                detector = self._state.detector
                if pf is None or detector is None:
                    continue
                # Libros normalizados vivos (USD por peg) que mantiene el detector — la MISMA
                # fuente que usa el wiring para marcar la equity (main.py record_equity_point).
                # Epoch real (UTC): el reloj se lee aquí (capa impura); `Portfolio.rebalance`
                # sigue puro y determinista recibiendo el ts por parámetro. NO monotonic:
                # no representa una fecha (PRD-012 RF-001).
                event = pf.rebalance(detector.books, ts=time.time())
                if event is not None:
                    logger.warning(
                        "rebalance: skew %.3f -> %.3f, cost $%.2f (fee %.6f BTC)",
                        event["skew_before"],
                        event["skew_after"],
                        event["cost_usd"],
                        event["fee_btc"],
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("rebalance tick falló; la tarea continúa")

    def stop(self) -> None:
        self._stop.set()
