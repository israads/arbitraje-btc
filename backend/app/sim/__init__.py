"""Simulador (C9) + inventario/balances (C10). FR-008/009/010/011.

Walking-the-book con fills parciales; latencia entre patas + leg risk/unwind;
balances pre-posicionados con invariante de conservación; P&L; rebalanceo amortizado.

Implementación: STORY-009 (fills), STORY-010 (inventario+P&L), STORY-016 (leg risk),
STORY-017 (rebalanceo).
"""
from __future__ import annotations

from .inventory import Portfolio, VenueBalance
from .rebalancer import Rebalancer
from .simulator import ExecutionSimulator

__all__ = ["ExecutionSimulator", "Portfolio", "Rebalancer", "VenueBalance"]
