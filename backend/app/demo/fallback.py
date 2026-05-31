"""C16 — Controlador de fallback a replay para la demo (FR-018, STORY-024).

Problema: en una demo en vivo los feeds reales pueden caer (corte de red, geo-restricción,
exchange en mantenimiento) y el dashboard se quedaría plano justo delante del jurado. Este
controlador detecta la caída y, sin intervención, **reproduce los ticks grabados** (C14
Recorder) por el MISMO pipeline (detección C5 → neto C6 → simulación C9 → métricas C13 →
SSE C11), con un badge "DEMO DATA", hasta que el feed real se recupera.

Diseño — el corte limpio del ciclo de realimentación:

- La liveness REAL se rastrea SOLO vía `mark_live()`, que invoca el `on_book` del camino
  vivo (ingesta real). El replay NO la toca. Así el controlador distingue "hay datos reales"
  de "hay datos en `latest_norm`" (que el replay también puebla).
- Al inyectar un tick grabado se RE-SELLA su `ts_recv_monotonic` a `now`: el watchdog (C8),
  el detector (C5) y los breakers lo ven FRESCO → la detección/ejecución fluyen igual que en
  vivo (no se auto-bloquean por staleness). El badge `DEMO DATA` (no `feed_status`) es la
  fuente de verdad de que el origen es replay — honesto sin romper el motor.

Modos: `auto` (cambia solo según la liveness real), `on` (fuerza replay — útil para que el
jurado vea el fallback sin matar feeds), `off` (nunca replay). Tarea de fondo espejo del
watchdog/breaker monitor: un fallo en un tick se loguea y la tarea continúa.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from ..backtest import Recorder
from ..config import Settings
from ..models.market import NormalizedBook

if TYPE_CHECKING:
    from ..state import AppState

logger = logging.getLogger("app.demo.fallback")

Mode = Literal["auto", "on", "off"]


class DemoFallback:
    """Controlador del fallback a replay (C16). Una instancia viva por proceso."""

    def __init__(
        self,
        state: AppState,
        settings: Settings,
        *,
        inject: Callable[[NormalizedBook], None],
        on_change: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._state = state
        self._settings = settings
        self._inject = inject  # feed_normalized(nb, record=False, mark_live=False)
        self._on_change = on_change
        self._stop = asyncio.Event()
        self.active = False
        self._mode: Mode = "auto"
        self._last_live: float | None = None
        self._replay: list[NormalizedBook] = []
        self._idx = 0
        self.since: float | None = None
        # Recording de respaldo: se carga UNA sola vez aquí (en el arranque, fuera del hot loop
        # del controlador) — leer el JSONL en `tick()` congelaría el event loop justo con los
        # feeds caídos, y se repetiría a 20 Hz si el archivo está vacío/corrupto (revisión HIGH).
        self._file_ticks: list[NormalizedBook] = self._load_backup_file()

    # ---- liveness real (sólo la mueve el camino vivo) ----

    def mark_live(self, now: float | None = None) -> None:
        """Sella la última llegada de datos REALES (ingesta viva). NUNCA la llama el replay."""
        self._last_live = now if now is not None else time.monotonic()

    def _real_alive(self, now: float) -> bool:
        if self._last_live is None:
            return False  # nunca llegó dato real → no hay feed vivo
        return (now - self._last_live) * 1000.0 <= self._settings.demo_stale_ms

    # ---- control de modo (operador / demo) ----

    def set_mode(self, mode: Mode) -> None:
        self._mode = mode

    def _want_active(self, now: float) -> bool:
        if self._mode == "on":
            return True
        if self._mode == "off":
            return False
        return not self._real_alive(now)  # auto: sin feed real vivo → replay

    # ---- fuente de replay ----

    def _load_backup_file(self) -> list[NormalizedBook]:
        """Carga (una vez, en construcción) el recording de respaldo en archivo, si lo hay.
        Tolerante: archivo ausente/sin permiso (OSError) o binario/no-UTF8 (UnicodeDecodeError,
        que NO es OSError) → lista vacía sin abortar el arranque."""
        path = self._settings.demo_recording_path
        if not path:
            return []
        try:
            return Recorder.from_jsonl(path, maxlen=self._settings.record_maxlen).ticks()
        except (OSError, UnicodeDecodeError, ValueError):
            logger.warning("demo: no se pudo leer el recording de respaldo %s", path)
            return []

    def _load_replay(self) -> None:
        """Instantánea de los ticks a reproducir: primero el buffer del Recorder VIVO (lo grabado
        mientras hubo feed, barato en memoria); si está vacío (arranque en frío con feeds muertos)
        usa el recording de respaldo YA cargado en construcción. Ordenado cronológicamente."""
        rec = self._state.recorder
        ticks = rec.ticks() if rec is not None else []
        if not ticks:
            ticks = self._file_ticks
        self._replay = Recorder.chronological(ticks)
        self._idx = 0

    # ---- estado expuesto (badge) ----

    def status(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "mode": self._mode,
            "source": "replay" if self.active else "live",
            "badge": "DEMO DATA" if self.active else None,
            "since": self.since,
            "n_replay_ticks": len(self._replay),
        }

    def _activate(self, now: float) -> None:
        self.active = True
        self.since = now
        logger.warning("DEMO fallback ACTIVO: replay de %d ticks grabados", len(self._replay))
        if self._on_change is not None:
            self._on_change(self.status())

    def _deactivate(self, now: float) -> None:
        self.active = False
        self.since = None
        self._replay = []
        self._idx = 0
        logger.warning("DEMO fallback DESACTIVADO: feed real recuperado")
        if self._on_change is not None:
            self._on_change(self.status())

    def _emit_next(self, now: float) -> None:
        """Inyecta el siguiente tick grabado, re-sellado fresco, cíclicamente (la demo no se
        agota: al terminar el buffer reinicia)."""
        nb = self._replay[self._idx]
        self._idx = (self._idx + 1) % len(self._replay)  # cicla acotado (no crece sin fin)
        fresh = nb.model_copy(update={"ts_recv_monotonic": now})
        self._inject(fresh)

    # ---- tarea de fondo ----

    def tick(self, now: float) -> None:
        """Un paso del controlador (pura respecto al reloj que recibe). Separada de `run` para
        testear sin tarea de fondo."""
        want = self._want_active(now)
        if want and not self.active:
            self._load_replay()
            if self._replay:  # sin datos que reproducir no se activa (honesto: badge off)
                self._activate(now)
        elif not want and self.active:
            self._deactivate(now)
        if self.active and self._replay:
            self._emit_next(now)

    async def run(self) -> None:
        interval = self._settings.demo_replay_interval_ms / 1000.0
        while not self._stop.is_set():
            await asyncio.sleep(interval)
            try:
                self.tick(time.monotonic())
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("demo tick falló; la tarea continúa")

    def stop(self) -> None:
        self._stop.set()
