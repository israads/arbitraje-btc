"""C4 — la cola acotada descarta el dato más viejo cuando se llena (drop-oldest)."""
from __future__ import annotations

from app.bus.queue import BoundedQueue


async def test_drop_oldest():
    q: BoundedQueue[int] = BoundedQueue(maxsize=2)
    q.put_nowait(1)
    q.put_nowait(2)
    q.put_nowait(3)  # llena → descarta el 1
    assert q.dropped == 1
    assert q.qsize() == 2
    assert await q.get() == 2
    assert await q.get() == 3
