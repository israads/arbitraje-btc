"""Guards y estado público para ejecución protegida/testnet."""
from __future__ import annotations

from ..config import Settings
from ..models.preflight import ExecutionStatus
from .registry import SUPPORTED_EXECUTION_VENUES


class ExecutionDisabled(RuntimeError):
    """La capa de ejecución está apagada por configuración."""


class TestOrdersDisabled(RuntimeError):
    """El endpoint de test order no tiene todos los flags duros activos."""


def ensure_execution_enabled(settings: Settings) -> None:
    if settings.execution_mode == "disabled":
        raise ExecutionDisabled("execution_mode=disabled")


def ensure_test_orders_enabled(settings: Settings) -> None:
    ensure_execution_enabled(settings)
    if settings.execution_mode != "testnet" or not settings.enable_test_orders:
        raise TestOrdersDisabled(
            "test-order requiere ARB_EXECUTION_MODE=testnet y "
            "ARB_ENABLE_TEST_ORDERS=true"
        )


def build_execution_status(settings: Settings) -> ExecutionStatus:
    notes: list[str] = []
    if settings.execution_mode == "disabled":
        notes.append("execution disabled by default")
    if settings.execution_mode == "dry_run":
        notes.append("dry_run validates local exchange rules only")
    if settings.execution_mode == "testnet" and not settings.enable_test_orders:
        notes.append("test orders blocked until enable_test_orders=true")
    return ExecutionStatus(
        mode=settings.execution_mode,
        enabled=settings.execution_mode != "disabled",
        test_orders_enabled=(
            settings.execution_mode == "testnet" and settings.enable_test_orders
        ),
        supported_venues=list(SUPPORTED_EXECUTION_VENUES),
        credentials_configured={
            "binance_api_key": bool(settings.binance_testnet_api_key),
            "binance_api_secret": bool(settings.binance_testnet_api_secret),
        },
        notes=notes,
    )
