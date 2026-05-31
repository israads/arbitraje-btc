"""C11 — Hub SSE. Una tarea "pump" del pipeline publica eventos; cada cliente SSE
tiene su cola acotada (drop-oldest) → un cliente lento nunca frena el motor.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from ..models.events import StreamEvent

log = logging.getLogger("app.stream.hub")


class StreamHub:
    def __init__(self, client_queue_maxsize: int = 500) -> None:
        self._clients: set[asyncio.Queue[StreamEvent]] = set()
        self._maxsize = client_queue_maxsize

    def publish(self, event: StreamEvent) -> None:
        """No bloqueante. Drop-oldest por cliente para no acumular lag."""
        for q in list(self._clients):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    async def subscribe(self) -> AsyncIterator[StreamEvent]:
        """Generador para el endpoint SSE. Registra la cola al iniciar y la limpia
        al desconectarse el cliente."""
        q: asyncio.Queue[StreamEvent] = asyncio.Queue(self._maxsize)
        self._clients.add(q)
        log.info("sse client connected (total=%d)", len(self._clients))
        try:
            while True:
                yield await q.get()
        finally:
            self._clients.discard(q)
            log.info("sse client disconnected (total=%d)", len(self._clients))

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def aclose(self) -> None:
        self._clients.clear()
