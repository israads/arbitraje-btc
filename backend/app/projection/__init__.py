"""Projection Suite v2 — capturabilidad (frontier) · capacidad · forward.

Construida ENCIMA del motor (no toca C1-C18 ni la ruta caliente). Toda la economía pasa por
`engine.cost_model` (fuente única). Determinista y autostart-safe en modo demo; alimentada por
los `NormalizedBook` reales en modo live.
"""
from __future__ import annotations

from .capacity import build_capacity_curve
from .forward import build_forward_projection
from .frontier import build_frontier
from .survival import expected_capturable_edge, p_survive

__all__ = [
    "build_frontier",
    "build_capacity_curve",
    "build_forward_projection",
    "p_survive",
    "expected_capturable_edge",
]
