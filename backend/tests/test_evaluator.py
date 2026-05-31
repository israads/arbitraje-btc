"""C6 — evaluador de rentabilidad NETA (FR-005, STORY-008).

Determinista: libros sintéticos, sin red ni reloj para los asserts numéricos.
"""
from __future__ import annotations

import time

import pytest

from app.config import ExchangeConfig, Settings
from app.engine.detector import SpatialDetector
from app.engine.evaluator import NetEvaluator
from app.models.enums import DiscardReason, OpportunityStatus, Strategy
from app.models.market import NormalizedBook
from app.models.opportunity import Opportunity


def _book(ex: str, bids, asks, ts: float) -> NormalizedBook:
    return NormalizedBook(
        exchange=ex, symbol="BTC/USD", quote_ccy="USD",
        bids=bids, asks=asks, price_norm_factor=1.0, ts_recv_monotonic=ts,
    )


def _settings(**over) -> Settings:
    # Fees y withdrawal deterministas, conocidos en los asserts.
    base = dict(
        min_net_profit_usd=0.0,
        max_slippage=0.0010,
        default_trade_qty_btc=1.0,
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


def _detected(buy="binance", sell="kraken") -> Opportunity:
    return Opportunity(
        id="opp-1", strategy=Strategy.spatial, symbol="BTC/USD",
        buy_venue=buy, sell_venue=sell, q_target=1.0,
        status=OpportunityStatus.detected,
    )


def _usdt_book(ex: str, bids, asks, ts: float, *, factor: float = 1.0) -> NormalizedBook:
    """Book con quote USDT (precios ya en USD por el peg `factor`)."""
    return NormalizedBook(
        exchange=ex, symbol="BTC/USDT", quote_ccy="USDT",
        bids=bids, asks=asks, price_norm_factor=factor, ts_recv_monotonic=ts,
    )


# ---------------------------------------------------------------------------
# Gate peg_adverse (C3/FR-003): un leg con stable fuera de banda se descarta
# ANTES del walk-the-book; USD puro y stables en banda evalúan normal.
# ---------------------------------------------------------------------------

def _peg(usdt_rate: float):
    from app.normalize.peg import PegProvider
    p = PegProvider(target="USD", tolerance=0.005)
    p.update("USDT", usdt_rate, source="kraken", ts=0.0)
    return p


def test_peg_adverse_discards_when_usdt_depegged():
    t = time.monotonic()
    ev = NetEvaluator(_settings(max_slippage=1.0), peg=_peg(0.98))  # depeg 2% > 0.5%
    buy = _usdt_book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)], ts=t)
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)], ts=t)
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status is OpportunityStatus.discarded
    assert opp.discard_reason is DiscardReason.peg_adverse
    assert opp.net_pnl is None  # gate temprano: no se computó el neto


def test_peg_within_tolerance_evaluates_normally():
    t = time.monotonic()
    ev = NetEvaluator(_settings(max_slippage=1.0), peg=_peg(0.9997))  # dentro de banda
    buy = _usdt_book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)], ts=t)
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)], ts=t)
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status is OpportunityStatus.viable
    assert opp.discard_reason is None


def test_peg_adverse_ignores_usd_only_opps():
    """Aun con USDT roto, un cruce USD↔USD no se ve afectado (ningún leg usa la stable)."""
    t = time.monotonic()
    ev = NetEvaluator(_settings(max_slippage=1.0), peg=_peg(0.90))
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)], ts=t)   # USD
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)], ts=t)  # USD
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status is OpportunityStatus.viable


def test_evaluator_without_peg_is_backcompat():
    """Sin peg inyectado el gate es no-op (cero regresión vs comportamiento anterior)."""
    t = time.monotonic()
    ev = NetEvaluator(_settings(max_slippage=1.0))  # sin peg
    buy = _usdt_book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)], ts=t)
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)], ts=t)
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status is OpportunityStatus.viable


def test_viable_simple_cross_no_slippage():
    """Cruce limpio, 1 nivel profundo == 1 BTC: VWAP == top-of-book (slippage 0)."""
    t = time.monotonic()
    s = _settings(max_slippage=1.0)  # apaga filtro de slippage para aislar el neto
    ev = NetEvaluator(s)
    # Compra en binance a 100 (asks), vende en kraken a 110 (bids).
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)], ts=t)
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)], ts=t)
    opp = ev.evaluate(_detected(), buy, sell)

    q = 1.0
    gross = (110.0 - 100.0) * q                       # 10.0
    fees = q * 100.0 * 0.0010 + q * 110.0 * 0.0040    # 0.10 + 0.44 = 0.54
    reb = (0.0002 + 0.00005) * 100.0                  # 0.025
    net = gross - fees - reb                          # 9.435

    assert opp.status == OpportunityStatus.viable
    assert opp.vwap_buy == 100.0 and opp.vwap_sell == 110.0
    assert abs(opp.fees - fees) < 1e-9
    assert abs(opp.net_pnl - net) < 1e-9
    assert opp.q_target == 1.0
    assert opp.slippage == 0.0  # VWAP == top-of-book


def test_vwap_walks_multiple_levels():
    """q=1 consume 2 niveles en compra → VWAP > top-of-book (slippage real > 0)."""
    t = time.monotonic()
    s = _settings(max_slippage=1.0)
    ev = NetEvaluator(s)
    # 0.5 BTC @ 100 + 0.5 BTC @ 102 → vwap_buy 101.0 (top 100 → slippage)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 0.5), (102.0, 0.5)], ts=t)
    sell = _book("kraken", bids=[(120.0, 0.5), (118.0, 0.5)], asks=[(121, 5)], ts=t)
    opp = ev.evaluate(_detected(), buy, sell)

    assert abs(opp.vwap_buy - 101.0) < 1e-9      # (0.5*100+0.5*102)/1
    assert abs(opp.vwap_sell - 119.0) < 1e-9     # (0.5*120+0.5*118)/1
    assert opp.slippage > 0.0                    # walk-the-book, nunca cero
    assert opp.q_target == 1.0


def test_thin_book_discarded():
    """Profundidad < 10% del objetivo → discarded(thin_book)."""
    t = time.monotonic()
    s = _settings()
    ev = NetEvaluator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 0.01)], ts=t)  # solo 0.01 BTC
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)], ts=t)
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.thin_book


def test_not_profitable_discarded():
    """Spread pequeño que las fees devoran → discarded(not_profitable_fees)."""
    t = time.monotonic()
    s = _settings(max_slippage=1.0, min_net_profit_usd=0.0)
    ev = NetEvaluator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)], ts=t)
    sell = _book("kraken", bids=[(100.2, 5.0)], asks=[(101, 5)], ts=t)  # spread 0.2
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.not_profitable_fees
    # Campos económicos rellenos también en descarte por neto.
    assert opp.vwap_buy == 100.0 and opp.vwap_sell == 100.2
    assert opp.fees is not None and opp.net_pnl is not None and opp.net_pnl < 0


def test_slippage_over_limit_discarded():
    """VWAP muy por encima del top-of-book supera max_slippage → discarded."""
    t = time.monotonic()
    s = _settings(max_slippage=0.0010)  # 0.10%
    ev = NetEvaluator(s)
    # 0.5 @ 100 + 0.5 @ 110 → vwap_buy 105 vs top 100 → slip 5% >> 0.10%.
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 0.5), (110.0, 0.5)], ts=t)
    sell = _book("kraken", bids=[(200.0, 5.0)], asks=[(201, 5)], ts=t)
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.slippage_over_limit
    assert opp.vwap_buy is not None and opp.slippage is not None


def test_min_profit_threshold_blocks_viability():
    """net por debajo de min_net_profit_usd → discarded aunque sea positivo."""
    t = time.monotonic()
    s = _settings(max_slippage=1.0, min_net_profit_usd=100.0)
    ev = NetEvaluator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)], ts=t)
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)], ts=t)  # net ~9.4
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.not_profitable_fees
    assert opp.net_pnl is not None and opp.net_pnl > 0  # positivo pero < umbral


def test_fee_per_leg_uses_each_venue_config():
    """Fee única por leg con el fee_taker del venue correspondiente (nunca doble)."""
    t = time.monotonic()
    s = _settings(max_slippage=1.0)
    ev = NetEvaluator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)], ts=t)
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)], ts=t)
    opp = ev.evaluate(_detected("binance", "kraken"), buy, sell)
    expected = 1.0 * 100.0 * 0.0010 + 1.0 * 110.0 * 0.0040  # binance + kraken
    assert abs(opp.fees - expected) < 1e-9


def test_q_limited_by_shallower_leg():
    """q efectiva = min de profundidad de ambas patas (liquidez efectiva)."""
    t = time.monotonic()
    s = _settings(max_slippage=1.0)
    ev = NetEvaluator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)], ts=t)        # 5 BTC
    sell = _book("kraken", bids=[(110.0, 0.3)], asks=[(111, 5)], ts=t)       # solo 0.3
    opp = ev.evaluate(_detected(), buy, sell)
    assert abs(opp.q_target - 0.3) < 1e-9
    assert opp.status == OpportunityStatus.viable


def test_thesis_native_gap_collapses_to_net_negative():
    """Escenario tesis: un gap NATIVO grande que parece atractivo se desinfla tras
    el peg y, con las fees taker/taker, queda NET-NEGATIVO → discarded.

    Cadena $97 → $12 → negativo (la del reto), trazada paso a paso:
      - Gap nativo aparente ~$97: en el feed crudo BTC/USDT de binance se ve ~97 USDT
        por debajo del BTC/USD de kraken. Pero el NormalizedBook YA llega normalizado a
        USD por peg (regla crítica: el evaluador NO re-normaliza), y ese peg < 1.00
        comprime el gap real a sólo ~$12 de spread en USD.
      - Gross normalizado: (100012 - 100000) * 1 BTC = $12.00.
      - Fees taker ÚNICA por leg: 1*100000*0.0010 (binance) + 1*100012*0.0040 (kraken)
        = 100.00 + 400.048 = $500.048.  (¡las fees solas ya superan al gross!)
      - Rebalanceo amortizado: (0.0002 + 0.00005) * 100000 = $25.00.
      - Net = 12.00 - 500.048 - 25.00 = -$513.048 → claramente negativo.
    Resultado esperado: discarded(not_profitable_fees), con los campos económicos
    rellenos (vwap recorridos, fees, slippage, net) para reconciliación en dashboard.
    """
    t = time.monotonic()
    s = _settings(max_slippage=1.0, min_net_profit_usd=0.0)  # aísla el veredicto al neto
    ev = NetEvaluator(s)
    # Libros YA normalizados a USD (1 BTC profundo por lado: VWAP == top, slippage 0).
    buy = _book("binance", bids=[(99_999.0, 5.0)], asks=[(100_000.0, 5.0)], ts=t)
    sell = _book("kraken", bids=[(100_012.0, 5.0)], asks=[(100_013.0, 5.0)], ts=t)
    opp = ev.evaluate(_detected("binance", "kraken"), buy, sell)

    q = 1.0
    gross = (100_012.0 - 100_000.0) * q                       # 12.00
    fees = q * 100_000.0 * 0.0010 + q * 100_012.0 * 0.0040    # 500.048
    reb = (0.0002 + 0.00005) * 100_000.0                      # 25.00
    net = gross - fees - reb                                  # -513.048

    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.not_profitable_fees
    assert opp.vwap_buy == 100_000.0 and opp.vwap_sell == 100_012.0
    assert opp.fees == pytest.approx(fees)
    assert opp.fees == pytest.approx(500.048)                 # gross $12 < fees $500
    assert opp.net_pnl == pytest.approx(net)
    assert opp.net_pnl == pytest.approx(-513.048)             # net-negativo, no $97
    assert opp.net_pnl < 0.0
    assert opp.slippage == 0.0                                # 1 nivel == q: sin slippage
    assert opp.q_target == 1.0


def test_zero_qty_level_does_not_truncate_walk():
    """Un nivel `[price, 0]` (delta de remoción / ruido de snapshot) antepuesto a
    liquidez real NO debe cortar el walk-the-book ni inventar un thin_book espurio."""
    from app.engine.evaluator import _walk_book

    # Regresión directa del repro del hallazgo: primer nivel con qty 0.
    vwap, filled = _walk_book([(100.0, 0.0), (101.0, 1.0)], 1.0)
    assert abs(filled - 1.0) < 1e-9
    assert abs(vwap - 101.0) < 1e-9

    # End-to-end: con un [precio,0] al frente, la liquidez real basta para ser viable.
    t = time.monotonic()
    s = _settings(max_slippage=1.0)
    ev = NetEvaluator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 0.0), (100.0, 5.0)], ts=t)
    sell = _book("kraken", bids=[(110.0, 0.0), (110.0, 5.0)], asks=[(111, 5)], ts=t)
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status == OpportunityStatus.viable
    assert opp.q_target == 1.0
    assert opp.vwap_buy == 100.0 and opp.vwap_sell == 110.0


def test_nan_qty_falls_into_thin_book_not_nan_net():
    """Un nivel con qty=NaN (libro corrupto) debe rechazarse explícitamente como
    thin_book con q_target=0.0, NO propagar NaN hasta net_pnl/q_target."""
    t = time.monotonic()
    s = _settings(max_slippage=1.0)
    ev = NetEvaluator(s)
    # Único nivel de compra con qty NaN → sin liquidez real → thin_book.
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, float("nan"))], ts=t)
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)], ts=t)
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.thin_book
    assert opp.q_target == 0.0          # saneado, nunca NaN
    assert opp.net_pnl is None          # descarte temprano: neto no se computa


def test_thin_book_sets_q_target_to_real_liquidity_regardless_of_initial():
    """En thin_book, q_target debe reflejar la liquidez REALMENTE alcanzable aunque
    la oportunidad llegue con un q_target distinto del default (sin centinela frágil)."""
    t = time.monotonic()
    s = _settings()  # default_trade_qty_btc = 1.0
    ev = NetEvaluator(s)
    opp_in = _detected()
    opp_in.q_target = 0.5  # distinto del default: dimensionado dinámico
    # Sólo 0.01 BTC alcanzable < 10% del objetivo → thin_book.
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 0.01)], ts=t)
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)], ts=t)
    opp = ev.evaluate(opp_in, buy, sell)
    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.thin_book
    assert abs(opp.q_target - 0.01) < 1e-9  # liquidez real, no el 0.5 original


def test_integration_engine_evaluates_before_on_opp():
    """run_engine evalúa el neto con detector.books antes de on_opp (sin red)."""
    import asyncio

    from app.bus import BoundedQueue
    from app.engine import run_engine

    s = _settings(max_slippage=1.0)
    detector = SpatialDetector(s)
    ev = NetEvaluator(s)
    seen: list[Opportunity] = []

    async def driver():
        q: BoundedQueue[NormalizedBook] = BoundedQueue(10)
        t = time.monotonic()
        # binance ask 100 < kraken bid 110 → cruce espacial.
        q.put_nowait(_book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)], ts=t))
        q.put_nowait(_book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)], ts=t))
        task = asyncio.create_task(
            run_engine(q, detector, seen.append, evaluator=ev)
        )
        # Deja procesar ambos books y cancela (test determinista, sin reloj de assert).
        for _ in range(50):
            if seen:
                break
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(driver())
    assert seen, "el motor debe emitir al menos una oportunidad evaluada"
    o = seen[-1]
    assert o.status in (OpportunityStatus.viable, OpportunityStatus.discarded)
    assert o.vwap_buy is not None and o.vwap_sell is not None  # evaluada, no detected
    assert o.buy_venue == "binance" and o.sell_venue == "kraken"


def test_run_engine_builds_evaluator_from_settings_when_none():
    """Si `run_engine` se llama SIN evaluator, lo construye desde `settings` (o el del
    detector). Cubre la rama por defecto del motor (engine/__init__:36)."""
    import asyncio

    from app.bus import BoundedQueue
    from app.engine import run_engine

    s = _settings(max_slippage=1.0)
    detector = SpatialDetector(s)
    seen: list[Opportunity] = []

    async def driver():
        q: BoundedQueue[NormalizedBook] = BoundedQueue(10)
        t = time.monotonic()
        q.put_nowait(_book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)], ts=t))
        q.put_nowait(_book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)], ts=t))
        # SIN evaluator ni settings explícito: usa detector.settings y crea el NetEvaluator.
        task = asyncio.create_task(run_engine(q, detector, seen.append))
        for _ in range(50):
            if seen:
                break
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(driver())
    assert seen, "el motor debe emitir aunque no se pase evaluator"
    assert seen[-1].vwap_buy is not None  # evaluada por el evaluator construido por defecto
