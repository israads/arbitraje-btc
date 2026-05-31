"""Protocolo `Runner` — contrato común de las tareas de feed duck-typed (C1/C3).

`ExchangeIngestor` (C1) y `PegIngestor` (C3) no comparten jerarquía pero sí la misma
interfaz: una corrutina `run()` (loop de ingesta con backoff) y `close()` (cierre del
cliente). El lifespan los trata uniformemente (`run_ingestors`, bucle de `close`). Tipar
ese uso con un `Protocol` estructural elimina los `list[object]`/`attr-defined` de mypy
sin acoplar las clases ni añadir herencia (STORY-030).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Runner(Protocol):
    """Tarea de fondo con ciclo de vida run/close (ingestor de exchange o de peg)."""

    async def run(self) -> None: ...

    async def close(self) -> None: ...
