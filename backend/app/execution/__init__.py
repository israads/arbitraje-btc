"""Capa de ejecución protegida/testnet (PRD-003)."""
from __future__ import annotations

from .preflight import (
    ExecutionDisabled,
    TestOrdersDisabled,
    build_execution_status,
    ensure_execution_enabled,
    ensure_test_orders_enabled,
)
from .registry import UnsupportedExecutionVenue, get_execution_adapter

__all__ = [
    "ExecutionDisabled",
    "TestOrdersDisabled",
    "UnsupportedExecutionVenue",
    "build_execution_status",
    "ensure_execution_enabled",
    "ensure_test_orders_enabled",
    "get_execution_adapter",
]
