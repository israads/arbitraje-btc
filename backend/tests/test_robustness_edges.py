"""Robustez en el borde (auditoría fase final): supervisión de tasks y cache LRU.

- El motor y el watchdog NO mueren en silencio ante una excepción imprevista (C2):
  loggean y siguen procesando el siguiente tick.
- `_PROJECTION_CACHE` está acotado (LRU): variar query params no crece memoria sin límite.
"""
from __future__ import annotations

import asyncio
import time

from app.api.v1.router import (
    _PROJECTION_CACHE,
    _PROJECTION_CACHE_MAX,
    _cache_get,
    _cache_put,
)
from app.bus import BoundedQueue
from app.config import Settings
from app.engine import SpatialDetector, run_engine
from app.models.market import NormalizedBook
from app.risk.watchdog import Watchdog


def _nb(ex: str, bid: float, ask: float, ts: float) -> NormalizedBook:
    return NormalizedBook(
        exchange=ex, symbol="BTC/USD", quote_ccy="USD",
        bids=[(bid, 1.0)], asks=[(ask, 1.0)], price_norm_factor=1.0, ts_recv_monotonic=ts,
    )


class _ExplodingDetector:
    """Detector que revienta en el primer book y delega después (simula bug imprevisto)."""

    def __init__(self, settings: Settings) -> None:
        self._inner = SpatialDetector(settings)
        self.settings = settings
        self.calls = 0

    @property
    def books(self) -> dict[str, NormalizedBook]:
        return self._inner.books

    def on_book(self, nb: NormalizedBook) -> list:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("boom")
        return self._inner.on_book(nb)


async def test_run_engine_survives_detector_exception():
    """Una excepción procesando UN book no mata la task del motor: el siguiente tick
    se procesa con normalidad (antes: muerte silenciosa y detección parada de por vida)."""
    settings = Settings(ingest_autostart=False)
    queue: BoundedQueue[NormalizedBook] = BoundedQueue(10)
    detector = _ExplodingDetector(settings)
    t = time.monotonic()

    task = asyncio.create_task(run_engine(queue, detector, lambda _o: None))  # type: ignore[arg-type]
    queue.put_nowait(_nb("binance", 100, 101, t))   # → RuntimeError (debe sobrevivir)
    queue.put_nowait(_nb("kraken", 99, 100.5, t))   # → procesado normal
    for _ in range(200):
        if detector.calls >= 2:
            break
        await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert detector.calls == 2, "el segundo book debe procesarse: la task no murió"


async def test_watchdog_survives_exception(monkeypatch):
    """El watchdog loggea y continúa: `feed_status` no queda congelado por un bug puntual."""
    settings = Settings(ingest_autostart=False, watchdog_interval_ms=1)

    class _State:
        latest_norm: dict[str, NormalizedBook] = {}
        feed_status: dict = {}

    wd = Watchdog(_State(), settings)  # type: ignore[arg-type]
    calls = {"n": 0}
    original = wd.evaluate

    def exploding_evaluate(now: float):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return original(now)

    monkeypatch.setattr(wd, "evaluate", exploding_evaluate)
    task = asyncio.create_task(wd.run())
    for _ in range(500):
        if calls["n"] >= 2:
            break
        await asyncio.sleep(0.002)
    wd.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert calls["n"] >= 2, "siguió evaluando tras la excepción"


def test_projection_cache_is_bounded_lru():
    _PROJECTION_CACHE.clear()
    now = 1000.0
    for i in range(_PROJECTION_CACHE_MAX * 3):
        _cache_put(f"forward:{i}", object(), now)
    assert len(_PROJECTION_CACHE) == _PROJECTION_CACHE_MAX
    # LRU: la clave más reciente sobrevive; la más vieja fue desalojada.
    last = f"forward:{_PROJECTION_CACHE_MAX * 3 - 1}"
    assert _cache_get(last, now) is not None
    assert _cache_get("forward:0", now) is None
    # Al escribir también se purgan las expiradas por TTL.
    _cache_put("fresh", object(), now + 10_000.0)
    assert len(_PROJECTION_CACHE) == 1
    _PROJECTION_CACHE.clear()
