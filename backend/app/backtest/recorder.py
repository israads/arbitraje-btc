"""C14 — Grabador de ticks para replay (FR-014 AC#1, STORY-021).

Graba los `NormalizedBook` (top-N, YA normalizados a USD por peg) a medida que llegan en el
camino caliente (`on_book` del lifespan), con su `ts_recv_monotonic` de recepción. Es un ring
buffer acotado (`record_maxlen`): O(1) por tick, sin I/O en el camino caliente (igual filosofía
que el `BatchWriter` C12). El replay (C14) los reproduce cronológicamente por el MISMO motor.

Se graba el book NORMALIZADO (no el crudo) para que el replay alimente directamente el motor
(`SpatialDetector.on_book` consume `NormalizedBook`) reproduciendo EXACTAMENTE lo observado,
con el peg vivo ya aplicado (point-in-time fiel; sin re-normalizar con un peg posterior).

Persistencia opcional en archivo (JSONL) para backup/reproducibilidad de la demo (Apéndice:
"recordings opcional en archivos") y para el fallback a replay (C16, STORY-024).
"""
from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable, Iterator

from pydantic import ValidationError

from ..models.market import NormalizedBook


class Recorder:
    """Ring buffer de `NormalizedBook` para record & replay. No abre red ni reloj: el `ts`
    viaja en cada book (`ts_recv_monotonic`)."""

    def __init__(self, *, maxlen: int = 20_000, enabled: bool = True) -> None:
        self.enabled = enabled
        self._buf: deque[NormalizedBook] = deque(maxlen=maxlen)

    def record(self, nb: NormalizedBook) -> None:
        """Graba un book normalizado (no-op si está deshabilitado). Llamado en el camino
        caliente: O(1), sin copias ni serialización (el `NormalizedBook` es inmutable de
        hecho — el normalizador crea uno nuevo por tick)."""
        if self.enabled:
            self._buf.append(nb)

    def ticks(self) -> list[NormalizedBook]:
        """Snapshot inmutable de los ticks grabados, en orden de llegada (cronológico:
        `ts_recv_monotonic` es monotónico en el proceso). El replay lo re-ordena por ts de
        forma defensiva."""
        return list(self._buf)

    def __len__(self) -> int:
        return len(self._buf)

    @property
    def maxlen(self) -> int | None:
        return self._buf.maxlen

    def clear(self) -> None:
        self._buf.clear()

    # --- Persistencia opcional en archivo (JSONL) ---

    def to_jsonl(self, path: str) -> int:
        """Vuelca los ticks a un archivo JSONL (un book por línea). Devuelve cuántos escribió."""
        n = 0
        with open(path, "w", encoding="utf-8") as fh:
            for nb in self._buf:
                fh.write(json.dumps(nb.model_dump(mode="json")) + "\n")
                n += 1
        return n

    @classmethod
    def from_jsonl(cls, path: str, *, maxlen: int = 20_000) -> Recorder:
        """Carga un recording desde JSONL a un `Recorder` nuevo (para replay/fallback C16).

        Tolerante a líneas corruptas: una línea malformada (JSON inválido o book que no valida)
        se SALTA en vez de abortar la carga — un recording parcialmente dañado sigue siendo
        útil para la demo (mejor degradar que no arrancar el fallback)."""
        rec = cls(maxlen=maxlen, enabled=True)
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec._buf.append(NormalizedBook.model_validate(json.loads(line)))
                except (json.JSONDecodeError, ValidationError, TypeError):
                    continue  # línea corrupta: se ignora
        return rec

    @staticmethod
    def chronological(ticks: Iterable[NormalizedBook]) -> list[NormalizedBook]:
        """Ordena los ticks por `ts_recv_monotonic` ascendente (estable). El buffer ya llega
        en orden, pero el replay lo garantiza por si se carga de archivo o se concatena."""
        return sorted(ticks, key=lambda nb: nb.ts_recv_monotonic)

    def __iter__(self) -> Iterator[NormalizedBook]:
        return iter(self._buf)
