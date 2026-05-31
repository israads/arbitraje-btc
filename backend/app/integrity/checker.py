"""C2 — Integridad de order book por exchange (STORY-015, FR-020).

ccxt.pro ya mantiene el libro internamente (aplica el `U/u`/nonce de Binance, el
CRC32 de Kraken si se activa, y `sequence_num` + heartbeats de Coinbase). Esta capa
añade una validación ESTRUCTURAL y de secuencia ANTES de aceptar cada RawOrderBook,
para nunca alimentar al motor con un libro corrupto:

  - lado no vacío (hay bids y asks),
  - precios y cantidades estrictamente positivos,
  - niveles ordenados (bids desc, asks asc),
  - libro no cruzado (mejor bid no supera al mejor ask; `==` locked se tolera),
  - secuencia (`seq`/nonce) monótona no decreciente por venue (descarta updates
    fuera de orden / duplicados viejos).

Un libro inválido se DESCARTA (no actualiza el estado vivo) y se contabiliza por
venue para exponerlo en `/health`. Es complementario al watchdog (C8): integridad =
correctitud estructural; watchdog = frescura temporal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models.market import RawOrderBook


@dataclass
class IntegrityReport:
    """Estadísticas de integridad acumuladas para un venue."""

    accepted: int = 0
    rejected: int = 0
    last_reason: str | None = None
    last_seq: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "rejected": self.rejected,
            "last_reason": self.last_reason,
        }


def integrity_reason(raw: RawOrderBook, last_seq: int | None) -> str | None:
    """Motivo de rechazo del libro, o None si es íntegro. Pura, testeable."""
    bids, asks = raw.bids, raw.asks
    if not bids or not asks:
        return "empty_side"
    for side in (bids, asks):
        for px, qty in side:
            if px <= 0 or qty <= 0:
                return "nonpositive"
    if any(bids[i][0] < bids[i + 1][0] for i in range(len(bids) - 1)):
        return "bids_unsorted"
    if any(asks[i][0] > asks[i + 1][0] for i in range(len(asks) - 1)):
        return "asks_unsorted"
    if bids[0][0] > asks[0][0]:
        return "crossed_book"
    if last_seq is not None and raw.seq is not None and raw.seq < last_seq:
        return "seq_regression"
    return None


class BookIntegrityChecker:
    """Valida RawOrderBook por venue; mantiene la última secuencia y estadísticas."""

    def __init__(self) -> None:
        self._reports: dict[str, IntegrityReport] = {}

    def check(self, raw: RawOrderBook) -> bool:
        """True si el libro es íntegro (y debe aceptarse); False si se descarta."""
        rep = self._reports.setdefault(raw.exchange, IntegrityReport())
        reason = integrity_reason(raw, rep.last_seq)
        if reason is not None:
            rep.rejected += 1
            rep.last_reason = reason
            return False
        rep.accepted += 1
        if raw.seq is not None:
            rep.last_seq = raw.seq
        return True

    def reports(self) -> dict[str, dict[str, Any]]:
        return {ex: r.to_dict() for ex, r in self._reports.items()}
