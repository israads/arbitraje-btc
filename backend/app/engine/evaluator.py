"""C6 — Evaluador de rentabilidad NETA (FR-005 / FR-008, STORY-008).

Toma una `Opportunity(status=detected)` del detector espacial (C5) y los dos
`NormalizedBook` involucrados (venue de compra y venue de venta) y decide su
viabilidad económica recorriendo los libros nivel a nivel (walk-the-book).

Pipeline (Apéndice D.1 de la arquitectura):
  1. Cantidad alcanzable `q = min(objetivo, profundidad_asks_compra, profundidad_bids_venta)`.
     Si la profundidad no alcanza una `q` mínima razonable → `discarded(thin_book)`.
  2. VWAP de compra recorriendo los `asks` del venue de compra (de menor a mayor
     precio) y VWAP de venta recorriendo los `bids` del venue de venta (de mayor a
     menor precio), para esa `q`.
  3. `gross = (vwap_sell - vwap_buy) * q`.
  4. Fees taker ÚNICA por leg (taker/taker), cada una con el `fee_taker` del
     `ExchangeConfig` de su venue: `q*vwap_buy*fee_buy + q*vwap_sell*fee_sell`.
     Nunca doble fee.
  5. Slippage real derivado del VWAP ejecutado vs top-of-book (nunca cero). Filtro
     pre-trade `max_slippage` (ver DECISIÓN DE SLIPPAGE más abajo).
  6. Costo de rebalanceo amortizado por trade (ver FÓRMULA DE REBALANCEO más abajo).
  7. `net = gross - fees - rebalanceo_amortizado`.
  8. `net > min_net_profit_usd` → `viable`; si no → `discarded(not_profitable_fees)`
     (estricto: descarta E[neto]≤umbral, FR-007 AC#2).
     En AMBOS casos se rellenan vwap_buy/vwap_sell (VWAP recorridos, NO top-of-book),
     fees, slippage, net_pnl y q_target.

Precios YA en USD por peg (NormalizedBook): NO se re-normaliza. Sin look-ahead:
sólo el libro actual.

---
FÓRMULA DE REBALANCEO AMORTIZADO (Apéndice D.1 `cfg.rebalance_cost_amortized`):

El inventario está pre-posicionado en cada venue (ADR: así operan los market makers;
no hay withdrawal on-chain por trade). El costo on-chain de mover BTC entre venues se
amortiza por trade. Cada trade consume BTC del venue de compra y deposita en el de
venta; reponer ese flujo implica un retiro on-chain en CADA venue, cuyo fee fijo está
en `ExchangeConfig.withdrawal_btc` (en BTC). Valoramos esos BTC a precio de mercado
(usamos `vwap_buy`, el precio del leg que origina el movimiento de inventario):

    rebalance_amortized_usd = (withdrawal_btc_buy + withdrawal_btc_sell) * vwap_buy

Es un costo fijo por trade (independiente de `q`): por eso penaliza más a `q` pequeñas
y se "amortiza" cuanto mayor sea el tamaño ejecutado. Determinista y 100% derivado de
config + libro actual (sin red ni reloj).

---
DECISIÓN DE SLIPPAGE: el slippage relativo de cada leg es el desvío del VWAP ejecutado
respecto al top-of-book de ESE leg:
    slip_buy  = (vwap_buy  - best_ask_compra) / best_ask_compra   # >=0 (peor al comprar)
    slip_sell = (best_bid_venta - vwap_sell) / best_bid_venta     # >=0 (peor al vender)
Si CUALQUIERA supera `max_slippage` → `discarded(slippage_over_limit)` (filtro
pre-trade duro del Apéndice D.3), en vez de recortar `q`: recortar reabriría el
walk-the-book de forma iterativa y enmascararía libros finos que el reto quiere
descartar explícitamente. El campo `opp.slippage` guarda el slippage agregado en USD
(VWAP vs top-of-book en ambos legs) para trazabilidad.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..config import ExchangeConfig, Settings
from ..models.enums import DiscardReason, OpportunityStatus
from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity
from .bookmath import walk_book
from .cost_model import NetBreakdown, compute_net
from .explain import build_opportunity_explanation

if TYPE_CHECKING:
    from ..normalize.peg import PegProvider

# Fracción mínima del objetivo que debe poder llenarse para considerar el libro
# suficientemente profundo. Por debajo → thin_book.
_MIN_FILL_RATIO = 0.10

# Re-export retro-compatible: `walk_book` vive ahora en `engine/bookmath.py` (módulo
# neutral, fuente única de verdad). El código y los tests existentes lo importan desde
# aquí —`walk_book` y el alias `_walk_book`—; se mantienen como re-exports.
_walk_book = walk_book

__all__ = ["NetEvaluator", "walk_book"]


class NetEvaluator:
    """Evaluador de neto (C6). Sin estado entre oportunidades: cada `evaluate` es
    puro respecto a los libros que recibe (determinista, sin red ni reloj)."""

    def __init__(self, settings: Settings, peg: PegProvider | None = None) -> None:
        self.settings = settings
        # C3/FR-003: con peg inyectado, el evaluador descarta `peg_adverse` cuando una stable
        # de algún leg se desvía de su peg más allá de `peg_tolerance` (durante un depeg la
        # comparación cross-venue no es fiable). Opcional → retrocompatible con los tests.
        self.peg = peg

    def _fee(self, venue: str) -> float:
        """Fee taker del venue desde su `ExchangeConfig`. Fee único por leg."""
        cfg: ExchangeConfig | None = self.settings.exchanges.get(venue)
        # Sin config explícita asumimos 0.0 (no inventamos costos): conservador y
        # determinista. Los venues del reto siempre están en config.
        return cfg.fee_taker if cfg is not None else 0.0

    def _withdrawal_btc(self, venue: str) -> float:
        cfg: ExchangeConfig | None = self.settings.exchanges.get(venue)
        return cfg.withdrawal_btc if cfg is not None else 0.0

    def _attach_explanation(
        self,
        opp: Opportunity,
        buy_book: NormalizedBook,
        sell_book: NormalizedBook,
        *,
        breakdown: NetBreakdown | None = None,
    ) -> Opportunity:
        opp.explanation = build_opportunity_explanation(
            opp, buy_book, sell_book, self.settings, breakdown=breakdown
        )
        return opp

    def evaluate(
        self,
        opp: Opportunity,
        buy_book: NormalizedBook,
        sell_book: NormalizedBook,
    ) -> Opportunity:
        """Evalúa el neto de `opp` (detected) usando `buy_book` (venue de compra) y
        `sell_book` (venue de venta). Muta y devuelve la misma `opp` con
        status=viable|discarded y los campos económicos rellenos."""
        q_objetivo = self.settings.default_trade_qty_btc

        # --- 0) Gate de peg adverso (C3/FR-003) ---
        # Si CUALQUIER leg cotiza en una stable desviada de su peg > peg_tolerance, la
        # normalización a USD es poco fiable: el "cruce" puede ser un artefacto del depeg, no
        # arbitraje real. Se descarta ANTES del walk-the-book (no gastamos cómputo). USD puro
        # y stables dentro de banda pasan (within_tolerance → True). Sin peg inyectado: no-op.
        if self.peg is not None and not (
            self.peg.within_tolerance(buy_book.quote_ccy)
            and self.peg.within_tolerance(sell_book.quote_ccy)
        ):
            self._discard(opp, DiscardReason.peg_adverse, q=0.0)
            return self._attach_explanation(opp, buy_book, sell_book)

        # --- 1) Cantidad alcanzable: walk-the-book en ambos legs (Apéndice D.1) ---
        # asks de compra (asc.) y bids de venta (desc.) ya vienen ordenados del book.
        vwap_buy, filled_buy = _walk_book(buy_book.asks, q_objetivo)
        vwap_sell, filled_sell = _walk_book(sell_book.bids, q_objetivo)
        q = min(filled_buy, filled_sell)  # liquidez efectiva (ambas patas)

        # Profundidad insuficiente, no finita o nula → thin_book.
        # `not math.isfinite(q)` captura NaN/inf de un libro corrupto (toda
        # comparación con NaN es False, así que sin este guard el NaN se propagaría
        # hasta el neto y se etiquetaría con un motivo económico erróneo).
        if not math.isfinite(q) or q < _MIN_FILL_RATIO * q_objetivo or q <= 0.0:
            self._discard(opp, DiscardReason.thin_book, q=q)
            return self._attach_explanation(opp, buy_book, sell_book)

        # Reconstruimos los VWAP exactamente para la q efectiva (no para q_objetivo),
        # de modo que ambos legs midan el MISMO tamaño ejecutable.
        vwap_buy, _ = _walk_book(buy_book.asks, q)
        vwap_sell, _ = _walk_book(sell_book.bids, q)

        # --- 5) Slippage real: VWAP ejecutado vs top-of-book (nunca cero) ---
        # Tras el guard de thin_book (q>0) ambos legs tuvieron fill, así que best_ask/
        # best_bid no son None; el `or 0.0` los normaliza a float (tipado) y mantiene el
        # cómputo seguro si el book fuera degenerado (slippage 0 en vez de propagar None).
        best_ask = buy_book.best_ask or 0.0   # mejor precio de compra (asks[0])
        best_bid = sell_book.best_bid or 0.0  # mejor precio de venta (bids[0])
        slip_buy_rel = (vwap_buy - best_ask) / best_ask if best_ask else 0.0
        slip_sell_rel = (best_bid - vwap_sell) / best_bid if best_bid else 0.0
        # Slippage agregado en USD (impacto del walk-the-book frente al top-of-book).
        slippage_usd = (vwap_buy - best_ask) * q + (best_bid - vwap_sell) * q

        # Filtro pre-trade duro (Apéndice D.3): cualquier leg sobre max_slippage descarta.
        if (
            slip_buy_rel > self.settings.max_slippage
            or slip_sell_rel > self.settings.max_slippage
        ):
            opp.vwap_buy = vwap_buy
            opp.vwap_sell = vwap_sell
            opp.slippage = slippage_usd
            opp.q_target = q
            nb = compute_net(
                buy_book.asks,
                sell_book.bids,
                q,
                fee_buy=self._fee(opp.buy_venue),
                fee_sell=self._fee(opp.sell_venue),
                rebalance_btc=(
                    self._withdrawal_btc(opp.buy_venue) + self._withdrawal_btc(opp.sell_venue)
                ) / self.settings.expected_trades_per_rebalance,
                top_ask=best_ask,
                top_bid=best_bid,
            )
            self._discard(opp, DiscardReason.slippage_over_limit, q=q)
            return self._attach_explanation(opp, buy_book, sell_book, breakdown=nb)

        # --- 3-7) Gross, fees por leg, rebalanceo amortizado y neto ---
        # Fuente ÚNICA de la aritmética (engine/cost_model.py): el MISMO cómputo que usa la
        # proyección, para que evaluador y frontier no diverjan jamás. `rebalance_btc` es el
        # retiro on-chain fijo por trade (wd_buy+wd_sell), amortizable por ciclo (F1): por
        # defecto `expected_trades_per_rebalance`=1 ⇒ comportamiento idéntico al anterior.
        nb = compute_net(
            buy_book.asks,
            sell_book.bids,
            q,
            fee_buy=self._fee(opp.buy_venue),
            fee_sell=self._fee(opp.sell_venue),
            rebalance_btc=(
                self._withdrawal_btc(opp.buy_venue) + self._withdrawal_btc(opp.sell_venue)
            ) / self.settings.expected_trades_per_rebalance,
            top_ask=best_ask,
            top_bid=best_bid,
        )

        # Campos económicos (VWAP recorridos, NO top-of-book) — siempre rellenos.
        opp.vwap_buy = nb.vwap_buy
        opp.vwap_sell = nb.vwap_sell
        opp.fees = nb.fees
        opp.slippage = slippage_usd
        opp.q_target = q
        opp.net_pnl = nb.net
        net = nb.net

        # --- 8) Veredicto ---
        # Estricto `>`: descarta E[neto] <= umbral (FR-007 AC#2 "descarta E[neto]≤0"). Con el
        # umbral por defecto 0, un neto nulo o negativo NO es oportunidad (no se ejecuta a
        # margen cero).
        if net > self.settings.min_net_profit_usd:
            opp.status = OpportunityStatus.viable
            opp.discard_reason = None
        else:
            opp.status = OpportunityStatus.discarded
            opp.discard_reason = DiscardReason.not_profitable_fees
        return self._attach_explanation(opp, buy_book, sell_book, breakdown=nb)

    def _discard(
        self, opp: Opportunity, reason: DiscardReason, *, q: float
    ) -> Opportunity:
        """Marca la oportunidad como descartada preservando lo ya calculado.

        `q` es la liquidez efectiva realmente alcanzable (min de ambas patas).
        En thin_book SIEMPRE fijamos `q_target = q` para reflejar la liquidez real,
        sin usar el default como centinela (frágil: evaluate() es API pública y puede
        recibir oportunidades con `q_target` distinto del default, p.ej. dimensionado
        dinámico). En slippage_over_limit el llamador ya fijó `opp.q_target = q`, así
        que reescribirlo aquí con la misma `q` es idempotente. Saneamos NaN/inf a 0.0."""
        opp.status = OpportunityStatus.discarded
        opp.discard_reason = reason
        opp.q_target = max(q, 0.0) if math.isfinite(q) else 0.0
        # En descartes tempranos (thin_book) el neto no se computa: queda None.
        return opp
