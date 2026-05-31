"""C4 — Cola acotada con política drop-oldest.

En trading interesa el dato fresco: si la cola está llena se descarta el tick más
viejo antes de encolar el nuevo. Desacopla la ingesta (ráfagas) del procesamiento.
"""
from __future__ import annotations

import asyncio
from typing import Generic, TypeVar

T = TypeVar("T")


class BoundedQueue(Generic[T]):
    def __init__(self, maxsize: int) -> None:
        self._q: asyncio.Queue[T] = asyncio.Queue(maxsize)
        self.dropped = 0

    def put_nowait(self, item: T) -> None:
        if self._q.full():
            try:
                self._q.get_nowait()
                self.dropped += 1
            except asyncio.QueueEmpty:
                pass
        self._q.put_nowait(item)

    async def get(self) -> T:
        return await self._q.get()

    def qsize(self) -> int:
        return self._q.qsize()

    @property
    def maxsize(self) -> int:
        return self._q.maxsize
