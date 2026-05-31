"""C9 — Simulador de ejecución TAKER con fills parciales, leg risk y unwind (FR-008/FR-009).

Toma una `Opportunity` ya `viable` (evaluada por C6) y simula su ejecución como TAKER en
ambos venues, recorriendo los libros nivel a nivel (walk-the-book) tal y como hace el
evaluador. Produce un `Execution` con sus `Leg` (buy/sell), el tramo casado, el P&L
realizado y la exposición de LEG RISK.

MODELO SECUENCIAL CON LATENCIA (Apéndice D.3, STORY-016):
  1. Fill leg1 = COMPRA (venue barato) recorriendo los `asks` del venue de compra →
     (vwap_buy, filled_buy). Fee taker ÚNICA por leg.
  2. Tras la latencia simulada (`cfg.exec_latency_ms`, 100-200 ms) se RE-LEE el book de la
     2ª pata (venta) en el tick t+Δ y se recomputa la rentabilidad del tramo casado:
       · si SIGUE rentable (neto del matched >= `min_net_profit_usd` y el slippage del leg2
         re-leído <= `max_slippage`) ⇒ se rellena leg2 (PARCIAL si la profundidad no
         alcanza) y se registra el `Execution` con su leg risk (igual que STORY-009).
       · si NO ⇒ UNWIND del leg1 a mercado: se vende lo comprado de vuelta en el venue de
         compra (recorriendo sus `bids`); `realized_pnl` = pérdida del unwind; `unwound=True`
         y `unwind_reason` registra el motivo. No se ejecuta el leg2.
  3. Filtro PRE-TRADE de slippage (Apéndice D.3): antes de comprometer el leg1, si el
     slippage estimado (leg1 vs su top-of-book, o leg2 sobre el book PRE-latencia) supera
     `cfg.max_slippage` ⇒ no se opera y se descarta (`slippage_over_limit`, devuelve `None`).

RE-LECTURA DEL BOOK t+Δ — HONESTIDAD (sin look-ahead, sin reloj):
  El book t+Δ del leg2 se INYECTA vía `sell_book_t1`. Cuando NO se pasa (`None`) NO se
  fabrica ninguna deriva: el leg2 se rellena contra el mismo snapshot que el leg1 y el
  resultado es idéntico a STORY-009 (sin unwind, sin gate de slippage extra). El motor en
  vivo detecta→evalúa→simula de forma SÍNCRONA sobre el MISMO snapshot de libros del
  detector (no hay desfase temporal real entre evaluar y simular), así que pasa `None` y
  nunca hace unwinds espurios. La deriva real t+Δ la alimentan el BACKTEST/REPLAY (STORY-021,
  que sí conoce el book posterior de los datos grabados) y los tests deterministas. Así el
  unwind es una capacidad REAL y probada, sin inventar movimientos de precio que no ocurren.

P&L del tramo CASADO (precisión, NFR-004): el VWAP del tramo casado se RE-CALCULA recorriendo
cada book exactamente hasta `matched` (mismo patrón que el evaluador para la `q` efectiva),
NO se reutiliza el VWAP del fill COMPLETO del leg. Cuando los fills son asimétricos (leg
risk) el leg sobre-llenado promedia niveles profundos que pertenecen al EXCEDENTE, no al
tramo casado; el matched se ejecuta SIEMPRE en los mejores niveles (cheapest-first al comprar
/ best-first al vender). Las fees del tramo casado se cobran sobre ese mismo VWAP del matched.

Reglas críticas respetadas: precios YA en USD por peg (NO se re-normaliza); fee único taker
por leg; sin look-ahead (sólo libros provistos); 100% determinista (sin red ni `sleep`).
"""
from __future__ import annotations

import math
import time

from ..config import ExchangeConfig, Settings
from ..engine.bookmath import walk_book
from ..models.enums import DiscardReason, LegSide, OpportunityStatus
from ..models.execution import Execution, Leg
from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity

_DUST = 1e-12


class ExecutionSimulator:
    """Simulador de ejecución TAKER (C9). Sin estado entre ejecuciones: cada `simulate`
    es puro respecto a la oportunidad y los libros que recibe (determinista, sin red ni
    reloj para el cómputo). El P&L/equity (STORY-010) y la persistencia (STORY-011) consumen
    el `Execution` resultante; la API se mantiene limpia para eso.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _fee_taker(self, venue: str) -> float:
        """Fee taker del venue desde su `ExchangeConfig`. Fee único por leg (nunca doble).
        Sin config explícita → 0.0 (no inventamos costos): conservador y determinista."""
        cfg: ExchangeConfig | None = self.settings.exchanges.get(venue)
        return cfg.fee_taker if cfg is not None else 0.0

    def _withdrawal_btc(self, venue: str) -> float:
        """Fee de retiro on-chain (BTC) del venue, para el rebalanceo amortizado (igual que
        el evaluador C6). Sin config → 0.0."""
        cfg: ExchangeConfig | None = self.settings.exchanges.get(venue)
        return cfg.withdrawal_btc if cfg is not None else 0.0

    @staticmethod
    def _top_sane(levels: list[tuple[float, float]]) -> float | None:
        """Precio del primer nivel con liquidez REAL (precio y qty finitos, qty>0), aplicando
        el MISMO filtro que `walk_book`. El top-of-book CRUDO (`best_bid`/`best_ask`) puede ser
        un nivel FANTASMA —qty=0 (delta de remoción) o NaN— que el fill IGNORA; medir el
        slippage contra él descartaría/desharía oportunidades perfectamente operables (el walk
        las llena a un nivel más profundo, sin slippage real frente al top operable). None si
        no hay ningún nivel operable."""
        for price, qty in levels:
            if qty > 0.0 and math.isfinite(qty) and math.isfinite(price) and price > 0.0:
                return float(price)
        return None

    @staticmethod
    def _excess_vwap(
        vwap_full: float,
        filled: float,
        vwap_matched: float,
        matched: float,
        excess_qty: float,
    ) -> float:
        """VWAP del tramo EXCEDENTE (leg risk) del leg sobre-llenado, derivado por balance
        de coste sin re-leer el book: el coste total del fill es `vwap_full*filled` y el del
        tramo casado `vwap_matched*matched`, así el coste del excedente es la diferencia y su
        VWAP el coste por BTC. Es el coste base que el P&L de unwind/mark-to-market necesita
        (`(precio - entry_vwap) * qty`), sin look-ahead ni re-derivación. `excess_qty` es
        `> 0` en el llamador; si por redondeo no, cae al VWAP completo (conservador)."""
        if excess_qty <= 0.0:
            return vwap_full
        return (vwap_full * filled - vwap_matched * matched) / excess_qty

    @staticmethod
    def _sane_mark(mark: float | None, fallback: float) -> float:
        """Sanea un precio de marca (top-of-book) como hace `walk_book` con los niveles: un
        snapshot corrupto puede traer NaN/inf o <= 0 y eso propagaría un MTM no finito a
        equity/persistencia (STORY-010/011). Cae al `fallback` (VWAP recorrido del leg, ya
        finito) y, si tampoco vale, a 0.0."""
        if mark is not None and math.isfinite(mark) and mark > 0.0:
            return mark
        return fallback if math.isfinite(fallback) and fallback > 0.0 else 0.0

    def _slippage_breached(
        self, vwap: float, top: float | None, *, is_buy: bool
    ) -> bool:
        """`True` si el slippage relativo del leg (VWAP recorrido vs su top-of-book) supera
        `max_slippage`. Compra: `(vwap-best_ask)/best_ask`; venta: `(best_bid-vwap)/best_bid`
        (ambos >=0 cuando el walk empeora respecto al top). Top no finito/<=0 → no se puede
        medir, no se bloquea (conservador: el evaluador ya filtró pre-latencia)."""
        if top is None or not math.isfinite(top) or top <= 0.0 or vwap <= 0.0:
            return False
        rel = (vwap - top) / top if is_buy else (top - vwap) / top
        return rel > self.settings.max_slippage

    def simulate(
        self,
        opp: Opportunity,
        buy_book: NormalizedBook,
        sell_book: NormalizedBook,
        *,
        sell_book_t1: NormalizedBook | None = None,
        ts: float | None = None,
    ) -> Execution | None:
        """Simula la ejecución TAKER de `opp` (viable). `buy_book` = venue de compra (leg1),
        `sell_book` = venue de venta (leg2) en el instante t. `sell_book_t1` es la RE-LECTURA
        del book de venta tras la latencia (tick t+Δ): si es `None` se usa `sell_book` (sin
        deriva, comportamiento STORY-009). Devuelve el `Execution` y muta `opp.status`; en el
        descarte pre-trade por slippage devuelve `None` y marca `opp` como `discarded`.

        `ts` es el sello temporal del `Execution` (monotónico/epoch). Si no se pasa se usa
        `time.monotonic()`; los asserts deterministas NO deben depender de este valor."""
        q_target = opp.q_target if opp.q_target and opp.q_target > 0.0 else (
            self.settings.default_trade_qty_btc
        )
        ts_val = ts if ts is not None else time.monotonic()
        fee_buy_rate = self._fee_taker(opp.buy_venue)
        fee_sell_rate = self._fee_taker(opp.sell_venue)

        # `sell_eff` = libro de la 2ª pata realmente usado para el fill. Con re-lectura t+Δ
        # explícita es ese; si no, el snapshot inicial (sin deriva: idéntico a STORY-009).
        latency_reread = sell_book_t1 is not None
        sell_eff = sell_book_t1 if sell_book_t1 is not None else sell_book

        # --- 1) Fill leg1 = COMPRA recorriendo los asks del venue de compra (instante t) ---
        vwap_buy, filled_buy = walk_book(buy_book.asks, q_target)
        fee_buy = filled_buy * vwap_buy * fee_buy_rate

        # --- Filtro PRE-TRADE de slippage (Apéndice D.3) — sólo bajo modelo de latencia ---
        # En vivo el evaluador (C6) ya filtró el slippage pre-trade sobre los MISMOS libros;
        # este gate hace al simulador autónomo cuando se modela la latencia (backtest/tests).
        # Se evalúa sobre los libros PRE-latencia (lo conocido al decidir enviar la orden).
        # Sin él (`latency_reread=False`) NO se toca el comportamiento STORY-009 existente.
        if latency_reread and filled_buy > _DUST:
            vwap_sell_pre, filled_sell_pre = walk_book(sell_book.bids, q_target)
            # El "top" para el slippage se toma del primer nivel OPERABLE (saneado), no del
            # best_bid/best_ask crudo (que puede ser un nivel fantasma que el fill ignora).
            if self._slippage_breached(
                vwap_buy, self._top_sane(buy_book.asks), is_buy=True
            ) or (
                filled_sell_pre > _DUST
                and self._slippage_breached(
                    vwap_sell_pre, self._top_sane(sell_book.bids), is_buy=False
                )
            ):
                opp.status = OpportunityStatus.discarded
                opp.discard_reason = DiscardReason.slippage_over_limit
                return None

        # --- 2) Latencia: re-lectura del leg2 (venta) en t+Δ y fill ---
        vwap_sell, filled_sell = walk_book(sell_eff.bids, q_target)

        matched = min(filled_buy, filled_sell)
        # VWAP del tramo REALMENTE casado: re-camina cada book exactamente hasta `matched`
        # (mejores niveles), no arrastra los profundos del excedente. matched==0 → VWAP 0.0.
        vwap_buy_matched, _ = walk_book(buy_book.asks, matched)
        vwap_sell_matched, _ = walk_book(sell_eff.bids, matched)

        # --- 3) Recompute de rentabilidad post-latencia (sólo bajo re-lectura t+Δ) ---
        # Si tras la latencia el tramo casado deja de ser rentable (neto < umbral) o el leg2
        # re-leído supera el slippage máximo, y YA tenemos leg1 comprado (filled_buy>0), se
        # hace UNWIND del leg1 (no se completa el leg2 a pérdida). Con filled_buy==0 no hay
        # posición que deshacer → cae al path normal (leg risk del lado que sí llenó).
        if latency_reread and filled_buy > _DUST:
            fee_buy_m = matched * vwap_buy_matched * fee_buy_rate
            fee_sell_m = matched * vwap_sell_matched * fee_sell_rate
            # Rebalanceo amortizado por trade: MISMA definición de neto que el evaluador C6
            # (gross − fees − rebalanceo), para que el gate de unwind use el mismo criterio
            # de rentabilidad que decidió la viabilidad original (no uno más laxo). Sólo se
            # incurre si se COMPLETA el trade (mueve inventario cross-venue); el unwind no.
            rebalance_amortized = (
                self._withdrawal_btc(opp.buy_venue) + self._withdrawal_btc(opp.sell_venue)
            ) * vwap_buy_matched
            net_matched = (
                (vwap_sell_matched - vwap_buy_matched) * matched
                - fee_buy_m
                - fee_sell_m
                - rebalance_amortized
            )
            slip2_breached = self._slippage_breached(
                vwap_sell, self._top_sane(sell_eff.bids), is_buy=False
            )
            if (
                matched <= _DUST
                or net_matched < self.settings.min_net_profit_usd
                or slip2_breached
            ):
                reason = (
                    DiscardReason.slippage_over_limit
                    if slip2_breached
                    else DiscardReason.not_profitable_fees
                )
                return self._unwind(
                    opp,
                    buy_book,
                    q_target=q_target,
                    vwap_buy=vwap_buy,
                    filled_buy=filled_buy,
                    fee_buy=fee_buy,
                    fee_buy_rate=fee_buy_rate,
                    reason=reason,
                    ts=ts_val,
                )

        # --- 4) PROCEED: ejecución de ambas patas (STORY-009, con el leg2 = sell_eff) ---
        fee_sell = filled_sell * vwap_sell * fee_sell_rate
        buy_leg = Leg(
            venue=opp.buy_venue, side=LegSide.buy,
            qty_filled=filled_buy, vwap=vwap_buy, fee=fee_buy,
            qty_requested=q_target,
        )
        sell_leg = Leg(
            venue=opp.sell_venue, side=LegSide.sell,
            qty_filled=filled_sell, vwap=vwap_sell, fee=fee_sell,
            qty_requested=q_target,
        )
        partial = buy_leg.partial or sell_leg.partial

        # --- LEG RISK: excedente del leg sobre-llenado (posición abierta) ---
        leg_risk_qty = abs(filled_buy - filled_sell)
        leg_risk_mtm = 0.0
        leg_risk_entry_vwap = 0.0
        leg_risk_venue: str | None = None
        leg_risk_side: LegSide | None = None
        if leg_risk_qty > _DUST:
            if filled_buy > filled_sell:
                # Compramos de más: LARGOS en el venue de compra. Mark al bid de ese venue.
                leg_risk_venue = opp.buy_venue
                leg_risk_side = LegSide.buy
                leg_risk_entry_vwap = self._excess_vwap(
                    vwap_buy, filled_buy, vwap_buy_matched, matched, leg_risk_qty
                )
                mark = self._sane_mark(buy_book.best_bid, vwap_buy)
            else:
                # Vendimos de más: CORTOS en el venue de venta. Mark al ask de ese venue.
                leg_risk_venue = opp.sell_venue
                leg_risk_side = LegSide.sell
                leg_risk_entry_vwap = self._excess_vwap(
                    vwap_sell, filled_sell, vwap_sell_matched, matched, leg_risk_qty
                )
                mark = self._sane_mark(sell_eff.best_ask, vwap_sell)
            leg_risk_mtm = leg_risk_qty * mark

        # --- P&L realizado: SÓLO el tramo casado (el excedente es leg risk abierto) ---
        fee_buy_matched = matched * vwap_buy_matched * fee_buy_rate
        fee_sell_matched = matched * vwap_sell_matched * fee_sell_rate
        realized_pnl = (
            (vwap_sell_matched - vwap_buy_matched) * matched
            - fee_buy_matched
            - fee_sell_matched
        )

        execution = Execution(
            id=f"exec-{opp.id}",
            opportunity_id=opp.id,
            legs=[buy_leg, sell_leg],
            matched_qty=matched,
            partial=partial,
            unwound=False,
            realized_pnl=realized_pnl,
            leg_risk_qty=leg_risk_qty,
            leg_risk_mtm=leg_risk_mtm,
            leg_risk_entry_vwap=leg_risk_entry_vwap,
            leg_risk_venue=leg_risk_venue,
            leg_risk_side=leg_risk_side,
            exec_latency_ms=self.settings.exec_latency_ms,
            status=OpportunityStatus.captured,
            ts=ts_val,
        )
        opp.status = OpportunityStatus.captured
        return execution

    def _unwind(
        self,
        opp: Opportunity,
        buy_book: NormalizedBook,
        *,
        q_target: float,
        vwap_buy: float,
        filled_buy: float,
        fee_buy: float,
        fee_buy_rate: float,
        reason: DiscardReason,
        ts: float,
    ) -> Execution:
        """Deshace el leg1 ya comprado: vende `filled_buy` de vuelta a mercado en el venue de
        COMPRA recorriendo sus `bids`. `realized_pnl` = pérdida del unwind (proceeds − coste
        de compra − ambas fees, prorrateadas a la porción realmente deshecha). Si los bids no
        tienen profundidad para todo `filled_buy`, el RESIDUAL queda como leg risk LARGO
        abierto en el venue de compra (coste base = `vwap_buy`), marcado a mercado. El leg2
        (venta cruzada) NO se ejecuta. `matched_qty=0`; `unwound=True`; estado `captured`
        (la oportunidad SÍ se operó —y se cerró a pérdida—, no es un descarte pre-trade)."""
        vwap_unwind, qty_unwound = walk_book(buy_book.bids, filled_buy)
        fee_unwind = qty_unwound * vwap_unwind * fee_buy_rate
        # Fee de compra atribuible a la porción deshecha (el resto pertenece al residual).
        fee_buy_unwound = fee_buy * (qty_unwound / filled_buy) if filled_buy > 0.0 else 0.0
        realized_pnl = (
            (vwap_unwind - vwap_buy) * qty_unwound - fee_buy_unwound - fee_unwind
        )

        buy_leg = Leg(
            venue=opp.buy_venue, side=LegSide.buy,
            qty_filled=filled_buy, vwap=vwap_buy, fee=fee_buy,
            qty_requested=q_target,
        )
        unwind_leg = Leg(
            venue=opp.buy_venue, side=LegSide.sell,
            qty_filled=qty_unwound, vwap=vwap_unwind, fee=fee_unwind,
            qty_requested=filled_buy,
        )

        # Residual no deshecho (bids finos): posición LARGA abierta en el venue de compra.
        residual = filled_buy - qty_unwound
        leg_risk_qty = 0.0
        leg_risk_mtm = 0.0
        leg_risk_entry_vwap = 0.0
        leg_risk_venue: str | None = None
        leg_risk_side: LegSide | None = None
        if residual > _DUST:
            leg_risk_qty = residual
            leg_risk_venue = opp.buy_venue
            leg_risk_side = LegSide.buy
            # Coste base = VWAP de compra (precio puro, sin capitalizar la fee de compra de
            # la porción residual). MISMO criterio que el leg risk del path normal (C9): la
            # fee del excedente NO se capitaliza en el coste base, se realiza al cerrar la
            # posición. Esto deja un desfase transitorio `delta_equity vs total_pnl` del orden
            # de `fee_buy·residual/filled_buy` en el unrealized de la posición abierta (se
            # autocorrige al cerrarla). Es comportamiento PRE-EXISTENTE de STORY-009/010; su
            # corrección (capitalizar la fee en el coste base de TODO leg risk) es hardening
            # transversal fuera del alcance de STORY-016.
            leg_risk_entry_vwap = vwap_buy
            mark = self._sane_mark(buy_book.best_bid, vwap_buy)
            leg_risk_mtm = residual * mark

        execution = Execution(
            id=f"exec-{opp.id}",
            opportunity_id=opp.id,
            legs=[buy_leg, unwind_leg],
            matched_qty=0.0,
            partial=buy_leg.partial or residual > _DUST,
            unwound=True,
            unwind_reason=reason,
            realized_pnl=realized_pnl,
            leg_risk_qty=leg_risk_qty,
            leg_risk_mtm=leg_risk_mtm,
            leg_risk_entry_vwap=leg_risk_entry_vwap,
            leg_risk_venue=leg_risk_venue,
            leg_risk_side=leg_risk_side,
            exec_latency_ms=self.settings.exec_latency_ms,
            status=OpportunityStatus.captured,
            ts=ts,
        )
        opp.status = OpportunityStatus.captured
        return execution
