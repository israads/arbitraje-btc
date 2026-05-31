"""C13 — Métricas. FR-017, NFR-001/010.

Latencia p50/p99 por etapa (monotónica, en ventana); embudo
detectadas→viables→ejecutables→capturadas con motivo; microestructura (effective/realized
spread, price impact, capture/fill ratio, opportunity lifetime). STORY-022.
"""
from __future__ import annotations

from .collector import MetricsCollector

__all__ = ["MetricsCollector"]
