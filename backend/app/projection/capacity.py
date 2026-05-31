"""Capacity Curve (curva de capacidad de la oportunidad de arbitraje).

Barre tamaños crecientes de orden ``Q`` (BTC) y, para cada uno, valora el neto
del cross con :func:`app.engine.cost_model.compute_net`. El resultado es una
curva **cóncava** de ``edge_total_usd`` frente a ``Q``:

* Para ``Q`` pequeño el edge crece casi linealmente: cada BTC extra captura el
  spread top-of-book menos fees, y el coste fijo de rebalanceo se amortiza.
* A medida que ``Q`` consume niveles más profundos del libro, el VWAP de compra
  sube y el de venta baja (slippage); el edge marginal por BTC decrece y la
  curva se **satura**.
* Pasado el óptimo ``Q*`` el edge marginal se vuelve negativo (cada BTC extra
  destruye más valor del que aporta) y el edge total **cae**, llegando
  eventualmente a cruzar cero: ese cruce es la *hard capacity*, el tamaño a
  partir del cual la operación deja de ser rentable.

``Q*`` (``q_star_btc``) es el tamaño que MAXIMIZA ``edge_total_usd``, es decir el
punto donde el edge marginal cruza 0. El edge capturable en ese punto
(``q_star_edge_usd``) es el throughput por oportunidad.

Determinista: sin red, sin reloj, sin estado global mutable.
"""
from __future__ import annotations

import math

from app.config import Settings, get_settings
from app.engine.cost_model import compute_net
from app.models.market import NormalizedBook
from app.models.projection import CapacityPoint, CapacityResult
from app.projection.frontier import (
    _BUY_ASKS,
    _SELL_BIDS,
    _WD_BTC_DEMO,
    _best_route,
)

__all__ = ["build_capacity_curve"]

# --- Constantes del overlay square-root (square-root law / market impact) ----
# Modelo ilustrativo de impacto de mercado: I(Q) = Y · σ · sqrt(Q / V) · Q,
# valorado en USD multiplicando por el precio de referencia.
# Referencia empírica: Donier & Bonart (2015) reportan para BTC un exponente de
# impacto δ ≈ 0.5 (de ahí la raíz cuadrada) y un prefactor Y ≈ 0.9. Es SOLO un
# overlay de validación teórica de la curva: NO entra en la aritmética del neto.
_SQRT_Y = 0.9  # prefactor de impacto (Donier-Bonart, BTC)
_SQRT_SIGMA = 0.02  # volatilidad diaria como fracción (~2%/día)
_SQRT_V_REF_BTC = 1.0e4  # volumen diario de referencia de mercado profundo (BTC/día)

_DEMO_FEE = 0.0004  # taker VIP2 por defecto en demo
_N_POINTS = 24  # número de puntos de la barrida
_Q_MIN_FRAC = 1.0 / _N_POINTS  # primer Q como fracción del cap (espaciado lineal)


def _depth_sum(levels: list[tuple[float, float]]) -> float:
    """Suma de tamaños disponibles en un lado del libro (BTC)."""
    return sum(size for _price, size in levels)


def _sqrt_impact_usd(q: float, ref_price: float) -> float:
    """Overlay teórico square-root law: I(Q) = Y·σ·sqrt(Q/V)·Q en USD.

    Ilustrativo (Donier-Bonart δ≈0.5, Y≈0.9 para BTC); no afecta al neto real.
    """
    if q <= 0 or ref_price <= 0:
        return 0.0
    impact_frac = _SQRT_Y * _SQRT_SIGMA * math.sqrt(q / _SQRT_V_REF_BTC)
    return impact_frac * q * ref_price


def _linear_zero_crossing(
    x0: float, y0: float, x1: float, y1: float
) -> float | None:
    """Q donde un segmento (x0,y0)->(x1,y1) cruza y=0 (interpolación lineal)."""
    if y0 == y1:
        return None
    if (y0 > 0) == (y1 > 0):
        return None
    t = y0 / (y0 - y1)
    return x0 + t * (x1 - x0)


def build_capacity_curve(
    settings: Settings | None = None,
    books: dict[str, NormalizedBook] | None = None,
    *,
    mode: str = "demo",
    fee: float | None = None,
) -> CapacityResult:
    """Construye la curva de capacidad de la oportunidad de arbitraje.

    Args:
        settings: configuración; por defecto :func:`get_settings`.
        books: libros normalizados por venue (sólo modo ``live``).
        mode: ``"demo"`` (cross fijo) o ``"live"`` (mejor ruta de ``books``).
            ``live`` sin ruta viva cae a ``demo``.
        fee: fee taker fraccional. ``None`` → demo usa ``0.0004`` (VIP2); live usa
            ``settings.exchanges[buy].fee_taker`` o ``0.0004``.

    Returns:
        :class:`CapacityResult` con la barrida de puntos, ``q_star_btc`` (óptimo),
        ``hard_capacity_btc`` (cruce a cero tras el pico) y el overlay
        square-root como validación teórica.
    """
    settings = settings if settings is not None else get_settings()

    route: dict[str, str] | None = None
    notes = ""

    # --- Selección del cross según el modo --------------------------------
    buy_asks: list[tuple[float, float]]
    sell_bids: list[tuple[float, float]]
    rebalance_btc: float
    resolved_fee: float

    live_route = _best_route(books) if (mode == "live" and books) else None
    if mode == "live" and live_route is not None:
        buy_name, sell_name, buy_book, sell_book = live_route
        buy_asks = buy_book.asks
        sell_bids = sell_book.bids
        buy_cfg = settings.exchanges.get(buy_name)
        sell_cfg = settings.exchanges.get(sell_name)
        wd_buy = buy_cfg.withdrawal_btc if buy_cfg is not None else 0.0
        wd_sell = sell_cfg.withdrawal_btc if sell_cfg is not None else 0.0
        trades = max(1, settings.expected_trades_per_rebalance)
        rebalance_btc = (wd_buy + wd_sell) / trades
        resolved_fee = (
            fee
            if fee is not None
            else ((buy_cfg.fee_taker if buy_cfg is not None else None) or 0.0004)
        )
        route = {"buy": buy_name, "sell": sell_name, "symbol": buy_book.symbol}
        actual_mode = "live"
    else:
        if mode == "live":
            notes = "live sin ruta viva: fallback a demo. "
        buy_asks = _BUY_ASKS
        sell_bids = _SELL_BIDS
        rebalance_btc = _WD_BTC_DEMO
        resolved_fee = fee if fee is not None else _DEMO_FEE
        actual_mode = "demo"

    # --- Rango de la barrida: lineal de Q_min hasta el cap de profundidad --
    cap = min(_depth_sum(buy_asks), _depth_sum(sell_bids))
    points: list[CapacityPoint] = []

    if cap <= 0:
        return CapacityResult(
            mode=actual_mode,
            route=route,
            fee_bps=resolved_fee * 10000.0,
            points=[],
            notes=notes + "sin profundidad disponible.",
        )

    ref_price = (
        (buy_asks[0][0] + sell_bids[0][0]) / 2.0
        if buy_asks and sell_bids
        else 0.0
    )

    q_grid = [cap * _Q_MIN_FRAC * i for i in range(1, _N_POINTS + 1)]

    prev_q: float | None = None
    prev_edge: float | None = None
    for q in q_grid:
        nb = compute_net(
            buy_asks,
            sell_bids,
            q,
            fee_buy=resolved_fee,
            fee_sell=resolved_fee,
            rebalance_btc=rebalance_btc,
        )
        edge_total = nb.net
        if prev_q is None or prev_edge is None:
            # primer punto: marginal = neto por BTC
            marginal = nb.net_per_btc
        else:
            dq = q - prev_q
            marginal = (edge_total - prev_edge) / dq if dq > 0 else 0.0
        points.append(
            CapacityPoint(
                q_btc=q,
                edge_total_usd=edge_total,
                edge_marginal_per_btc=marginal,
                sqrt_impact_usd=_sqrt_impact_usd(q, ref_price),
            )
        )
        prev_q = q
        prev_edge = edge_total

    # --- Q* = máximo de edge_total (donde el marginal cruza 0) ------------
    star_idx = max(range(len(points)), key=lambda i: points[i].edge_total_usd)
    q_star_btc = points[star_idx].q_btc
    q_star_edge_usd = points[star_idx].edge_total_usd

    # --- hard capacity: primer cruce a 0 del edge_total tras el pico ------
    hard_capacity_btc: float | None = None
    for i in range(star_idx, len(points) - 1):
        cross = _linear_zero_crossing(
            points[i].q_btc,
            points[i].edge_total_usd,
            points[i + 1].q_btc,
            points[i + 1].edge_total_usd,
        )
        if cross is not None:
            hard_capacity_btc = cross
            break

    throughput_usd_per_opp = q_star_edge_usd

    return CapacityResult(
        mode=actual_mode,
        route=route,
        fee_bps=resolved_fee * 10000.0,
        points=points,
        q_star_btc=q_star_btc,
        q_star_edge_usd=q_star_edge_usd,
        hard_capacity_btc=hard_capacity_btc,
        throughput_usd_per_opp=throughput_usd_per_opp,
        notes=notes.strip(),
    )
