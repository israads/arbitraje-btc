"""Módulos de estrategia (PRD-008)."""
from __future__ import annotations

from .base import StrategyModule
from .funding import FundingBasisStrategy
from .regional_mxn import RegionalMXNStrategy
from .spatial import SpatialStrategyAdapter
from .stat_z import StatZStrategyAdapter
from .triangular import TriangularStrategy

__all__ = [
    "FundingBasisStrategy",
    "RegionalMXNStrategy",
    "SpatialStrategyAdapter",
    "StatZStrategyAdapter",
    "StrategyModule",
    "TriangularStrategy",
]
