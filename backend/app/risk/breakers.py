"""C8 (parte breakers) — Circuit breakers + kill switch (STORY-018, FR-012).

Seguridad operativa: el bot deja de operar cuando el riesgo se dispara. Cinco breakers
(``BreakerType``), dos familias por su semántica:

  · AUTO (no enganchan): se recomputan en CADA tick del monitor y reflejan la condición
    AHORA. Se limpian solos cuando la condición cede:
      - ``volatility``     — el RANGO del mid en la ventana ``volatility_window_ms`` supera
                             ``volatility_breaker_bps`` en algún venue (mercado convulso).
      - ``inventory_skew`` — el desbalance de BTC entre venues supera el límite (reusa
                             ``Portfolio.inventory_skew()`` — MISMA definición que el
                             rebalanceo periódico, sin criterio paralelo).
      - ``stale_data``     — NINGÚN venue habilitado está ``live`` (sin datos operables; la
                             EXCLUSIÓN per-venue la sigue haciendo el detector C5/watchdog,
                             este breaker es el corte global "no hay mercado que mirar").

  · ENGANCHADOS (latching, requieren ``resume()`` manual): una vez disparados HALTAN hasta
    que el operador reanuda — comportamiento clásico de circuit breaker, y la demo más
    contundente para el jurado:
      - ``max_drawdown`` — la caída desde el PICO de equity supera ``max_drawdown_usd``.
      - ``kill_switch``  — corte manual del operador (``POST /control/kill-switch``).

``tripped`` (cualquiera activo) es el predicado que el motor (C5/C6, en ``on_opp``) consulta
ANTES de simular: con un breaker activo la oportunidad viable se descarta
(``breaker_active``) y NO se ejecuta. El simulador (C9) se mantiene puro; el punto de
consulta es el motor (Apéndice F: "Breakers/Watchdog activos ▶ discarded(breaker_active)").

Determinista: ``evaluate`` recibe las MEDIDAS ya calculadas (equity, skew, vol, feeds) y el
``now`` monotónico; no abre red ni lee reloj. La cadencia y la recolección de medidas viven
en ``BreakerMonitor`` (espejo del watchdog/rebalancer).
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..config import Settings
from ..engine.bookmath import mid_lenient
from ..models.enums import BreakerType, ConnectionStatus
from ..models.risk import CircuitBreakerState

if TYPE_CHECKING:
    from ..models.market import NormalizedBook
    from ..sim.inventory import Portfolio
    from ..state import AppState

logger = logging.getLogger("app.risk.breakers")

# BTC por debajo de este umbral se considera plano (un venue sin BTC no necesita mark).
_DUST = 1e-12


class VolatilityTracker:
    """Rango de mid por venue dentro de una ventana deslizante, en basis points.

    Mantiene ``(now, mid)`` por venue y descarta lo anterior a ``now − window``. El proxy
    de volatilidad es el RANGO relativo ``(max − min) / min`` (robusto y barato): captura un
    spike rápido sin asumir distribución ni signo. Ignora mids no finitos o <= 0 (snapshot
    corrupto). Necesita >= 2 puntos en la ventana para medir; si no, no opina (``None``)."""

    def __init__(self, window_ms: float) -> None:
        self._window = window_ms / 1000.0
        self._hist: dict[str, deque[tuple[float, float]]] = defaultdict(deque)

    def update(self, venue: str, mid: float, now: float) -> None:
        if not (math.isfinite(mid) and mid > 0.0):
            return
        h = self._hist[venue]
        h.append((now, mid))
        cutoff = now - self._window
        while h and h[0][0] < cutoff:
            h.popleft()

    def max_bps(self, now: float) -> float | None:
        """Máximo rango (bps) entre venues, sólo con datos DENTRO de la ventana en ``now``.
        Purga primero lo viejo para no medir contra un mid rancio de hace minutos."""
        best: float | None = None
        cutoff = now - self._window
        empties: list[str] = []
        for venue, h in self._hist.items():
            while h and h[0][0] < cutoff:
                h.popleft()
            if not h:
                empties.append(venue)  # venue sin datos en la ventana: no lo arrastres
                continue
            if len(h) < 2:
                continue
            mids = [m for _, m in h]
            lo, hi = min(mids), max(mids)
            if lo > 0.0:
                bps = (hi - lo) / lo * 10_000.0
                best = bps if best is None else max(best, bps)
        for v in empties:  # poda claves muertas (evita iterar venues fantasma cada tick)
            del self._hist[v]
        return best


class BreakerManager:
    """Estado de los breakers (C8). Sin red ni reloj: ``evaluate`` recibe las medidas.

    Es el dato vivo que consulta el motor (``tripped``) y que exponen ``/health`` y
    ``/control/status``. ``trip_kill_switch``/``resume`` son las acciones del operador."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Un CircuitBreakerState por tipo, en orden estable del enum.
        self._states: dict[BreakerType, CircuitBreakerState] = {
            bt: CircuitBreakerState(type=bt) for bt in BreakerType
        }
        self._equity_peak: float | None = None
        self._drawdown_latched = False
        self._kill = False

    # --- acciones del operador (kill switch / resume) ---
    def trip_kill_switch(self, *, now: float | None = None) -> None:
        """Activa el kill switch manual (engancha hasta ``resume``)."""
        self._kill = True
        self._set(BreakerType.kill_switch, True, "kill switch manual", now)

    def resume(self, *, now: float | None = None, equity: float | None = None) -> None:
        """Reanuda: limpia el kill switch Y el enganche de drawdown, y RE-ANCLA el pico de
        equity al valor actual para no re-disparar drawdown de inmediato por la caída ya
        absorbida. Los breakers AUTO (vol/skew/stale) no se tocan: se recomputan solos (si la
        condición persiste, ``tripped`` seguirá True — reanudar no enmascara un riesgo vivo)."""
        self._kill = False
        self._drawdown_latched = False
        if equity is not None and math.isfinite(equity):
            self._equity_peak = equity
        self._set(BreakerType.kill_switch, False, None, now)
        self._set(BreakerType.max_drawdown, False, None, now)

    # --- consulta ---
    @property
    def tripped(self) -> bool:
        """True si CUALQUIER breaker está activo: el motor no debe operar."""
        return any(s.active for s in self._states.values())

    def states(self) -> list[CircuitBreakerState]:
        """Estados en orden estable del enum (copias inmutables para la API)."""
        return [self._states[bt].model_copy() for bt in BreakerType]

    def active_types(self) -> list[str]:
        return [bt.value for bt in BreakerType if self._states[bt].active]

    def status(self) -> dict[str, Any]:
        """Forma para ``/health``, ``/control/status`` y el evento SSE ``breaker``."""
        return {
            "halted": self.tripped,
            "active": self.active_types(),
            "breakers": [s.model_dump(mode="json") for s in self.states()],
        }

    # --- transición de un breaker (set/clear) preservando `since` ---
    def _set(
        self, bt: BreakerType, active: bool, reason: str | None, now: float | None
    ) -> None:
        st = self._states[bt]
        if active and not st.active:
            st.active = True
            st.reason = reason
            st.since = now if now is not None else time.monotonic()
        elif active:
            st.reason = reason  # sigue activo: refresca el motivo, conserva `since`
        elif st.active:
            st.active = False
            st.reason = None
            st.since = None

    def evaluate(
        self,
        *,
        now: float,
        equity: float | None,
        skew_breached: bool,
        live_venues: int,
        enabled_venues: int,
        volatility_bps: float | None,
    ) -> None:
        """Recomputa los 5 breakers a partir de las MEDIDAS (pura respecto a su entrada).

        kill_switch y el enganche de drawdown ya viven en ``self`` (los fija el operador /
        el propio cómputo de drawdown); el resto son función directa de las medidas del tick.
        """
        # kill switch (engancha; lo limpia resume()).
        self._set(BreakerType.kill_switch, self._kill, "kill switch manual", now)

        # stale_data (auto): ningún venue habilitado está live → sin mercado operable.
        all_stale = enabled_venues > 0 and live_venues == 0
        self._set(BreakerType.stale_data, all_stale, "sin feeds vivos", now)

        # volatility (auto): rango del mid en la ventana supera el umbral en algún venue.
        vol_breached = (
            volatility_bps is not None
            and math.isfinite(volatility_bps)
            and volatility_bps > self.settings.volatility_breaker_bps
        )
        vol_reason = (
            f"volatilidad {volatility_bps:.0f}bps > {self.settings.volatility_breaker_bps:.0f}bps"
            if vol_breached
            else None
        )
        self._set(BreakerType.volatility, vol_breached, vol_reason, now)

        # inventory_skew (auto): reusa el predicado del Portfolio (misma def. que rebalanceo).
        self._set(
            BreakerType.inventory_skew, skew_breached, "skew de inventario sobre el límite", now
        )

        # max_drawdown (engancha): caída desde el pico de equity supera el límite.
        if equity is not None and math.isfinite(equity):
            if self._equity_peak is None or equity > self._equity_peak:
                self._equity_peak = equity
            drawdown = self._equity_peak - equity
            if drawdown > self.settings.max_drawdown_usd:
                self._drawdown_latched = True
        dd_reason = (
            f"drawdown > ${self.settings.max_drawdown_usd:.0f}"
            if self._drawdown_latched
            else None
        )
        self._set(BreakerType.max_drawdown, self._drawdown_latched, dd_reason, now)


class BreakerMonitor:
    """Tarea de fondo que recolecta medidas y recomputa los breakers (C8).

    Espejo del watchdog/rebalancer: cadencia ``breaker_interval_ms``. Cada tick lee el estado
    vivo (libros normalizados, portfolio, feed_status del watchdog), alimenta el tracker de
    volatilidad, llama a ``BreakerManager.evaluate`` y, si el conjunto de breakers activos
    CAMBIÓ, loguea y dispara ``on_change`` (SSE). Un fallo en un tick no mata la tarea."""

    def __init__(
        self,
        state: AppState,
        settings: Settings,
        *,
        on_change: Callable[[BreakerManager], None] | None = None,
    ) -> None:
        self._state = state
        self._settings = settings
        self._stop = asyncio.Event()
        self._on_change = on_change
        self._vol = VolatilityTracker(window_ms=settings.volatility_window_ms)

    def _equity_complete(self, pf: Portfolio, books: dict[str, NormalizedBook]) -> bool:
        """True si TODO venue que mantiene BTC tiene un mark vivo (mid válido). Evita medir
        drawdown sobre una equity artificialmente baja por un libro ausente (mark→0). Un venue
        sin BTC (|btc|<=dust) no aporta valor marcable → no exige libro."""
        for venue, vb in pf.venues.items():
            if abs(vb.btc) <= _DUST:
                continue
            nb = books.get(venue)
            if nb is None or self._mid(nb) is None:
                return False
        return True

    @staticmethod
    def _mid(nb: NormalizedBook) -> float | None:
        return mid_lenient(nb)

    def measure(self, now: float) -> dict[str, Any]:
        """Recolecta las medidas del tick (pura respecto al estado leído). Separada de ``run``
        para poder testearla sin tarea de fondo."""
        books = self._state.latest_norm
        for venue, nb in books.items():
            mid = self._mid(nb)
            if mid is not None:
                self._vol.update(venue, mid, now)
        pf = self._state.portfolio
        equity: float | None = None
        skew_breached = False
        if pf is not None:
            skew_breached = bool(pf.inventory_skew()["breached"])
            # Sólo medimos drawdown con equity COMPLETA. Si un venue con BTC no tiene libro
            # vivo, `equity_total` lo marca a 0 (conservador para el dashboard) → la equity se
            # desploma ~miles USD por DATO FALTANTE, no por pérdida real. Como el breaker de
            # drawdown ENGANCHA, ese glitch transitorio latcharía un HALT permanente (mismo
            # carácter del P&L fantasma de STORY-010). Con equity incompleta pasamos None: no
            # actualiza el pico ni evalúa drawdown hasta que todos los venues con BTC sean
            # marcables; el corte por feed caído ya lo cubre `stale_data` (auto) + el detector.
            if self._equity_complete(pf, books):
                equity = pf.equity_total(books)
        live = sum(
            1 for s in self._state.feed_status.values() if s is ConnectionStatus.live
        )
        return {
            "now": now,
            "equity": equity,
            "skew_breached": skew_breached,
            "live_venues": live,
            "enabled_venues": len(self._settings.enabled_exchanges),
            "volatility_bps": self._vol.max_bps(now),
        }

    async def run(self) -> None:
        interval = self._settings.breaker_interval_ms / 1000.0
        prev_active: list[str] = []
        while not self._stop.is_set():
            await asyncio.sleep(interval)
            # Un fallo en un tick (estado inesperado) NO debe matar la tarea: se loguea y se
            # sigue. `CancelledError` se re-lanza para respetar la cancelación del shutdown.
            try:
                # Se relee cada tick (barato): refleja un reemplazo de `state.breakers` en
                # runtime y cubre el arranque cuando aún es None.
                mgr = self._state.breakers
                if mgr is None:
                    continue
                now = time.monotonic()
                mgr.evaluate(**self.measure(now))
                active = mgr.active_types()
                if active != prev_active:
                    logger.warning("breakers: %s -> %s", prev_active, active)
                    if self._on_change is not None:
                        self._on_change(mgr)
                    prev_active = active
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("breaker tick falló; la tarea continúa")

    def stop(self) -> None:
        self._stop.set()
