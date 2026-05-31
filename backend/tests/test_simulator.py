"""C9 — simulador de ejecución TAKER con fills parciales y leg risk (FR-008/009, STORY-009).

Determinista: libros sintéticos, sin red ni reloj para los asserts numéricos.
"""
from __future__ import annotations

import pytest

from app.config import ExchangeConfig, Settings
from app.models.enums import DiscardReason, LegSide, OpportunityStatus, Strategy
from app.models.market import NormalizedBook
from app.models.opportunity import Opportunity
from app.sim import ExecutionSimulator


def _book(ex: str, bids, asks) -> NormalizedBook:
    return NormalizedBook(
        exchange=ex, symbol="BTC/USD", quote_ccy="USD",
        bids=bids, asks=asks, price_norm_factor=1.0, ts_recv_monotonic=0.0,
    )


def _settings(**over) -> Settings:
    base = dict(
        default_trade_qty_btc=1.0,
        exec_latency_ms=150,
        exchanges={
            "binance": ExchangeConfig(
                id="binance", symbol="BTC/USDT", quote_ccy="USDT",
                fee_taker=0.0010, withdrawal_btc=0.0002, ob_limit=20,
            ),
            "kraken": ExchangeConfig(
                id="kraken", symbol="BTC/USD", quote_ccy="USD",
                fee_taker=0.0040, withdrawal_btc=0.00005, ob_limit=25,
            ),
        },
    )
    base.update(over)
    return Settings(**base)


def _viable(buy="binance", sell="kraken", q=1.0, vb=100.0, vs=110.0) -> Opportunity:
    return Opportunity(
        id="opp-1", strategy=Strategy.spatial, symbol="BTC/USD",
        buy_venue=buy, sell_venue=sell, q_target=q,
        vwap_buy=vb, vwap_sell=vs, status=OpportunityStatus.viable,
    )


def test_full_fill_realized_pnl_and_captured():
    """Ambos legs llenan q_target completo: P&L neto del tramo casado, sin leg risk."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)])
    opp = _viable()
    ex = sim.simulate(opp, buy, sell, ts=1.0)

    q = 1.0
    fees = q * 100.0 * 0.0010 + q * 110.0 * 0.0040     # 0.10 + 0.44 = 0.54
    pnl = (110.0 - 100.0) * q - fees                   # 9.46

    assert ex.matched_qty == pytest.approx(1.0)
    assert ex.partial is False
    assert ex.leg_risk_qty == pytest.approx(0.0)
    assert ex.leg_risk_mtm == pytest.approx(0.0)
    assert ex.realized_pnl == pytest.approx(pnl)
    assert ex.status == OpportunityStatus.captured
    assert opp.status == OpportunityStatus.captured       # muta la oportunidad
    assert len(ex.legs) == 2
    buy_leg = next(lg for lg in ex.legs if lg.side == LegSide.buy)
    sell_leg = next(lg for lg in ex.legs if lg.side == LegSide.sell)
    assert buy_leg.venue == "binance" and buy_leg.vwap == pytest.approx(100.0)
    assert sell_leg.venue == "kraken" and sell_leg.vwap == pytest.approx(110.0)
    assert ex.exec_latency_ms == 150                      # latencia simulada registrada


def test_vwap_walks_levels_on_each_leg():
    """El simulador recorre niveles (taker): VWAP de los niveles consumidos."""
    s = _settings()
    sim = ExecutionSimulator(s)
    # compra 0.5@100 + 0.5@102 → vwap 101 ; venta 0.5@120 + 0.5@118 → vwap 119
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 0.5), (102.0, 0.5)])
    sell = _book("kraken", bids=[(120.0, 0.5), (118.0, 0.5)], asks=[(121, 5)])
    ex = sim.simulate(_viable(vb=101.0, vs=119.0), buy, sell, ts=1.0)
    buy_leg = next(lg for lg in ex.legs if lg.side == LegSide.buy)
    sell_leg = next(lg for lg in ex.legs if lg.side == LegSide.sell)
    assert buy_leg.vwap == pytest.approx(101.0)
    assert sell_leg.vwap == pytest.approx(119.0)
    assert ex.matched_qty == pytest.approx(1.0)
    assert ex.partial is False


def test_partial_fill_marks_partial_and_matches_min():
    """Profundidad de venta < q_target → fill parcial; matched = min(buy, sell)."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)])     # 5 BTC dispo.
    sell = _book("kraken", bids=[(110.0, 0.4)], asks=[(111, 5)])    # sólo 0.4 BTC
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)

    assert ex.matched_qty == pytest.approx(0.4)
    assert ex.partial is True
    # Excedente de compra = 1.0 - 0.4 = 0.6 BTC como leg risk (largos en binance).
    assert ex.leg_risk_qty == pytest.approx(0.6)
    assert ex.leg_risk_venue == "binance"
    assert ex.leg_risk_side == LegSide.buy
    # MTM del excedente al mejor bid del venue de compra (99) — lo que pagan al vender.
    assert ex.leg_risk_mtm == pytest.approx(0.6 * 99.0)
    # P&L realizado SÓLO sobre 0.4 casado.
    fees = 0.4 * 100.0 * 0.0010 + 0.4 * 110.0 * 0.0040
    assert ex.realized_pnl == pytest.approx((110.0 - 100.0) * 0.4 - fees)


def test_leg_risk_short_side_marks_to_ask():
    """Si vendemos de más (venta más profunda), quedamos cortos: MTM al ASK del venue
    de venta (lo que costaría recomprar)."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 0.3)])     # sólo 0.3 BTC
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5)])  # 5 BTC
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)

    assert ex.matched_qty == pytest.approx(0.3)
    assert ex.leg_risk_qty == pytest.approx(0.7)
    assert ex.leg_risk_venue == "kraken"
    assert ex.leg_risk_side == LegSide.sell
    assert ex.leg_risk_mtm == pytest.approx(0.7 * 111.0)  # ask del venue de venta


def test_fee_per_leg_uses_each_venue_taker():
    """Fee única taker por leg con el fee_taker del venue (nunca doble)."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)
    buy_leg = next(lg for lg in ex.legs if lg.side == LegSide.buy)
    sell_leg = next(lg for lg in ex.legs if lg.side == LegSide.sell)
    assert buy_leg.fee == pytest.approx(1.0 * 100.0 * 0.0010)   # binance 0.10%
    assert sell_leg.fee == pytest.approx(1.0 * 110.0 * 0.0040)  # kraken 0.40%


def test_deterministic_no_clock_dependency():
    """Misma entrada → mismo Execution (salvo `ts` explícito). Determinismo."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)])
    a = sim.simulate(_viable(), buy, sell, ts=1.0)
    b = sim.simulate(_viable(), buy, sell, ts=1.0)
    assert a.model_dump() == b.model_dump()


def test_latency_from_config():
    """exec_latency_ms se toma de config (Apéndice D.3) y se registra en el Execution."""
    s = _settings(exec_latency_ms=200)
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)
    assert ex.exec_latency_ms == 200
    assert ex.unwound is False   # unwind es STORY-016: aquí nunca se deshace


def test_walk_book_shared_util_still_importable_from_evaluator():
    """El util compartido sigue accesible (retrocompatibilidad con C6 y sus tests)."""
    from app.engine.evaluator import _walk_book, walk_book

    assert walk_book is _walk_book
    vwap, filled = walk_book([(100.0, 0.5), (102.0, 0.5)], 1.0)
    assert filled == pytest.approx(1.0)
    assert vwap == pytest.approx(101.0)


def test_buy_leg_no_liquidity_empty_asks():
    """Venue de compra SIN asks → no se puede comprar: matched=0, todo el fill de venta
    queda como leg risk CORTO (vendimos de más). P&L del tramo casado = 0."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[])              # sin liquidez de compra
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)])
    opp = _viable()
    ex = sim.simulate(opp, buy, sell, ts=1.0)

    buy_leg = next(lg for lg in ex.legs if lg.side == LegSide.buy)
    sell_leg = next(lg for lg in ex.legs if lg.side == LegSide.sell)
    assert buy_leg.qty_filled == pytest.approx(0.0)
    assert buy_leg.vwap == pytest.approx(0.0)   # walk_book vacío → vwap 0.0
    assert buy_leg.fee == pytest.approx(0.0)     # nada llenado → fee 0
    assert sell_leg.qty_filled == pytest.approx(1.0)
    assert ex.matched_qty == pytest.approx(0.0)
    assert ex.partial is True                    # buy leg quedó 0 < q_target
    # Vendimos 1.0 sin contraparte de compra → cortos en kraken, MTM al ask de venta.
    assert ex.leg_risk_qty == pytest.approx(1.0)
    assert ex.leg_risk_venue == "kraken"
    assert ex.leg_risk_side == LegSide.sell
    assert ex.leg_risk_mtm == pytest.approx(1.0 * 111.0)
    assert ex.realized_pnl == pytest.approx(0.0)  # sin tramo casado, no realiza P&L
    assert ex.status == OpportunityStatus.captured
    assert opp.status == OpportunityStatus.captured


def test_sell_leg_no_liquidity_empty_bids():
    """Venue de venta SIN bids → no se puede vender: matched=0, todo el fill de compra
    queda como leg risk LARGO (compramos de más). P&L del tramo casado = 0."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[], asks=[(111.0, 5.0)])            # sin liquidez de venta
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)

    buy_leg = next(lg for lg in ex.legs if lg.side == LegSide.buy)
    sell_leg = next(lg for lg in ex.legs if lg.side == LegSide.sell)
    assert buy_leg.qty_filled == pytest.approx(1.0)
    assert sell_leg.qty_filled == pytest.approx(0.0)
    assert sell_leg.vwap == pytest.approx(0.0)
    assert ex.matched_qty == pytest.approx(0.0)
    assert ex.partial is True
    # Compramos 1.0 sin contraparte de venta → largos en binance, MTM al bid de compra.
    assert ex.leg_risk_qty == pytest.approx(1.0)
    assert ex.leg_risk_venue == "binance"
    assert ex.leg_risk_side == LegSide.buy
    assert ex.leg_risk_mtm == pytest.approx(1.0 * 99.0)
    assert ex.realized_pnl == pytest.approx(0.0)


def test_partial_populates_leg_fields_qty_requested_and_partial_flag():
    """En un fill parcial, cada Leg expone qty_requested, qty_filled, vwap, fee y su
    flag `partial` correctos (campos poblados para STORY-010/016)."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])   # llena completo
    sell = _book("kraken", bids=[(110.0, 0.4)], asks=[(111.0, 5.0)])  # sólo 0.4
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)

    buy_leg = next(lg for lg in ex.legs if lg.side == LegSide.buy)
    sell_leg = next(lg for lg in ex.legs if lg.side == LegSide.sell)
    # buy leg: lleno completo, no parcial
    assert buy_leg.qty_requested == pytest.approx(1.0)
    assert buy_leg.qty_filled == pytest.approx(1.0)
    assert buy_leg.partial is False
    assert buy_leg.fee == pytest.approx(1.0 * 100.0 * 0.0010)
    # sell leg: parcial (sólo 0.4), fee sobre lo realmente llenado
    assert sell_leg.qty_requested == pytest.approx(1.0)
    assert sell_leg.qty_filled == pytest.approx(0.4)
    assert sell_leg.partial is True
    assert sell_leg.fee == pytest.approx(0.4 * 110.0 * 0.0040)
    assert ex.partial is True


def test_matched_pnl_uses_matched_vwap_not_full_fill_vwap_buy_overfilled():
    """Leg de COMPRA sobre-llenado consumiendo >=2 niveles: el tramo casado debe valorarse
    a los MEJORES niveles (cheapest-first), NO al VWAP del fill completo (que promedia
    niveles profundos del excedente). Fija la atribución de coste matched vs leg risk."""
    # fees=0 para aislar el efecto del VWAP.
    s = _settings(
        exchanges={
            "binance": ExchangeConfig(
                id="binance", symbol="BTC/USDT", quote_ccy="USDT",
                fee_taker=0.0, withdrawal_btc=0.0, ob_limit=20,
            ),
            "kraken": ExchangeConfig(
                id="kraken", symbol="BTC/USD", quote_ccy="USD",
                fee_taker=0.0, withdrawal_btc=0.0, ob_limit=25,
            ),
        },
    )
    sim = ExecutionSimulator(s)
    # buy llena 1.0 = 0.5@100 + 0.5@200 (vwap_full=150); sell sólo 0.5@300; matched=0.5.
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 0.5), (200.0, 0.5)])
    sell = _book("kraken", bids=[(300.0, 0.5)], asks=[(301, 5)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)

    assert ex.matched_qty == pytest.approx(0.5)
    assert ex.leg_risk_qty == pytest.approx(0.5)
    assert ex.leg_risk_venue == "binance"
    assert ex.leg_risk_side == LegSide.buy
    # Los 0.5 casados se compraron SÓLO contra el nivel @100 → (300-100)*0.5 = 100.0
    # (NO el bug de VWAP completo 150 → (300-150)*0.5 = 75.0).
    assert ex.realized_pnl == pytest.approx((300.0 - 100.0) * 0.5)
    # El Leg de compra conserva el VWAP del fill COMPLETO (informativo).
    buy_leg = next(lg for lg in ex.legs if lg.side == LegSide.buy)
    assert buy_leg.vwap == pytest.approx(150.0)
    # Coste base del excedente = nivel profundo @200 (la franja [0.5, 1.0]).
    assert ex.leg_risk_entry_vwap == pytest.approx(200.0)


def test_matched_pnl_uses_matched_vwap_sell_overfilled():
    """Simétrico: leg de VENTA sobre-llenado con >=2 niveles. El tramo casado se vende a
    los MEJORES bids (best-first), no al VWAP del fill completo de la venta."""
    s = _settings(
        exchanges={
            "binance": ExchangeConfig(
                id="binance", symbol="BTC/USDT", quote_ccy="USDT",
                fee_taker=0.0, withdrawal_btc=0.0, ob_limit=20,
            ),
            "kraken": ExchangeConfig(
                id="kraken", symbol="BTC/USD", quote_ccy="USD",
                fee_taker=0.0, withdrawal_btc=0.0, ob_limit=25,
            ),
        },
    )
    sim = ExecutionSimulator(s)
    # buy sólo 0.4@100; sell llena 1.0 = 0.4@300 + 0.6@110 (vwap_full=186); matched=0.4.
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 0.4)])
    sell = _book("kraken", bids=[(300.0, 0.4), (110.0, 0.6)], asks=[(301, 5)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)

    assert ex.matched_qty == pytest.approx(0.4)
    assert ex.leg_risk_qty == pytest.approx(0.6)
    assert ex.leg_risk_venue == "kraken"
    assert ex.leg_risk_side == LegSide.sell
    # 0.4 casados vendidos al mejor bid @300 → (300-100)*0.4 = 80.0 (no 186 del fill full).
    assert ex.realized_pnl == pytest.approx((300.0 - 100.0) * 0.4)
    sell_leg = next(lg for lg in ex.legs if lg.side == LegSide.sell)
    assert sell_leg.vwap == pytest.approx(186.0)
    # Coste base del excedente vendido de más = nivel profundo @110 (franja [0.4, 1.0]).
    assert ex.leg_risk_entry_vwap == pytest.approx(110.0)


def test_matched_pnl_fee_uses_matched_vwap():
    """Las fees del tramo casado se cobran sobre el VWAP del matched, no del fill completo."""
    s = _settings()  # binance 0.10%, kraken 0.40%
    sim = ExecutionSimulator(s)
    # buy 1.0 = 0.5@100 + 0.5@200 (full 150), sell 0.5@300 → matched 0.5 al @100.
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 0.5), (200.0, 0.5)])
    sell = _book("kraken", bids=[(300.0, 0.5)], asks=[(301, 5)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)
    # fees sobre VWAP matched: 0.5*100*0.0010 (buy) + 0.5*300*0.0040 (sell)
    fee_buy = 0.5 * 100.0 * 0.0010
    fee_sell = 0.5 * 300.0 * 0.0040
    assert ex.realized_pnl == pytest.approx((300.0 - 100.0) * 0.5 - fee_buy - fee_sell)


def test_leg_risk_mtm_finite_when_top_of_book_corrupt():
    """Top-of-book NaN/inf en el leg sobre-llenado NO debe propagar un MTM no finito: se
    cae al VWAP recorrido del leg (finito), igual que walk_book filtra niveles corruptos."""
    s = _settings()
    sim = ExecutionSimulator(s)
    # buy: best_bid NaN, pero asks llenan 1.0 → largos 0.6; mark debe sanearse.
    buy = _book("binance", bids=[(float("nan"), 5.0)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[(110.0, 0.4)], asks=[(111.0, 5.0)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)
    assert ex.leg_risk_venue == "binance"
    assert ex.leg_risk_side == LegSide.buy
    import math as _m
    assert _m.isfinite(ex.leg_risk_mtm)
    # Fallback al VWAP de compra (100.0), finito y > 0.
    assert ex.leg_risk_mtm == pytest.approx(0.6 * 100.0)


def test_full_fill_no_leg_risk_fields_none():
    """Fill completo simétrico → sin leg risk: qty/mtm en 0 y venue/side None."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)
    assert ex.leg_risk_qty == pytest.approx(0.0)
    assert ex.leg_risk_mtm == pytest.approx(0.0)
    assert ex.leg_risk_entry_vwap == pytest.approx(0.0)
    assert ex.leg_risk_venue is None
    assert ex.leg_risk_side is None
    assert ex.unwound is False


def test_excess_vwap_falls_back_to_full_when_excess_nonpositive():
    """`_excess_vwap` con `excess_qty <= 0` (sin excedente real) cae al VWAP completo
    (conservador), en vez de dividir por ~0. Rama 83-84."""
    # Sin excedente (excess_qty=0) → devuelve vwap_full tal cual.
    assert ExecutionSimulator._excess_vwap(
        vwap_full=150.0, filled=1.0, vwap_matched=100.0, matched=1.0, excess_qty=0.0
    ) == pytest.approx(150.0)
    # Con excedente real, deriva el coste por balance: (150·1 - 100·0.5)/0.5 = 200.
    assert ExecutionSimulator._excess_vwap(
        vwap_full=150.0, filled=1.0, vwap_matched=100.0, matched=0.5, excess_qty=0.5
    ) == pytest.approx(200.0)


# ===========================================================================================
# STORY-016 — Modelo secuencial con latencia: re-lectura del leg2 (t+Δ), recompute y unwind.
# El comportamiento STORY-009 (sin `sell_book_t1`) queda intacto: estos tests SIEMPRE pasan
# `sell_book_t1` para ejercitar la latencia. Deterministas: libros sintéticos, sin reloj.
# ===========================================================================================


def test_latency_reread_spread_holds_proceeds_no_unwind():
    """Re-lectura t+Δ con el spread aún favorable → procede (fill ambas patas), sin unwind.
    El leg2 se rellena contra `sell_book_t1`, no contra el snapshot inicial."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])
    sell_t0 = _book("kraken", bids=[(130.0, 5.0)], asks=[(131.0, 5.0)])
    # t+Δ: el bid bajó a 120 pero SIGUE rentable (120 > 100 + fees).
    sell_t1 = _book("kraken", bids=[(120.0, 5.0)], asks=[(121.0, 5.0)])
    ex = sim.simulate(_viable(), buy, sell_t0, sell_book_t1=sell_t1, ts=1.0)
    assert ex is not None
    assert ex.unwound is False
    assert ex.unwind_reason is None
    assert ex.matched_qty == pytest.approx(1.0)
    sell_leg = next(lg for lg in ex.legs if lg.side == LegSide.sell)
    # El leg2 usó el book t+Δ (120), no el inicial (130).
    assert sell_leg.vwap == pytest.approx(120.0)
    fee_buy = 1.0 * 100.0 * 0.0010
    fee_sell = 1.0 * 120.0 * 0.0040
    assert ex.realized_pnl == pytest.approx((120.0 - 100.0) * 1.0 - fee_buy - fee_sell)


def test_latency_reread_spread_collapses_unwinds_leg1():
    """El spread se evapora tras la latencia (bid t+Δ < ask de compra) → no rentable →
    UNWIND del leg1 a mercado (vender lo comprado en el venue de compra). Pérdida registrada,
    matched=0, unwound=True, motivo not_profitable_fees."""
    s = _settings()  # binance 0.10%, kraken 0.40%, min_net_profit_usd=0.0
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])
    sell_t0 = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)])
    # t+Δ: el bid se desploma a 99.5 → (99.5-100) negativo, no rentable.
    sell_t1 = _book("kraken", bids=[(99.5, 5.0)], asks=[(100.5, 5.0)])
    opp = _viable()
    ex = sim.simulate(opp, buy, sell_t0, sell_book_t1=sell_t1, ts=1.0)
    assert ex is not None
    assert ex.unwound is True
    assert ex.unwind_reason == DiscardReason.not_profitable_fees
    assert ex.matched_qty == pytest.approx(0.0)
    assert opp.status == OpportunityStatus.captured  # se operó (y se cerró a pérdida)
    # Unwind: compró 1.0@100 (fee 0.1), vendió de vuelta 1.0@99 (bid del venue de compra,
    # fee 0.099). realized = (99-100)*1 - 0.1 - 0.099.
    fee_buy = 1.0 * 100.0 * 0.0010
    fee_unwind = 1.0 * 99.0 * 0.0010
    assert ex.realized_pnl == pytest.approx((99.0 - 100.0) * 1.0 - fee_buy - fee_unwind)
    assert ex.realized_pnl < 0.0
    # Unwind total (bids con profundidad) → sin leg risk residual.
    assert ex.leg_risk_qty == pytest.approx(0.0)
    # Las dos patas son del MISMO venue de compra (compra + venta de unwind).
    assert {lg.venue for lg in ex.legs} == {"binance"}
    sides = sorted(lg.side for lg in ex.legs)
    assert sides == [LegSide.buy, LegSide.sell]


def test_unwind_below_min_net_profit_threshold():
    """Aunque el spread siga POSITIVO, si el neto recomputado cae por debajo de
    `min_net_profit_usd` se hace unwind (umbral de rentabilidad, no signo)."""
    s = _settings(min_net_profit_usd=50.0)  # umbral alto
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])
    sell_t0 = _book("kraken", bids=[(200.0, 5.0)], asks=[(201.0, 5.0)])
    # t+Δ: bid 110 → net = (110-100)*1 - fees ≈ 9.46 < 50 → unwind.
    sell_t1 = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)])
    ex = sim.simulate(_viable(), buy, sell_t0, sell_book_t1=sell_t1, ts=1.0)
    assert ex is not None
    assert ex.unwound is True
    assert ex.unwind_reason == DiscardReason.not_profitable_fees


def test_pretrade_slippage_gate_discards_returns_none():
    """Filtro PRE-TRADE: si el slippage del leg1 (walk vs top-of-book) supera max_slippage,
    no se opera → devuelve None y marca la oportunidad como discarded(slippage_over_limit)."""
    s = _settings(max_slippage=0.0010)
    sim = ExecutionSimulator(s)
    # buy: top @100 con 0.01 BTC, resto @200 → vwap_buy≈199 para q=1.0, slip≈99% > 0.10%.
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 0.01), (200.0, 5.0)])
    sell_t0 = _book("kraken", bids=[(300.0, 5.0)], asks=[(301.0, 5.0)])
    sell_t1 = _book("kraken", bids=[(300.0, 5.0)], asks=[(301.0, 5.0)])
    opp = _viable()
    ex = sim.simulate(opp, buy, sell_t0, sell_book_t1=sell_t1, ts=1.0)
    assert ex is None
    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.slippage_over_limit


def test_leg2_slippage_after_latency_triggers_unwind():
    """Si el book t+Δ del leg2 tiene un slippage que supera max_slippage (top fino sobre
    liquidez profunda), se hace unwind con motivo slippage_over_limit (independiente del
    signo del neto)."""
    s = _settings(max_slippage=0.0010)
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])
    sell_t0 = _book("kraken", bids=[(130.0, 5.0)], asks=[(131.0, 5.0)])  # limpio pre-trade
    # t+Δ: best_bid 130 con 0.01, resto @128 → vwap_sell≈128.02, slip≈1.5% > 0.10%.
    sell_t1 = _book("kraken", bids=[(130.0, 0.01), (128.0, 5.0)], asks=[(131.0, 5.0)])
    ex = sim.simulate(_viable(), buy, sell_t0, sell_book_t1=sell_t1, ts=1.0)
    assert ex is not None
    assert ex.unwound is True
    assert ex.unwind_reason == DiscardReason.slippage_over_limit


def test_partial_unwind_leaves_residual_leg_risk():
    """Si los bids del venue de compra no tienen profundidad para deshacer todo el leg1, el
    residual queda como leg risk LARGO abierto (coste base = vwap_buy), marcado a mercado."""
    s = _settings()
    sim = ExecutionSimulator(s)
    # buy llena 1.0@100, pero sólo hay 0.3 de bid @99 para deshacer → residual 0.7 largo.
    buy = _book("binance", bids=[(99.0, 0.3)], asks=[(100.0, 5.0)])
    sell_t0 = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)])
    sell_t1 = _book("kraken", bids=[(99.5, 5.0)], asks=[(100.5, 5.0)])  # colapso → unwind
    ex = sim.simulate(_viable(), buy, sell_t0, sell_book_t1=sell_t1, ts=1.0)
    assert ex is not None
    assert ex.unwound is True
    assert ex.leg_risk_qty == pytest.approx(0.7)
    assert ex.leg_risk_venue == "binance"
    assert ex.leg_risk_side == LegSide.buy
    assert ex.leg_risk_entry_vwap == pytest.approx(100.0)
    assert ex.leg_risk_mtm == pytest.approx(0.7 * 99.0)  # marcado al bid del venue de compra
    # realized sólo de la porción deshecha (0.3): (99-100)*0.3 - fee_buy_porción - fee_unwind.
    fee_buy_full = 1.0 * 100.0 * 0.0010
    fee_buy_unwound = fee_buy_full * (0.3 / 1.0)
    fee_unwind = 0.3 * 99.0 * 0.0010
    assert ex.realized_pnl == pytest.approx(
        (99.0 - 100.0) * 0.3 - fee_buy_unwound - fee_unwind
    )


def test_no_unwind_when_buy_leg_empty_even_with_latency():
    """Con el leg1 (compra) sin liquidez (filled_buy=0) NO hay posición que deshacer: cae al
    path normal y produce leg risk CORTO del lado de venta (como STORY-009), no un unwind."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[])  # sin asks → no compra
    sell_t0 = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)])
    sell_t1 = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)])
    ex = sim.simulate(_viable(), buy, sell_t0, sell_book_t1=sell_t1, ts=1.0)
    assert ex is not None
    assert ex.unwound is False
    assert ex.matched_qty == pytest.approx(0.0)
    assert ex.leg_risk_qty == pytest.approx(1.0)
    assert ex.leg_risk_side == LegSide.sell
    assert ex.leg_risk_venue == "kraken"


def test_sell_book_t1_none_matches_story009_no_unwind():
    """Sin `sell_book_t1` (None) NO se modela deriva: comportamiento STORY-009 exacto, sin
    gate de slippage extra ni unwind, aunque el spread sea ajustado."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)  # t1 omitido
    assert ex is not None
    assert ex.unwound is False
    assert ex.unwind_reason is None
    assert ex.matched_qty == pytest.approx(1.0)


def test_latency_unwind_deterministic_no_clock():
    """El unwind es 100% determinista: dos simulaciones con los mismos libros dan idéntico
    `Execution` (sin depender de `time.monotonic()`)."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])
    sell_t0 = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)])
    sell_t1 = _book("kraken", bids=[(99.5, 5.0)], asks=[(100.5, 5.0)])
    a = sim.simulate(_viable(), buy, sell_t0, sell_book_t1=sell_t1, ts=1.0)
    b = sim.simulate(_viable(), buy, sell_t0, sell_book_t1=sell_t1, ts=1.0)
    assert a is not None and b is not None
    assert a.realized_pnl == pytest.approx(b.realized_pnl)
    assert a.unwound == b.unwound and a.unwind_reason == b.unwind_reason


def test_pretrade_gate_leg2_slippage_branch_discards():
    """Rama del gate pre-trade por slippage del LEG2 (venta) sobre el book pre-latencia:
    leg1 limpio, pero el book de venta inicial tiene un top fino sobre liquidez profunda →
    slippage del leg2 > max_slippage → discard(slippage_over_limit), devuelve None."""
    s = _settings(max_slippage=0.0010)
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])  # leg1 sin slippage
    # sell pre-latencia: best_bid 130 con 0.01, resto @100 → vwap≈100.3, slip≈22.8% > 0.10%.
    sell_t0 = _book("kraken", bids=[(130.0, 0.01), (100.0, 5.0)], asks=[(131.0, 5.0)])
    sell_t1 = _book("kraken", bids=[(130.0, 5.0)], asks=[(131.0, 5.0)])
    opp = _viable()
    ex = sim.simulate(opp, buy, sell_t0, sell_book_t1=sell_t1, ts=1.0)
    assert ex is None
    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.slippage_over_limit


def test_matched_zero_via_empty_sell_t1_unwinds():
    """Leg1 comprado pero el leg2 re-leído se queda SIN liquidez (bids vacíos en t+Δ):
    matched=0 con filled_buy>0 → unwind del leg1 (no queda nada que casar)."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])
    sell_t0 = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)])
    sell_t1 = _book("kraken", bids=[], asks=[(111.0, 5.0)])  # sin bids en t+Δ
    ex = sim.simulate(_viable(), buy, sell_t0, sell_book_t1=sell_t1, ts=1.0)
    assert ex is not None
    assert ex.unwound is True
    assert ex.matched_qty == pytest.approx(0.0)
    # Unwind total contra los bids del venue de compra (99) → pérdida = spread + fees.
    assert ex.realized_pnl < 0.0
    assert ex.leg_risk_qty == pytest.approx(0.0)


def test_phantom_top_level_does_not_spuriously_discard():
    """El gate de slippage mide contra el primer nivel OPERABLE (saneado), no el best_ask
    crudo: un nivel-top fantasma (qty=0, delta de remoción) que el fill IGNORA no debe
    disparar un descarte espurio. Sin el saneo, best_ask=50 daría slip 100% y descartaría."""
    s = _settings(max_slippage=0.0010)
    sim = ExecutionSimulator(s)
    # Top fantasma @50 con qty 0 (walk_book lo salta); liquidez real @100.
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(50.0, 0.0), (100.0, 5.0)])
    sell_t0 = _book("kraken", bids=[(130.0, 5.0)], asks=[(131.0, 5.0)])
    sell_t1 = _book("kraken", bids=[(130.0, 5.0)], asks=[(131.0, 5.0)])
    ex = sim.simulate(_viable(), buy, sell_t0, sell_book_t1=sell_t1, ts=1.0)
    assert ex is not None  # NO descartada: el fill llenó a 100 sin slippage real
    assert ex.unwound is False
    buy_leg = next(lg for lg in ex.legs if lg.side == LegSide.buy)
    assert buy_leg.vwap == pytest.approx(100.0)  # llenó al nivel real, no al fantasma


def test_rebalance_amortized_affects_unwind_decision():
    """El recompute del gate usa la MISMA definición de neto que el evaluador (incluye el
    rebalanceo amortizado): un trama marginalmente positivo ANTES del rebalanceo puede caer
    bajo el umbral por el coste de rebalanceo → unwind. Sin rebalanceo, el mismo trade pasa."""
    # Spread fino: gross=(100.6-100)*1=0.6; fees=0.1+0.4024=0.5024; net pre-rebal≈0.0976>0.
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])
    sell_t0 = _book("kraken", bids=[(200.0, 5.0)], asks=[(201.0, 5.0)])
    sell_t1 = _book("kraken", bids=[(100.6, 5.0)], asks=[(101.0, 5.0)])

    # (a) Rebalanceo alto (withdrawal_btc grande) → rebalance≈0.1056 > 0.0976 → unwind.
    s_high = _settings(
        exchanges={
            "binance": ExchangeConfig(
                id="binance", symbol="BTC/USDT", quote_ccy="USDT",
                fee_taker=0.0010, withdrawal_btc=0.0010, ob_limit=20,
            ),
            "kraken": ExchangeConfig(
                id="kraken", symbol="BTC/USD", quote_ccy="USD",
                fee_taker=0.0040, withdrawal_btc=0.00005, ob_limit=25,
            ),
        },
    )
    ex_high = ExecutionSimulator(s_high).simulate(
        _viable(), buy, sell_t0, sell_book_t1=sell_t1, ts=1.0
    )
    assert ex_high is not None and ex_high.unwound is True

    # (b) Sin rebalanceo (withdrawal 0) → net 0.0976 > 0 → procede (no unwind).
    s_zero = _settings(
        exchanges={
            "binance": ExchangeConfig(
                id="binance", symbol="BTC/USDT", quote_ccy="USDT",
                fee_taker=0.0010, withdrawal_btc=0.0, ob_limit=20,
            ),
            "kraken": ExchangeConfig(
                id="kraken", symbol="BTC/USD", quote_ccy="USD",
                fee_taker=0.0040, withdrawal_btc=0.0, ob_limit=25,
            ),
        },
    )
    ex_zero = ExecutionSimulator(s_zero).simulate(
        _viable(), buy, sell_t0, sell_book_t1=sell_t1, ts=1.0
    )
    assert ex_zero is not None and ex_zero.unwound is False
