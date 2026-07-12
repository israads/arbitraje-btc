"""C11 — Publicador hacia el hub SSE. Convierte la salida del pipeline en eventos.

`quote`: book normalizado a USD (throttled por venue para no inundar al cliente).
`opportunity`: oportunidad detectada/evaluada (se enriquece con neto en STORY-008).
Es no bloqueante: el hub encola con drop-oldest por cliente.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ..models.events import StreamEvent
from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity
from .hub import StreamHub


class StreamPublisher:
    def __init__(
        self, hub: StreamHub, quote_throttle_ms: int = 100, metrics_throttle_ms: int = 1000,
        pnl_throttle_ms: int = 500,
    ) -> None:
        self._hub = hub
        self._throttle = quote_throttle_ms / 1000.0
        self._metrics_throttle = metrics_throttle_ms / 1000.0
        self._pnl_throttle = pnl_throttle_ms / 1000.0
        self._last_quote: dict[str, float] = {}
        self._last_metrics = 0.0
        self._last_pnl = 0.0

    def publish_quote(self, nb: NormalizedBook) -> None:
        if self._hub.client_count == 0:
            return  # sin suscriptores SSE: no construir el dict en la ruta caliente
        now = time.monotonic()
        if now - self._last_quote.get(nb.exchange, 0.0) < self._throttle:
            return
        self._last_quote[nb.exchange] = now
        self._hub.publish(
            StreamEvent(
                type="quote",
                data={
                    "exchange": nb.exchange,
                    "symbol": nb.symbol,
                    "quote_ccy": nb.quote_ccy,
                    "usd_bid": nb.best_bid,
                    "usd_ask": nb.best_ask,
                    "price_norm_factor": nb.price_norm_factor,
                    "ts_exchange": nb.ts_exchange,
                },
            )
        )

    def publish_opportunity(self, opp: Opportunity) -> None:
        if self._hub.client_count == 0:
            return  # sin suscriptores SSE: evita model_dump por opp en la ruta caliente
        self._hub.publish(StreamEvent(type="opportunity", data=opp.model_dump(mode="json")))

    def publish_metrics(self, build: Callable[[], dict[str, Any]]) -> bool:
        """Empuja el snapshot de métricas (C13, STORY-022) por SSE, THROTTLED para no
        inundar al cliente. `build` se invoca SÓLO si pasa el throttle (construir/serializar
        el snapshot en cada opp sería caro). Devuelve True si emitió, False si lo saltó."""
        now = time.monotonic()
        if now - self._last_metrics < self._metrics_throttle:
            return False
        self._last_metrics = now
        data = build()
        # Permite al cliente rechazar un snapshot viejo que haya quedado en tránsito mientras
        # GET /demo ya devolvió un scenario_run_id nuevo (carrera entre transportes).
        data["asof_monotonic"] = now
        self._hub.publish(StreamEvent(type="metrics", data=data))
        return True

    def publish_pnl(self, build: Callable[[], dict[str, Any]]) -> bool:
        """Empuja el resumen de P&L (C10) por SSE en tiempo real tras cada ejecución aplicada,
        THROTTLED (≈2/s) para no recomputar el mark-to-market en cada trade. Reemplaza el
        polling de `/pnl` del cliente: la equity curve y el P&L dejan de tener lag de poll.
        `build` se invoca SÓLO si pasa el throttle. Devuelve True si emitió."""
        now = time.monotonic()
        if now - self._last_pnl < self._pnl_throttle:
            return False
        self._last_pnl = now
        self._hub.publish(StreamEvent(type="pnl", data=build()))
        return True

    def publish_demo(self, status: dict[str, Any]) -> None:
        """Estado del fallback de demo (C16, STORY-024). Se emite al CAMBIAR (activar/desactivar
        replay), para que el dashboard muestre/oculte el badge "DEMO DATA" al instante."""
        self._hub.publish(StreamEvent(type="demo", data=status))

    def publish_breaker(self, status: dict[str, Any]) -> None:
        """Estado de los circuit breakers (C8, STORY-018). Se emite sólo al CAMBIAR el
        conjunto de breakers activos (lo decide el BreakerMonitor), no en cada tick."""
        self._hub.publish(StreamEvent(type="breaker", data=status))
