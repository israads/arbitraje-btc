"""Compat — `build_edge_frontier` vive ahora en `app.projection.frontier` (Projection Suite v2).

Se mantiene este re-export para no romper imports/tests existentes; la implementación real
(modos demo/live, P_survive, Expected Capturable Edge, 3 óptimos) está en el paquete `projection`.
"""
from __future__ import annotations

from app.projection.frontier import build_edge_frontier

__all__ = ["build_edge_frontier"]
