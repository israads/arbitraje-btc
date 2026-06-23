"""Interfaces internas de adapters de ejecución."""
from __future__ import annotations

from typing import Protocol

from ..models.preflight import PreflightRequest, PreflightResult, TestOrderRequest, TestOrderResult


class ExecutionAdapter(Protocol):
    venue: str

    async def preflight(self, req: PreflightRequest) -> PreflightResult:
        ...

    async def test_order(self, req: TestOrderRequest) -> TestOrderResult:
        ...
