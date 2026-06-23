"""Adapter Binance Spot Testnet determinista.

Este primer adapter no toca red: valida reglas locales de símbolo, sanea el payload y emite
una respuesta de test order determinista. El archivo queda aislado para reemplazar el tramo
offline por `POST /api/v3/order/test` de Binance Spot Testnet sin cambiar router/UI.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from ..config import Settings
from ..models.preflight import (
    PreflightCheck,
    PreflightRequest,
    PreflightResult,
    TestOrderRequest,
    TestOrderResult,
)

_ZERO = Decimal("0")


@dataclass(frozen=True)
class SymbolFilters:
    min_qty: Decimal
    step_size: Decimal
    min_notional: Decimal
    tick_size: Decimal


_BTCUSDT = SymbolFilters(
    min_qty=Decimal("0.00001000"),
    step_size=Decimal("0.00001000"),
    min_notional=Decimal("5.00"),
    tick_size=Decimal("0.01000000"),
)


def _symbol(s: str) -> str:
    return s.replace("/", "").replace("-", "").replace("_", "").upper()


def _dec(v: float | str | Decimal) -> Decimal:
    return Decimal(str(v))


def _floor_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= _ZERO:
        return value
    units = (value / step).to_integral_value(rounding=ROUND_DOWN)
    return units * step


def _places(step: Decimal) -> int:
    exponent = step.normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def _fmt(value: Decimal, step: Decimal) -> str:
    return f"{value:.{_places(step)}f}"


class BinanceTestnetAdapter:
    venue = "binance"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def preflight(self, req: PreflightRequest) -> PreflightResult:
        symbol = _symbol(req.symbol)
        if symbol != "BTCUSDT":
            return PreflightResult(
                mode=self.settings.execution_mode,
                accepted=False,
                venue=self.venue,
                symbol=symbol,
                checks=[
                    PreflightCheck(
                        name="symbol_supported",
                        passed=False,
                        detail="adapter inicial soporta BTCUSDT",
                    )
                ],
                sanitized_order={},
            )

        filters = _BTCUSDT
        raw_qty = _dec(req.quantity_btc)
        qty = _floor_step(raw_qty, filters.step_size)
        checks = self._base_checks(req, qty, raw_qty, filters)
        price = self._price_reference(req, filters)
        if price is None:
            checks.append(
                PreflightCheck(
                    name="price_reference",
                    passed=False,
                    detail="market order requiere reference_price o book vigente",
                )
            )
            notional: Decimal | None = None
        else:
            checks.append(PreflightCheck(name="price_reference", passed=True))
            notional = qty * price
        checks.append(self._min_notional_check(notional, filters))
        checks.append(self._balance_check(req, qty, notional))
        accepted = all(c.passed for c in checks)
        return PreflightResult(
            mode=self.settings.execution_mode,
            accepted=accepted,
            venue=self.venue,
            symbol=symbol,
            checks=checks,
            sanitized_order=self._sanitized_order(req, symbol, qty, price, filters),
        )

    async def test_order(self, req: TestOrderRequest) -> TestOrderResult:
        preflight = await self.preflight(req)
        status = "accepted_test" if preflight.accepted else "rejected_test"
        response = {
            "test_order": preflight.accepted,
            "adapter": "local_binance_testnet",
            "network": "offline",
        }
        if preflight.accepted:
            response["client_order_id"] = self._client_order_id(preflight.sanitized_order)
        return TestOrderResult(
            mode=self.settings.execution_mode,
            accepted=preflight.accepted,
            venue=self.venue,
            symbol=preflight.symbol,
            status=status,
            checks=preflight.checks,
            submitted_order=preflight.sanitized_order,
            exchange_response=response,
        )

    def _base_checks(
        self,
        req: PreflightRequest,
        qty: Decimal,
        raw_qty: Decimal,
        filters: SymbolFilters,
    ) -> list[PreflightCheck]:
        checks = [
            PreflightCheck(
                name="credentials",
                passed=(
                    self.settings.execution_mode != "testnet"
                    or (
                        bool(self.settings.binance_testnet_api_key)
                        and bool(self.settings.binance_testnet_api_secret)
                    )
                ),
                detail=(
                    "not required in dry_run"
                    if self.settings.execution_mode == "dry_run"
                    else "configured"
                    if (
                        self.settings.binance_testnet_api_key
                        and self.settings.binance_testnet_api_secret
                    )
                    else "missing testnet credentials"
                ),
            ),
            PreflightCheck(name="venue_supported", passed=True, detail=self.venue),
            PreflightCheck(name="symbol_supported", passed=True, detail="BTCUSDT"),
        ]
        min_qty_ok = qty >= filters.min_qty
        min_qty_detail = (
            f"qty={_fmt(qty, filters.step_size)} "
            f"min={_fmt(filters.min_qty, filters.step_size)}"
        )
        checks.append(
            PreflightCheck(
                name="min_qty",
                passed=min_qty_ok,
                detail=min_qty_detail,
            )
        )
        checks.append(
            PreflightCheck(
                name="lot_size",
                passed=min_qty_ok and qty > _ZERO,
                detail=(
                    "aligned"
                    if raw_qty == qty
                    else f"sanitized_down_to={_fmt(qty, filters.step_size)}"
                ),
            )
        )
        if req.order_type == "limit":
            checks.append(
                PreflightCheck(
                    name="limit_price",
                    passed=req.limit_price is not None,
                    detail="required for LIMIT",
                )
            )
        else:
            checks.append(PreflightCheck(name="order_type", passed=True, detail="MARKET"))
        return checks

    def _price_reference(
        self, req: PreflightRequest, filters: SymbolFilters
    ) -> Decimal | None:
        source = req.limit_price if req.order_type == "limit" else (
            req.reference_price if req.reference_price is not None else req.limit_price
        )
        if source is None:
            return None
        price = _floor_step(_dec(source), filters.tick_size)
        return price if price > _ZERO else None

    @staticmethod
    def _min_notional_check(
        notional: Decimal | None, filters: SymbolFilters
    ) -> PreflightCheck:
        if notional is None:
            return PreflightCheck(name="min_notional", passed=False, detail="notional unknown")
        return PreflightCheck(
            name="min_notional",
            passed=notional >= filters.min_notional,
            detail=f"notional={notional:.2f} min={filters.min_notional:.2f}",
        )

    def _balance_check(
        self, req: PreflightRequest, qty: Decimal, notional: Decimal | None
    ) -> PreflightCheck:
        if req.side == "buy":
            available = _dec(self.settings.execution_local_quote_balance_usd)
            passed = notional is not None and notional <= available
            detail = (
                "notional unknown"
                if notional is None
                else f"required_usd={notional:.2f} available_usd={available:.2f}"
            )
        else:
            available = _dec(self.settings.execution_local_btc_balance)
            passed = qty <= available
            detail = f"required_btc={qty} available_btc={available}"
        return PreflightCheck(name="balance", passed=passed, detail=detail)

    @staticmethod
    def _sanitized_order(
        req: PreflightRequest,
        symbol: str,
        qty: Decimal,
        price: Decimal | None,
        filters: SymbolFilters,
    ) -> dict[str, str]:
        order = {
            "symbol": symbol,
            "side": req.side.upper(),
            "type": req.order_type.upper(),
            "quantity": _fmt(qty, filters.step_size),
        }
        if req.order_type == "limit":
            order["timeInForce"] = "GTC"
            if price is not None:
                order["price"] = _fmt(price, filters.tick_size)
        return order

    @staticmethod
    def _client_order_id(order: dict[str, str]) -> str:
        packed = json.dumps(order, sort_keys=True, separators=(",", ":"))
        return "test_" + hashlib.sha256(packed.encode("utf-8")).hexdigest()[:20]
