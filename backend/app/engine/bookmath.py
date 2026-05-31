"""Primitivas de cálculo sobre el order book (walk-the-book taker).

Módulo NEUTRAL: la fuente única de verdad del recorrido taker nivel a nivel. Lo consumen
tanto el evaluador de neto (C6, `engine/evaluator.py`) como el simulador de ejecución
(C9, `sim/simulator.py`). Vive aquí —y no dentro del evaluador— para que el simulador no
dependa conceptualmente de C6: ambos componentes comparten la MISMA aritmética de fill
sin que uno importe del otro. Sin estado, sin red ni reloj: 100% determinista.
"""
from __future__ import annotations

import math

from ..models.market import NormalizedBook, PriceLevel


def mid_lenient(book: NormalizedBook) -> float | None:
    """Mid de MARCA tolerante: (bid+ask)/2 si ambos lados son finitos y >0; si no, el lado
    válido que quede; None si ninguno sirve. Fuente única para marcar a mercado donde un solo
    lado del book aún da una marca razonable (circuit breakers vol, equity de cartera). Difiere
    del mid ESTRICTO del motor estadístico (`engine/statz._mid`), que exige AMBOS lados porque
    alimenta `ln(spread)` y un mid de un solo lado sesgaría la señal."""
    bid, ask = book.best_bid, book.best_ask
    ok_bid = bid is not None and math.isfinite(bid) and bid > 0.0
    ok_ask = ask is not None and math.isfinite(ask) and ask > 0.0
    if ok_bid and ok_ask and bid is not None and ask is not None:
        return (bid + ask) / 2.0
    if ok_bid:
        return bid
    if ok_ask:
        return ask
    return None


def walk_book(levels: list[PriceLevel], q: float) -> tuple[float, float]:
    """Recorre `levels` (asks asc. para compra / bids desc. para venta) acumulando
    hasta `q`. Devuelve `(vwap, filled)`; `filled < q` indica profundidad parcial.
    `vwap` es 0.0 si no hay nada que llenar.

    Util compartido (taker fill por niveles): lo reutilizan el evaluador de neto (C6) y el
    simulador de ejecución (C9) para no duplicar la lógica de recorrido del book. Fuente
    única de verdad del walk-the-book taker.

    Robustez: para SOLO cuando `q` ya está llena (no por un nivel vacío
    intermedio) y salta niveles sin liquidez (`qty <= 0.0`) o no finitos
    (NaN/inf en precio o cantidad), que ccxt/feeds reales emiten como deltas de
    remoción o ruido de snapshot. Así un `[price, 0]` o un NaN antepuesto a
    liquidez real no corta el recorrido ni contamina el VWAP/filled."""
    acc_qty = 0.0
    acc_cost = 0.0
    for price, qty in levels:
        if acc_qty >= q:  # `q` ya llena: paramos (no por un nivel vacío)
            break
        # Nivel sin liquidez o no finito (precio/cantidad): se ignora, no corta.
        if qty <= 0.0 or not math.isfinite(qty) or not math.isfinite(price):
            continue
        take = min(qty, q - acc_qty)
        acc_cost += take * price
        acc_qty += take
    vwap = acc_cost / acc_qty if acc_qty > 0.0 else 0.0
    return vwap, acc_qty
