"""C3 — Proveedor de peg de stablecoins (FR-003).

Mantiene el tipo de cambio VIVO stable→USD (p.ej. USDT/USD ≈ 0.9997, nunca 1.00).
La detección/neto usan `within_tolerance` para descartar comparaciones cuando una
stable se desvía de su peg más allá de lo configurado (`peg_adverse`).
"""
from __future__ import annotations

from typing import Any

from ..models.market import PegRate


class PegProvider:
    def __init__(self, target: str = "USD", tolerance: float = 0.005) -> None:
        self.target = target
        self.tolerance = tolerance
        self._rates: dict[str, PegRate] = {}

    def update(self, stable: str, usd_rate: float, *, source: str, ts: float) -> None:
        self._rates[stable] = PegRate(stable=stable, usd_rate=usd_rate, ts=ts, source=source)

    def factor_for(self, quote_ccy: str) -> float | None:
        """Factor multiplicativo precio→USD. `None` si no hay peg vivo todavía
        (nunca se asume 1.00 para una stable distinta del target)."""
        if quote_ccy == self.target:
            return 1.0
        rate = self._rates.get(quote_ccy)
        return rate.usd_rate if rate else None

    def within_tolerance(self, quote_ccy: str) -> bool:
        if quote_ccy == self.target:
            return True
        rate = self._rates.get(quote_ccy)
        if rate is None:
            return False
        return abs(rate.usd_rate - 1.0) <= self.tolerance

    def snapshot(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {self.target: {"usd_rate": 1.0, "within_tolerance": True}}
        for stable, rate in self._rates.items():
            out[stable] = {
                "usd_rate": rate.usd_rate,
                "within_tolerance": abs(rate.usd_rate - 1.0) <= self.tolerance,
            }
        return out
