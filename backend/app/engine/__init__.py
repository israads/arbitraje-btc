"""Motor de trading: detección (C5) + evaluador de neto (C6) + priorización (C7).

- C5 detección espacial (`Ask_A<Bid_B` norm.) + z-score. FR-004, FR-006.
- C6 neto: walk-the-book VWAP, fee único por tier, rebalanceo amortizado. FR-005.
- C7 ranking por score. FR-007.

Implementación: STORY-004 (espacial), STORY-008 (neto), STORY-019 (z), STORY-020 (rank).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from ..bus import BoundedQueue
from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity
from .detector import SpatialDetector
from .evaluator import NetEvaluator
from .prioritizer import Prioritizer
from .statz import StatZDetector

__all__ = ["NetEvaluator", "Prioritizer", "SpatialDetector", "StatZDetector", "run_engine"]

logger = logging.getLogger("app.engine")

# Cada cuántas opps emitidas se cede el event loop dentro de un tick: un burst de cruces
# (mercado convulso) no debe congelar ingesta/SSE durante todo el lote.
_YIELD_EVERY_OPPS = 64


async def run_engine(
    queue: BoundedQueue[NormalizedBook],
    detector: SpatialDetector,
    on_opp: Callable[[Opportunity], None],
    evaluator: NetEvaluator | None = None,
    stat_detector: StatZDetector | None = None,
    prioritizer: Prioritizer | None = None,
) -> None:
    """Consume books normalizados de la cola C4: detección (C5) → neto (C6) → emisión.

    El detector sólo detecta cruces; el evaluador decide viabilidad NETA recorriendo
    los libros por venue que mantiene el propio detector (`detector.books`), ANTES de
    `on_opp`. Determinista: sin red ni reloj para el cómputo económico.

    STORY-019: si se pasa `stat_detector` (C5 estadístico, FR-006), por cada book se
    corre TAMBIÉN la estrategia z-score sobre los mismos libros vivos del detector
    espacial; sus señales `stat_z` pasan por el MISMO evaluador de neto y `on_opp`
    (validación neta del cruce ejecutable, AC#4). Sin `stat_detector` → comportamiento
    byte-idéntico al anterior (retrocompatible / cero-regresión).

    STORY-020: si se pasa `prioritizer` (C7, FR-007), tras evaluar TODAS las opps del tick
    se rankean por score ajustado a riesgo y `on_opp` se invoca en orden descendente, de
    modo que el gate de capital/inventario (en `on_opp`) atienda primero las de mayor score.
    Sin `prioritizer` → orden de detección (byte-idéntico al anterior)."""
    if evaluator is None:
        evaluator = NetEvaluator(detector.settings)
    while True:
        nb = await queue.get()
        # Supervisión (C8/NFR): una excepción no prevista en el procesamiento de UN book no
        # puede matar la task del motor en silencio (la detección se detendría el resto de la
        # sesión). Se loggea y se continúa con el siguiente tick. `CancelledError` es
        # BaseException y NO la captura este bloque: la cancelación de shutdown sigue limpia.
        try:
            # El detector espacial almacena `nb` en `detector.books` ANTES de que el detector
            # estadístico lea los mids de la contraparte, por lo que ve el libro más reciente.
            opps = detector.on_book(nb)
            if stat_detector is not None:
                opps = [*opps, *stat_detector.on_book(nb, detector.books)]
            # Evalúa el neto de TODAS antes de priorizar (C7 necesita net_pnl/slippage/q de C6).
            for opp in opps:
                buy_book = detector.books.get(opp.buy_venue)
                sell_book = detector.books.get(opp.sell_venue)
                # El detector sólo emite cruces con ambos books presentes; el guard evita
                # romper si la API cambia.
                if buy_book is not None and sell_book is not None:
                    evaluator.evaluate(opp, buy_book, sell_book)
            # C7 (STORY-020): rankea por score desc (las viables primero); asigna `opp.score`.
            if prioritizer is not None:
                opps = prioritizer.rank(opps)
            for i, opp in enumerate(opps, start=1):
                on_opp(opp)
                if i % _YIELD_EVERY_OPPS == 0:
                    await asyncio.sleep(0)
        except Exception:
            logger.exception("error procesando book de %s; el motor continúa", nb.exchange)
