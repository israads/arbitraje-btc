"""Curvas acumuladas de profundidad para consultas VWAP repetidas.

`walk_book` sigue siendo la primitiva simple y conceptual. `DepthCurve` precomputa cantidades
y nocional acumulado para consultar muchos tamaños contra el mismo libro en O(log n), útil en
proyecciones y curvas de capacidad.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from typing import Literal

from ..models.market import PriceLevel

DepthSide = Literal["bid", "ask"]


@dataclass(frozen=True)
class DepthCurve:
    side: DepthSide
    prices: tuple[float, ...]
    qty_cum: tuple[float, ...]
    notional_cum: tuple[float, ...]

    @classmethod
    def from_levels(cls, levels: list[PriceLevel], side: DepthSide) -> DepthCurve:
        prices: list[float] = []
        qty_cum: list[float] = []
        notional_cum: list[float] = []
        acc_qty = 0.0
        acc_notional = 0.0
        for price, qty in levels:
            if qty <= 0.0 or not math.isfinite(qty) or not math.isfinite(price):
                continue
            acc_qty += qty
            acc_notional += price * qty
            prices.append(price)
            qty_cum.append(acc_qty)
            notional_cum.append(acc_notional)
        return cls(
            side=side,
            prices=tuple(prices),
            qty_cum=tuple(qty_cum),
            notional_cum=tuple(notional_cum),
        )

    @property
    def depth(self) -> float:
        return self.qty_cum[-1] if self.qty_cum else 0.0

    @property
    def best_price(self) -> float | None:
        return self.prices[0] if self.prices else None

    def vwap(self, q: float) -> tuple[float, float]:
        """Devuelve `(vwap, filled)` con la misma semántica de `walk_book`.

        Si `q` supera la profundidad disponible, se llena todo el libro válido. Si no hay
        niveles válidos o `q <= 0`, devuelve `(0.0, 0.0)`.
        """
        if q <= 0.0 or not self.qty_cum:
            return 0.0, 0.0

        idx = bisect_left(self.qty_cum, q)
        if idx >= len(self.qty_cum):
            filled = self.qty_cum[-1]
            notional = self.notional_cum[-1]
            return (notional / filled if filled > 0.0 else 0.0), filled

        prev_qty = self.qty_cum[idx - 1] if idx > 0 else 0.0
        prev_notional = self.notional_cum[idx - 1] if idx > 0 else 0.0
        take = q - prev_qty
        filled = q
        notional = prev_notional + take * self.prices[idx]
        return (notional / filled if filled > 0.0 else 0.0), filled
