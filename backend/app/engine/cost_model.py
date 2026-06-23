"""ExecutionCostModel — fuente ÚNICA de la economía de un cruce (walk-the-book taker).

Antes, el neto se calculaba en DOS sitios con fórmulas ligeramente distintas: el evaluador
(C6, `engine/evaluator.py`, fees por venue + rebalanceo desde `ExchangeConfig.withdrawal_btc`)
y la proyección (`validate/projection.py`, fee simétrico + rebalanceo con constantes hardcodeadas).
Eso es drift: dos implementaciones de la MISMA economía que pueden divergir en silencio.

Este módulo extrae la aritmética a una sola función pura, determinista, sin estado ni red ni
reloj. La consumen el evaluador (C6) y la proyección (frontier/capacity/scenarios). La definición
de neto es EXACTAMENTE la del evaluador (la que reconcilia `$109.75/BTC`):

    net       = gross − fees − rebalance
    gross     = (vwap_sell − vwap_buy) · filled
    fees      = (vwap_buy·fee_buy + vwap_sell·fee_sell) · filled
    rebalance = rebalance_btc · vwap_buy          # coste FIJO por trade (independiente de q)

donde `vwap_*` y `filled = min(filled_buy, filled_sell)` salen de caminar cada libro hasta `q`.
`rebalance_btc` = BTC de retiro on-chain por trade (en el evaluador, `wd_buy + wd_sell`). Como es
fijo por trade, penaliza más a tamaños pequeños y se "amortiza" cuanto mayor sea `q`. El factor
de amortización por ciclo (F1) se aplica EN EL LLAMADOR dividiendo `rebalance_btc` entre los
trades esperados por rebalanceo — por defecto 1 (= comportamiento actual, cero regresión).
"""
from __future__ import annotations

from dataclasses import dataclass

from .bookmath import walk_book
from .depth_curve import DepthCurve


@dataclass(frozen=True)
class NetBreakdown:
    """Descomposición del neto de un cruce a tamaño `filled` (USD salvo cantidades en BTC).

    `dominant_cost` ∈ {"fees", "slippage", "rebalance", "none"} = la fricción que más
    erosiona el edge (para el panel "por qué muere" del dashboard). "none" si no hay coste
    relevante (p.ej. sin liquidez)."""

    filled: float
    depth_limited: bool          # filled < q solicitado (se agotó el libro)
    vwap_buy: float
    vwap_sell: float
    gross: float                 # (vwap_sell − vwap_buy)·filled
    fees: float                  # fees totales de ambas patas (USD)
    fees_buy: float
    fees_sell: float
    rebalance: float             # coste de rebalanceo fijo por trade (USD)
    slippage_buy: float          # vwap_buy − top_ask (USD/BTC)
    slippage_sell: float         # top_bid − vwap_sell (USD/BTC)
    slippage_cost: float         # (slippage_buy + slippage_sell)·filled (USD, vs ejecutar al top)
    net: float                   # gross − fees − rebalance (USD)
    net_per_btc: float           # net / filled (USD/BTC); 0.0 si filled == 0
    dominant_cost: str


_EMPTY = NetBreakdown(
    filled=0.0, depth_limited=True, vwap_buy=0.0, vwap_sell=0.0, gross=0.0, fees=0.0,
    fees_buy=0.0, fees_sell=0.0, rebalance=0.0, slippage_buy=0.0, slippage_sell=0.0,
    slippage_cost=0.0, net=0.0, net_per_btc=0.0, dominant_cost="none",
)


def compute_net(
    buy_asks: list[tuple[float, float]],
    sell_bids: list[tuple[float, float]],
    q: float,
    *,
    fee_buy: float,
    fee_sell: float,
    rebalance_btc: float = 0.0,
    top_ask: float | None = None,
    top_bid: float | None = None,
) -> NetBreakdown:
    """Neto de comprar `q` BTC en `buy_asks` y vender en `sell_bids`, tras fees y rebalanceo.

    `fee_*` = fracción taker por pata (no %). `rebalance_btc` = BTC de retiro por trade (coste
    fijo, valorado a `vwap_buy`). `top_*` = mejor precio operable para medir slippage (si None,
    se usa el VWAP → slippage 0, igual que el evaluador con `best_ask or vwap`). Determinista;
    nunca lanza. `NetBreakdown` vacío si no hay liquidez."""
    vwap_buy, filled_buy = walk_book(buy_asks, q)
    vwap_sell, filled_sell = walk_book(sell_bids, q)
    return _compute_from_fills(
        q,
        vwap_buy,
        filled_buy,
        vwap_sell,
        filled_sell,
        fee_buy=fee_buy,
        fee_sell=fee_sell,
        rebalance_btc=rebalance_btc,
        top_ask=top_ask,
        top_bid=top_bid,
    )


def compute_net_from_curves(
    buy_curve: DepthCurve,
    sell_curve: DepthCurve,
    q: float,
    *,
    fee_buy: float,
    fee_sell: float,
    rebalance_btc: float = 0.0,
    top_ask: float | None = None,
    top_bid: float | None = None,
) -> NetBreakdown:
    """Neto equivalente a `compute_net`, pero usando curvas de profundidad precomputadas."""
    vwap_buy, filled_buy = buy_curve.vwap(q)
    vwap_sell, filled_sell = sell_curve.vwap(q)
    return _compute_from_fills(
        q,
        vwap_buy,
        filled_buy,
        vwap_sell,
        filled_sell,
        fee_buy=fee_buy,
        fee_sell=fee_sell,
        rebalance_btc=rebalance_btc,
        top_ask=top_ask,
        top_bid=top_bid,
    )


def _compute_from_fills(
    q: float,
    vwap_buy: float,
    filled_buy: float,
    vwap_sell: float,
    filled_sell: float,
    *,
    fee_buy: float,
    fee_sell: float,
    rebalance_btc: float = 0.0,
    top_ask: float | None = None,
    top_bid: float | None = None,
) -> NetBreakdown:
    filled = min(filled_buy, filled_sell)
    if filled <= 0.0:
        return _EMPTY

    gross = (vwap_sell - vwap_buy) * filled
    fees_buy = vwap_buy * filled * fee_buy
    fees_sell = vwap_sell * filled * fee_sell
    fees = fees_buy + fees_sell
    rebalance = rebalance_btc * vwap_buy
    net = gross - fees - rebalance

    slip_buy = vwap_buy - (top_ask if top_ask is not None else vwap_buy)
    slip_sell = (top_bid if top_bid is not None else vwap_sell) - vwap_sell
    slippage_cost = (slip_buy + slip_sell) * filled

    # Coste dominante: la fricción de mayor magnitud (USD). Sólo cuenta costes positivos.
    costs = {"fees": fees, "slippage": slippage_cost, "rebalance": rebalance}
    pos = {k: v for k, v in costs.items() if v > 0.0}
    dominant = max(pos, key=lambda k: pos[k]) if pos else "none"

    return NetBreakdown(
        filled=filled,
        depth_limited=filled < q - 1e-9,
        vwap_buy=vwap_buy,
        vwap_sell=vwap_sell,
        gross=gross,
        fees=fees,
        fees_buy=fees_buy,
        fees_sell=fees_sell,
        rebalance=rebalance,
        slippage_buy=slip_buy,
        slippage_sell=slip_sell,
        slippage_cost=slippage_cost,
        net=net,
        net_per_btc=net / filled,
        dominant_cost=dominant,
    )
