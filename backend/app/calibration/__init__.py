"""Calibración observe-only de supervivencia del edge (PRD-005)."""
from __future__ import annotations

from .samples import build_shadow_sample
from .survival import build_survival_report, evaluate_survival

__all__ = ["build_shadow_sample", "build_survival_report", "evaluate_survival"]
