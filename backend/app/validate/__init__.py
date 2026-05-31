"""C15 — Arnés de validación. FR-021, NFR-004.

Reconciliación contra el ejemplo del reto ($109.75/BTC) + invariantes reutilizables
(conservación de valor, fee única por leg, slippage >= 0, identidad del neto, q <=
profundidad, no cross book, no-arbitraje degenerado, monotonía de fees) y el ensamblado
del `ValidationReport` que consume `GET /api/v1/validation` y el HERO Edge Waterfall
(STORY-023).

Determinista: sin red ni reloj. Implementación: STORY-012.
"""
from __future__ import annotations

from .harness import (
    RECONCILE_TOLERANCE_USD,
    TARGET_NET_USD,
    build_challenge_opportunity,
    build_challenge_settings,
    reconcile_challenge,
)
from .invariants import (
    check_fee_monotonicity,
    check_net_identity,
    check_no_cross_book,
    check_no_degenerate_arbitrage,
    check_qty_within_depth,
    check_single_fee_per_leg,
    check_slippage_nonnegative,
    check_value_conservation,
)
from .report import build_validation_report
from .results import InvariantResult, ReconciliationResult, ValidationReport

__all__ = [
    # Reconciliación
    "TARGET_NET_USD",
    "RECONCILE_TOLERANCE_USD",
    "reconcile_challenge",
    "build_challenge_settings",
    "build_challenge_opportunity",
    # Invariantes
    "check_net_identity",
    "check_single_fee_per_leg",
    "check_slippage_nonnegative",
    "check_qty_within_depth",
    "check_no_cross_book",
    "check_value_conservation",
    "check_no_degenerate_arbitrage",
    "check_fee_monotonicity",
    # Reporte / modelos
    "build_validation_report",
    "ReconciliationResult",
    "InvariantResult",
    "ValidationReport",
]
