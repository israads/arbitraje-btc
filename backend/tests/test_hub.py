"""C11 — el hub hace fan-out de eventos a los clientes suscritos."""
from __future__ import annotations

import asyncio

from app.models.events import StreamEvent
from app.stream.hub import StreamHub


async def test_publish_reaches_subscriber():
    hub = StreamHub(client_queue_maxsize=10)
    gen = hub.subscribe()
    task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)  # deja que la suscripción registre su cola
    assert hub.client_count == 1

    hub.publish(StreamEvent(type="quote", data={"px": 70000}))
    ev = await asyncio.wait_for(task, timeout=1.0)
    assert ev.type == "quote"
    assert ev.data["px"] == 70000

    await gen.aclose()
    assert hub.client_count == 0
