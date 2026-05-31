"""C15 — Tests del arnés de validación (STORY-012, FR-021 / NFR-004).

Contenido:
  · TEST ESTRELLA: reconcilia el ejemplo del reto a $109.75/BTC vía el `NetEvaluator` real
    (tolerancia documentada 1e-6 USD: aritmética exacta en doble precisión).
  · Cada invariante: un caso que PASA y un caso que FALLA (doble fee, slippage negativo,
    dinero creado, cross book, neto roto, q > profundidad, arbitraje degenerado, monotonía).
  · El endpoint `GET /api/v1/validation` responde con la forma correcta y all_passed=True.

Deterministas: sin red, sin reloj real en asserts (los `ts` se inyectan a 0.0). Mantiene
los 101 tests previos en verde."""
from __future__ import annotations

import math

import pytest

from app.config import ExchangeConfig, Settings
from app.engine.evaluator import NetEvaluator
from app.models.enums import LegSide, OpportunityStatus, Strategy
from app.models.execution import Execution, Leg
from app.models.market import NormalizedBook
from app.models.opportunity import Opportunity
from app.sim.inventory import Portfolio
from app.validate import (
    RECONCILE_TOLERANCE_USD,
    TARGET_NET_USD,
    build_challenge_opportunity,
    build_challenge_settings,
    build_validation_report,
    check_fee_monotonicity,
    check_net_identity,
    check_no_cross_book,
    check_no_degenerate_arbitrage,
    check_qty_within_depth,
    check_single_fee_per_leg,
    check_slippage_nonnegative,
    check_value_conservation,
    reconcile_challenge,
)
from app.validate.harness import _challenge_books


def _mk_settings(buy_fee: float, sell_fee: float, **kw) -> Settings:
    """`Settings` ad-hoc con dos venues (`v_buy`/`v_sell`) sin rebalanceo, para escenarios."""
    exchanges = {
        "v_buy": ExchangeConfig(id="v_buy", symbol="BTC/USD", quote_ccy="USD",
                                fee_taker=buy_fee, withdrawal_btc=0.0, ob_limit=10,
                                initial_btc=kw.get("initial_btc", 5.0),
                                initial_quote=kw.get("initial_quote", 500_000.0)),
        "v_sell": ExchangeConfig(id="v_sell", symbol="BTC/USD", quote_ccy="USD",
                                 fee_taker=sell_fee, withdrawal_btc=0.0, ob_limit=10,
                                 initial_btc=kw.get("initial_btc", 5.0),
                                 initial_quote=kw.get("initial_quote", 500_000.0)),
    }
    return Settings(exchanges=exchanges, ingest_autostart=False,
                    default_trade_qty_btc=kw.get("qty", 1.0),
                    min_net_profit_usd=0.0, max_slippage=kw.get("max_slippage", 1.0))


def _books(buy_ask: float, sell_bid: float, depth: float = 5.0):
    buy = NormalizedBook(exchange="v_buy", symbol="BTC/USD", quote_ccy="USD",
                         bids=[(buy_ask - 1.0, depth)], asks=[(buy_ask, depth)],
                         ts_recv_monotonic=0.0, ts_exchange=0.0)
    sell = NormalizedBook(exchange="v_sell", symbol="BTC/USD", quote_ccy="USD",
                          bids=[(sell_bid, depth)], asks=[(sell_bid + 1.0, depth)],
                          ts_recv_monotonic=0.0, ts_exchange=0.0)
    return buy, sell


def _opp() -> Opportunity:
    return Opportunity(id="t", strategy=Strategy.spatial, symbol="BTC/USD",
                       buy_venue="v_buy", sell_venue="v_sell")


# ===================================================================== #
# TEST ESTRELLA: reconciliación $109.75/BTC                             #
# ===================================================================== #
def test_reconcile_challenge_109_75():
    """El ejemplo del reto (compra 1 BTC a $70,000 +0.1% fee, venta a $70,250 -0.1% fee)
    reconcilia a $109.75/BTC vía el `NetEvaluator` real. Tolerancia 1e-6 USD (aritmética
    exacta en doble precisión; la holgura sólo absorbe ruido de coma flotante)."""
    r = reconcile_challenge()
    assert r.target == 109.75
    assert r.passed is True
    assert math.isclose(r.computed, 109.75, abs_tol=RECONCILE_TOLERANCE_USD)
    assert abs(r.diff) <= RECONCILE_TOLERANCE_USD
    # Desglose del waterfall: gross 250, fees 140.25, rebalanceo 0, net 109.75.
    assert math.isclose(r.breakdown["gross"], 250.0, abs_tol=1e-6)
    assert math.isclose(r.breakdown["fees"], 140.25, abs_tol=1e-6)
    assert math.isclose(r.breakdown["rebalance"], 0.0, abs_tol=1e-6)
    assert math.isclose(r.breakdown["net"], 109.75, abs_tol=1e-6)


def test_reconcile_uses_real_evaluator_and_marks_viable():
    """La reconciliación pasa por `NetEvaluator.evaluate` (no una fórmula paralela) y la
    opp queda `viable` — gate de regresión: romper el cálculo de neto rompe este test."""
    settings = build_challenge_settings()
    buy_book, sell_book = _challenge_books()
    opp = build_challenge_opportunity()
    NetEvaluator(settings).evaluate(opp, buy_book, sell_book)
    assert opp.status is OpportunityStatus.viable
    assert math.isclose(opp.net_pnl, TARGET_NET_USD, abs_tol=RECONCILE_TOLERANCE_USD)


def test_reconcile_breaks_if_rebalance_added():
    """Sanidad de la SUPOSICIÓN 2: con rebalanceo on-chain > 0 el neto deja de reconciliar
    (baja de 109.75). Demuestra que el 109.75 NO incluye coste de retiro — honestidad."""
    exchanges = {
        "challenge_buy": ExchangeConfig(id="challenge_buy", symbol="BTC/USD",
                                        quote_ccy="USD", fee_taker=0.0010,
                                        withdrawal_btc=0.0002, ob_limit=10),
        "challenge_sell": ExchangeConfig(id="challenge_sell", symbol="BTC/USD",
                                         quote_ccy="USD", fee_taker=0.0010,
                                         withdrawal_btc=0.00005, ob_limit=10),
    }
    settings = Settings(exchanges=exchanges, ingest_autostart=False,
                        default_trade_qty_btc=1.0, min_net_profit_usd=0.0, max_slippage=1.0)
    buy_book, sell_book = _challenge_books()
    opp = build_challenge_opportunity()
    NetEvaluator(settings).evaluate(opp, buy_book, sell_book)
    assert opp.net_pnl < TARGET_NET_USD  # 109.75 - 0.00025*70000 = 92.0


# ===================================================================== #
# INVARIANTE: net = gross - fees - rebalanceo                           #
# ===================================================================== #
def test_net_identity_pass():
    settings = _mk_settings(0.0010, 0.0010)
    opp = _opp()
    buy, sell = _books(70_000.0, 70_250.0)
    NetEvaluator(settings).evaluate(opp, buy, sell)
    assert check_net_identity(opp, settings).passed is True


def test_net_identity_fail_when_net_tampered():
    """Si el `net_pnl` se corrompe (no cuadra con gross-fees-rebalanceo) la invariante falla."""
    settings = _mk_settings(0.0010, 0.0010)
    opp = _opp()
    buy, sell = _books(70_000.0, 70_250.0)
    NetEvaluator(settings).evaluate(opp, buy, sell)
    opp.net_pnl = opp.net_pnl + 50.0  # dinero inventado
    res = check_net_identity(opp, settings)
    assert res.passed is False


# ===================================================================== #
# INVARIANTE: fee única por leg (no doble fee)                          #
# ===================================================================== #
def _exec_with_fee(fee_factor: float) -> Execution:
    """`Execution` de 1 BTC casado con fee = factor * notional * rate (factor 1 => correcto;
    factor 2 => doble fee)."""
    rate = 0.0010
    legs = [
        Leg(venue="v_buy", side=LegSide.buy, qty_filled=1.0, vwap=70_000.0,
            fee=fee_factor * 1.0 * 70_000.0 * rate, qty_requested=1.0),
        Leg(venue="v_sell", side=LegSide.sell, qty_filled=1.0, vwap=70_250.0,
            fee=fee_factor * 1.0 * 70_250.0 * rate, qty_requested=1.0),
    ]
    return Execution(id="e", opportunity_id="t", legs=legs, matched_qty=1.0)


def test_single_fee_per_leg_pass():
    settings = _mk_settings(0.0010, 0.0010)
    assert check_single_fee_per_leg(_exec_with_fee(1.0), settings).passed is True


def test_single_fee_per_leg_fail_double_fee():
    settings = _mk_settings(0.0010, 0.0010)
    res = check_single_fee_per_leg(_exec_with_fee(2.0), settings)  # doble fee
    assert res.passed is False


# ===================================================================== #
# INVARIANTE: slippage >= 0                                             #
# ===================================================================== #
def test_slippage_nonnegative_pass():
    settings = _mk_settings(0.0010, 0.0010)
    opp = _opp()
    # Dos niveles: el walk-the-book de 1 BTC consume sólo el mejor → slippage 0.
    buy, sell = _books(70_000.0, 70_250.0)
    NetEvaluator(settings).evaluate(opp, buy, sell)
    assert check_slippage_nonnegative(opp, buy, sell).passed is True


def test_slippage_nonnegative_fail_when_vwap_better_than_top():
    """Slippage negativo (VWAP de compra MEJOR que el best_ask) = bug → la invariante falla."""
    buy, sell = _books(70_000.0, 70_250.0)
    opp = _opp()
    opp.vwap_buy = 69_900.0   # imposible: mejor que el best_ask (70_000) → slip_buy < 0
    opp.vwap_sell = 70_250.0
    res = check_slippage_nonnegative(opp, buy, sell)
    assert res.passed is False


# ===================================================================== #
# INVARIANTE: q ejecutada <= profundidad                                #
# ===================================================================== #
def test_qty_within_depth_pass():
    buy, sell = _books(70_000.0, 70_250.0, depth=5.0)
    legs = [
        Leg(venue="v_buy", side=LegSide.buy, qty_filled=1.0, vwap=70_000.0, fee=0.0),
        Leg(venue="v_sell", side=LegSide.sell, qty_filled=1.0, vwap=70_250.0, fee=0.0),
    ]
    ex = Execution(id="e", opportunity_id="t", legs=legs, matched_qty=1.0)
    assert check_qty_within_depth(ex, buy, sell).passed is True


def test_qty_within_depth_fail_overfilled():
    buy, sell = _books(70_000.0, 70_250.0, depth=1.0)  # sólo 1 BTC de profundidad
    legs = [
        Leg(venue="v_buy", side=LegSide.buy, qty_filled=3.0, vwap=70_000.0, fee=0.0),
    ]
    ex = Execution(id="e", opportunity_id="t", legs=legs, matched_qty=1.0)
    res = check_qty_within_depth(ex, buy, sell)
    assert res.passed is False


# ===================================================================== #
# INVARIANTE: no cross book                                             #
# ===================================================================== #
def test_no_cross_book_pass():
    buy, _ = _books(70_000.0, 70_250.0)
    assert check_no_cross_book(buy).passed is True


def test_no_cross_book_fail_crossed():
    crossed = NormalizedBook(exchange="x", symbol="BTC/USD", quote_ccy="USD",
                             bids=[(70_100.0, 1.0)], asks=[(70_000.0, 1.0)],
                             ts_recv_monotonic=0.0)  # bid > ask
    res = check_no_cross_book(crossed)
    assert res.passed is False


def test_no_cross_book_fail_asks_not_ascending():
    """Asks NO ascendentes (book desordenado) → la invariante falla (rama 195-196)."""
    bad = NormalizedBook(exchange="x", symbol="BTC/USD", quote_ccy="USD",
                         bids=[(69_000.0, 1.0)],
                         asks=[(70_000.0, 1.0), (69_500.0, 1.0)],  # baja, debería subir
                         ts_recv_monotonic=0.0)
    res = check_no_cross_book(bad)
    assert res.passed is False
    assert "asks no ascendentes" in res.detail


def test_no_cross_book_fail_bids_not_descending():
    """Bids NO descendentes (book desordenado) → la invariante falla (rama 197-198)."""
    bad = NormalizedBook(exchange="x", symbol="BTC/USD", quote_ccy="USD",
                         bids=[(69_000.0, 1.0), (69_500.0, 1.0)],  # sube, debería bajar
                         asks=[(70_000.0, 1.0)],
                         ts_recv_monotonic=0.0)
    res = check_no_cross_book(bad)
    assert res.passed is False
    assert "bids no descendentes" in res.detail


# ===================================================================== #
# INVARIANTE: ramas N/A (descarte temprano, sin neto/VWAP)              #
# ===================================================================== #
def test_net_identity_na_when_no_net_computed():
    """Opp descartada temprano (sin net_pnl/vwap) → net_identity es N/A (passed=True,
    nada que reconciliar). Rama 58-62."""
    opp = _opp()  # sin evaluar: net_pnl/vwap_buy/vwap_sell son None
    res = check_net_identity(opp, _mk_settings(0.0010, 0.0010))
    assert res.passed is True
    assert "descarte temprano" in res.detail


def test_slippage_nonnegative_na_when_no_vwap():
    """Opp sin VWAP (descarte temprano) → slippage_nonnegative es N/A (rama 128-131)."""
    opp = _opp()  # vwap_buy/vwap_sell None
    buy, sell = _books(70_000.0, 70_250.0)
    res = check_slippage_nonnegative(opp, buy, sell)
    assert res.passed is True
    assert "N/A" in res.detail


def test_value_conservation_fail_btc_not_conserved():
    """Si el BTC total cambia (no conservado) la invariante falla por la rama del BTC (251),
    aunque el quote cuadre. Inyectamos BTC de la nada en un venue tras el trade."""
    settings = _mk_settings(0.0010, 0.0010)
    ex = _matched_execution(settings)
    pf = Portfolio(settings)
    quote_before = {v: vb.quote for v, vb in pf.venues.items()}
    btc_before = sum(vb.btc for vb in pf.venues.values())
    pf.apply_execution(ex)
    next(iter(pf.venues.values())).btc += 1.0  # BTC inventado → no conservado
    res = check_value_conservation(quote_before, pf,
                                   realized_pnl=ex.realized_pnl, btc_before=btc_before)
    assert res.passed is False
    assert "btc:" in res.detail


# ===================================================================== #
# INVARIANTE: conservación de valor                                     #
# ===================================================================== #
def _matched_execution(settings: Settings) -> Execution:
    """Simula un trade casado del escenario base para la conservación."""
    from app.sim.simulator import ExecutionSimulator
    opp = _opp()
    buy, sell = _books(70_000.0, 70_250.0)
    NetEvaluator(settings).evaluate(opp, buy, sell)
    return ExecutionSimulator(settings).simulate(opp, buy, sell, ts=0.0)


def test_value_conservation_pass():
    settings = _mk_settings(0.0010, 0.0010)
    ex = _matched_execution(settings)
    pf = Portfolio(settings)
    quote_before = {v: vb.quote for v, vb in pf.venues.items()}
    btc_before = sum(vb.btc for vb in pf.venues.values())
    pf.apply_execution(ex)
    res = check_value_conservation(quote_before, pf,
                                   realized_pnl=ex.realized_pnl, btc_before=btc_before)
    assert res.passed is True
    # El quote total subió EXACTAMENTE el realized P&L (no se inventó dinero).
    assert math.isclose(res.metrics["delta_quote"], ex.realized_pnl, abs_tol=1e-4)
    # El BTC total se conserva (par casado, sin leg risk).
    assert math.isclose(res.metrics["btc_after"], btc_before, abs_tol=1e-9)


def test_value_conservation_fail_money_created():
    """Si el quote total cambia MÁS que el realized P&L (dinero creado), la invariante falla."""
    settings = _mk_settings(0.0010, 0.0010)
    ex = _matched_execution(settings)
    pf = Portfolio(settings)
    quote_before = {v: vb.quote for v, vb in pf.venues.items()}
    btc_before = sum(vb.btc for vb in pf.venues.values())
    pf.apply_execution(ex)
    # Inyectamos $1000 de la nada en un venue → Δquote ya no cuadra con realized_pnl.
    next(iter(pf.venues.values())).quote += 1000.0
    res = check_value_conservation(quote_before, pf,
                                   realized_pnl=ex.realized_pnl, btc_before=btc_before)
    assert res.passed is False


# ===================================================================== #
# INVARIANTE: no-arbitraje degenerado (spread 0 + fees > 0 ⇒ neto < 0)  #
# ===================================================================== #
def test_no_degenerate_arbitrage_pass():
    settings = _mk_settings(0.0010, 0.0010)
    res = check_no_degenerate_arbitrage(settings)
    assert res.passed is True
    assert res.metrics["net"] < 0.0


def test_no_degenerate_arbitrage_fail_zero_fees():
    """Caso que FALLA la invariante: con fees=0 y spread=0 el neto es 0 (no < 0), así que la
    property "spread 0 ⇒ neto<0" no se cumple — la invariante lo detecta correctamente como
    fallo (sin fees no hay margen anti-falso-positivo). La invariante usa los venues
    `deg_buy`/`deg_sell`: para forzar fee 0 los declaramos en config con fee_taker=0."""
    exchanges = {
        "deg_buy": ExchangeConfig(id="deg_buy", symbol="BTC/USD", quote_ccy="USD",
                                  fee_taker=0.0, withdrawal_btc=0.0, ob_limit=10),
        "deg_sell": ExchangeConfig(id="deg_sell", symbol="BTC/USD", quote_ccy="USD",
                                   fee_taker=0.0, withdrawal_btc=0.0, ob_limit=10),
    }
    settings = Settings(exchanges=exchanges, ingest_autostart=False,
                        default_trade_qty_btc=1.0, min_net_profit_usd=0.0, max_slippage=1.0)
    res = check_no_degenerate_arbitrage(settings)
    assert res.passed is False


# ===================================================================== #
# INVARIANTE: monotonía de fees                                         #
# ===================================================================== #
def test_fee_monotonicity_pass():
    res = check_fee_monotonicity()
    assert res.passed is True
    assert res.metrics["net_high_fee"] <= res.metrics["net_low_fee"]


# ===================================================================== #
# ENDPOINT /api/v1/validation                                          #
# ===================================================================== #
def test_validation_endpoint_shape(client):
    """El endpoint responde con {reconciliation, invariants, all_passed} y la reconciliación
    a 109.75. Autostart-safe: funciona en tests sin ingesta."""
    r = client.get("/api/v1/validation")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"reconciliation", "invariants", "all_passed"}
    rec = body["reconciliation"]
    assert rec["target"] == 109.75
    assert rec["passed"] is True
    assert math.isclose(rec["computed"], 109.75, abs_tol=1e-6)
    assert isinstance(body["invariants"], list) and len(body["invariants"]) >= 8
    # Toda invariante trae nombre + veredicto.
    for inv in body["invariants"]:
        assert "name" in inv and "passed" in inv
    assert body["all_passed"] is True


def test_validation_report_all_passed():
    rep = build_validation_report()
    assert rep.all_passed is True
    assert all(i.passed for i in rep.invariants)
    assert rep.reconciliation.passed is True


@pytest.mark.parametrize("name", [
    "net_identity", "single_fee_per_leg", "slippage_nonnegative", "qty_within_depth",
    "no_cross_book", "value_conservation", "no_degenerate_arbitrage", "fee_monotonicity",
])
def test_report_contains_each_invariant(name):
    """El reporte cubre TODAS las invariantes exigidas por FR-021."""
    rep = build_validation_report()
    names = {i.name for i in rep.invariants}
    assert name in names
