"""C4 — Bus interno: colas asyncio acotadas con backpressure drop-oldest."""
from __future__ import annotations

from .queue import BoundedQueue

__all__ = ["BoundedQueue"]
