"""C15 — Modelos de resultado del arnés de validación (FR-021, NFR-004).

Resultados ESTRUCTURADOS (pydantic) para que tanto los tests como el endpoint
`/api/v1/validation` (y el HERO Edge Waterfall del dashboard, STORY-023) consuman la
misma forma: pasa/falla + detalle + el número computado vs la referencia del reto.

Determinista: estos modelos no leen red ni reloj; sólo transportan resultados ya
computados por `harness.py` / `invariants.py`.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ReconciliationResult(BaseModel):
    """Resultado de reconciliar el ejemplo del reto ($109.75/BTC).

    `target` es la referencia oficial del reto; `computed` el neto/BTC que produce
    NUESTRO cálculo (vía `NetEvaluator`); `diff = computed - target`; `passed` cuando
    `abs(diff) <= tolerance`. `breakdown` desglosa gross/fees/rebalanceo para el waterfall.
    """

    target: float = 109.75            # referencia oficial del reto (PRD FR-021)
    computed: float                   # neto/BTC que produce nuestro cálculo
    diff: float                       # computed - target (firmado)
    tolerance: float                  # tolerancia documentada para `passed`
    passed: bool                      # abs(diff) <= tolerance
    qty_btc: float = 1.0              # cantidad del escenario (el reto: 1 BTC)
    # Desglose económico del neto (gross → -fees → -rebalanceo = net) por trade, para
    # el HERO Edge Waterfall (STORY-023). Todo en USD para la `qty_btc` del escenario.
    breakdown: dict[str, float] = Field(default_factory=dict)
    # Notas/suposiciones del escenario (precios, fees, fórmula) — honestidad ante el jurado.
    notes: str = ""


class InvariantResult(BaseModel):
    """Resultado de UNA invariante: pasa/falla + detalle legible.

    `name` identifica la invariante; `passed` el veredicto; `detail` explica el porqué
    (incluye los números relevantes); `metrics` lleva valores numéricos auxiliares para
    trazabilidad/visualización."""

    name: str
    passed: bool
    detail: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    """Reporte completo del arnés: reconciliación + lista de invariantes.

    Forma estable consumida por `GET /api/v1/validation`. `all_passed` es el AND de la
    reconciliación y TODAS las invariantes — la "prueba de correctitud" del dashboard."""

    reconciliation: ReconciliationResult
    invariants: list[InvariantResult] = Field(default_factory=list)
    all_passed: bool = False
