"""C7 — priorización y ranking por score (FR-007, STORY-020).

Cubre la fórmula del score (E[neto]×P(fill)×liquidez−riesgo), el descarte de E[neto]≤0
(score −inf), el orden descendente con las viables primero, y el gate de capital/inventario
del Portfolio (`can_afford`) que materializa "ejecuta por score desc hasta agotar capital".
"""
from __future__ import annotations

from app.config import Settings
from app.engine import Prioritizer
from app.models.enums import DiscardReason, OpportunityStatus, Strategy
from app.models.opportunity import Opportunity
from app.sim import Portfolio


def _settings(**over) -> Settings:
    base = dict(default_trade_qty_btc=1.0, max_slippage=0.0010, exec_latency_ms=150,
                score_pfill_floor=0.05, score_risk_aversion_bps=10.0)
    base.update(over)
    return Settings(**base)


def _viable(net, *, q=1.0, vwap_buy=50_000.0, vwap_sell=None, slippage=0.0, buy="binance",
            sell="kraken", strategy=Strategy.spatial, oid="o") -> Opportunity:
    # vwap_sell por defecto = vwap_buy → notional de par = 2·q·vwap_buy (números limpios para
    # los tests de slippage); el `net` se fija explícito, independiente de los vwaps.
    return Opportunity(
        id=oid, strategy=strategy, symbol="BTC/USD", buy_venue=buy, sell_venue=sell,
        q_target=q, vwap_buy=vwap_buy, vwap_sell=vwap_buy if vwap_sell is None else vwap_sell,
        slippage=slippage, net_pnl=net, status=OpportunityStatus.viable,
    )


# ---------------------------------------------------------------------------
# Fórmula del score
# ---------------------------------------------------------------------------

def test_score_formula_no_slippage_no_penalty():
    """Sin slippage (P_fill=1), liquidez plena (q=q_objetivo) y aversión 0: score == net."""
    s = _settings(score_risk_aversion_bps=0.0)
    p = Prioritizer(s)
    opp = _viable(net=100.0, q=1.0, slippage=0.0)
    assert p.score(opp) == 100.0


def test_score_liquidity_factor_scales():
    """factor_liquidez = q/q_objetivo: la mitad de profundidad ⇒ la mitad de score (resto igual)."""
    s = _settings(score_risk_aversion_bps=0.0)
    p = Prioritizer(s)
    full = _viable(net=100.0, q=1.0, slippage=0.0)
    half = _viable(net=100.0, q=0.5, slippage=0.0)
    assert p.score(full) == 100.0
    assert p.score(half) == 50.0  # net·1·0.5 − 0


def test_score_pfill_from_slippage_headroom():
    """P(fill) = 1 − slip_rel/max_slippage, slip_rel = slippage_usd / notional_par (2 patas)."""
    s = _settings(score_risk_aversion_bps=0.0, max_slippage=0.0010, default_trade_qty_btc=1.0)
    p = Prioritizer(s)
    # notional_par = q·(vwap_buy+vwap_sell) = 1·(50_000+50_000) = 100_000.
    # slip_rel objetivo = 0.0005 ⇒ slippage_usd = 50. P_fill = 1 − 0.0005/0.0010 = 0.5.
    opp = _viable(net=100.0, q=1.0, vwap_buy=50_000.0, vwap_sell=50_000.0, slippage=50.0)
    assert p.score(opp) == 50.0


def test_score_pfill_floor_applies():
    """Slippage que llevaría P(fill)<floor se acota al floor (no anula la opp)."""
    s = _settings(score_risk_aversion_bps=0.0, max_slippage=0.0010, score_pfill_floor=0.1)
    p = Prioritizer(s)
    # slip_rel = max_slippage (0.0010) ⇒ slippage_usd = 0.0010·100_000 = 100 → 1−1=0 → floor 0.1.
    opp = _viable(net=100.0, q=1.0, vwap_buy=50_000.0, vwap_sell=50_000.0, slippage=100.0)
    assert p.score(opp) == 10.0


def test_score_risk_penalty_subtracted():
    """penalización = (bps/1e4)·notional·latencia_seg, restada en USD."""
    s = _settings(score_risk_aversion_bps=10.0, exec_latency_ms=200, default_trade_qty_btc=1.0)
    p = Prioritizer(s)
    # notional = 50_000, latencia 0.2s, penalty = (10/1e4)·50_000·0.2 = 10.
    # P_fill=1 (sin slip), liq=1 ⇒ score = 150·1·1 − 10 = 140.
    opp = _viable(net=150.0, q=1.0, vwap_buy=50_000.0, slippage=0.0)
    assert p.score(opp) == 140.0


def test_score_non_eligible_net_le_zero():
    """E[neto] ≤ 0, None o no finito ⇒ score −inf (refuerzo del filtro de viabilidad C6)."""
    p = Prioritizer(_settings())
    assert p.score(_viable(net=0.0)) == float("-inf")
    assert p.score(_viable(net=-5.0)) == float("-inf")
    none_net = _viable(net=1.0)
    none_net.net_pnl = None
    assert p.score(none_net) == float("-inf")
    nan_net = _viable(net=1.0)
    nan_net.net_pnl = float("nan")
    assert p.score(nan_net) == float("-inf")


def test_score_q_nonfinite_or_zero_is_neg_inf():
    """q_target NaN/0/negativo ⇒ sin tamaño ejecutable ⇒ score −inf (no 0.0)."""
    p = Prioritizer(_settings())
    nan_q = _viable(net=100.0)
    nan_q.q_target = float("nan")
    assert p.score(nan_q) == float("-inf")
    zero_q = _viable(net=100.0, q=0.0)
    assert p.score(zero_q) == float("-inf")


def test_score_guards_no_zero_division():
    """max_slippage=0 (P_fill=1) y default_trade_qty_btc=0 (liq=1) no provocan ZeroDivision."""
    s = _settings(score_risk_aversion_bps=0.0, max_slippage=0.0, default_trade_qty_btc=0.0)
    p = Prioritizer(s)
    opp = _viable(net=100.0, q=1.0, vwap_buy=50_000.0, slippage=999.0)
    assert p.score(opp) == 100.0  # p_fill=1 (max_slip=0), liq=1 (default_q=0) → net·1·1


def test_score_notional_zero_no_division():
    """vwap_buy/sell None ⇒ notional 0 ⇒ slip_rel=0 (sin división), score = net·1·liq."""
    s = _settings(score_risk_aversion_bps=0.0)
    p = Prioritizer(s)
    opp = _viable(net=100.0, q=1.0, slippage=10.0)
    opp.vwap_buy = None
    opp.vwap_sell = None
    assert p.score(opp) == 100.0


def test_rank_empty_and_all_nonviable():
    """rank([]) → []; todas no viables → todas −inf, orden de entrada preservado."""
    p = Prioritizer(_settings())
    assert p.rank([]) == []
    d1 = Opportunity(id="d1", strategy=Strategy.spatial, symbol="BTC/USD", buy_venue="a",
                     sell_venue="b", status=OpportunityStatus.discarded, net_pnl=-1.0)
    d2 = Opportunity(id="d2", strategy=Strategy.spatial, symbol="BTC/USD", buy_venue="a",
                     sell_venue="b", status=OpportunityStatus.discarded, net_pnl=-2.0)
    assert [o.id for o in p.rank([d1, d2])] == ["d1", "d2"]


# ---------------------------------------------------------------------------
# Ranking / orden
# ---------------------------------------------------------------------------

def test_rank_orders_viable_desc_and_assigns_score():
    """Las viables se ordenan por score desc y se les asigna `opp.score`."""
    s = _settings(score_risk_aversion_bps=0.0)
    p = Prioritizer(s)
    lo = _viable(net=10.0, oid="lo")
    hi = _viable(net=300.0, oid="hi")
    mid = _viable(net=100.0, oid="mid")
    ordered = p.rank([lo, hi, mid])
    assert [o.id for o in ordered] == ["hi", "mid", "lo"]
    assert hi.score == 300.0 and mid.score == 100.0 and lo.score == 10.0


def test_rank_discarded_go_last_untouched():
    """Las no viables (discarded) van al final (score −inf) y no se les asigna score positivo."""
    s = _settings(score_risk_aversion_bps=0.0)
    p = Prioritizer(s)
    disc = Opportunity(
        id="disc", strategy=Strategy.spatial, symbol="BTC/USD", buy_venue="binance",
        sell_venue="kraken", status=OpportunityStatus.discarded,
        discard_reason=DiscardReason.not_profitable_fees, net_pnl=-50.0,
    )
    via = _viable(net=20.0, oid="via")
    ordered = p.rank([disc, via])
    assert ordered[0].id == "via"
    assert ordered[1].id == "disc"
    assert disc.score is None  # rank no asigna score a las no viables


def test_rank_stable_on_ties():
    """Empate de score ⇒ preserva el orden de detección (sort estable)."""
    s = _settings(score_risk_aversion_bps=0.0)
    p = Prioritizer(s)
    a = _viable(net=50.0, oid="a")
    b = _viable(net=50.0, oid="b")
    assert [o.id for o in p.rank([a, b])] == ["a", "b"]


# ---------------------------------------------------------------------------
# Gate de capital / inventario (Portfolio.can_afford)
# ---------------------------------------------------------------------------

def _portfolio(**over) -> Portfolio:
    s = Settings(**over) if over else Settings()
    return Portfolio(s)


def test_can_afford_true_with_seeded_balance():
    """Con balances sembrados (2 BTC + 100k/venue) una opp de 1 BTC @ precio bajo es asequible."""
    pf = _portfolio()
    opp = _viable(net=10.0, q=1.0, vwap_buy=40_000.0)  # coste ~40k < 100k quote; 1 BTC < 2 BTC
    assert pf.can_afford(opp) is True


def test_can_afford_false_insufficient_quote():
    """Sin quote suficiente en el venue de COMPRA → no asequible."""
    pf = _portfolio()
    # coste = 1·150_000·(1+fee) > 100_000 quote sembrado.
    opp = _viable(net=10.0, q=1.0, vwap_buy=150_000.0)
    assert pf.can_afford(opp) is False


def test_can_afford_false_insufficient_btc():
    """Sin BTC suficiente en el venue de VENTA → no asequible (límite de inventario)."""
    pf = _portfolio()
    opp = _viable(net=10.0, q=5.0, vwap_buy=10_000.0)  # 5 BTC > 2 BTC sembrados en sell_venue
    assert pf.can_afford(opp) is False


def test_can_afford_depletes_with_sequential_execution():
    """Tras aplicar ejecuciones que consumen el BTC del venue de venta, deja de ser asequible:
    materializa 'ejecuta por score desc hasta agotar inventario'."""
    from app.engine import NetEvaluator
    from app.models.market import NormalizedBook

    s = Settings()
    pf = Portfolio(s)
    sim_venue_sell = "kraken"
    # Vende 2 BTC en kraken (todo su inventario) vía dos ejecuciones de 1 BTC.
    ev = NetEvaluator(s)
    sim = __import__("app.sim", fromlist=["ExecutionSimulator"]).ExecutionSimulator(s)

    def book(ex, bid, ask):
        return NormalizedBook(
            exchange=ex, symbol="BTC/USD", quote_ccy="USD",
            bids=[(bid, 10.0)], asks=[(ask, 10.0)], price_norm_factor=1.0, ts_recv_monotonic=0.0,
        )

    # Cruce muy rentable: compra binance@40000, vende kraken@45000.
    buy_b = book("binance", 39_990, 40_000)
    sell_b = book("kraken", 45_000, 45_010)
    btc_before = pf.venues[sim_venue_sell].btc
    for i in range(2):
        opp = Opportunity(
            id=f"e{i}", strategy=Strategy.spatial, symbol="BTC/USD",
            buy_venue="binance", sell_venue="kraken", q_target=1.0,
            status=OpportunityStatus.detected,
        )
        ev.evaluate(opp, buy_b, sell_b)
        assert opp.status == OpportunityStatus.viable
        assert pf.can_afford(opp) is True
        ex = sim.simulate(opp, buy_b, sell_b)
        pf.apply_execution(ex)
    # Consumió ~2 BTC de kraken; una 3ª venta de 1 BTC ya no cabe.
    assert pf.venues[sim_venue_sell].btc < btc_before
    opp3 = _viable(net=10.0, q=1.0, vwap_buy=40_000.0, buy="binance", sell="kraken")
    assert pf.can_afford(opp3) is False


def test_can_afford_unknown_venue_not_blocked():
    """Venue no sembrado → no bloquea (consistente con apply_execution que lo ignora)."""
    pf = _portfolio()
    opp = _viable(net=10.0, q=1.0, vwap_buy=40_000.0, buy="okx_unseeded", sell="kraken")
    assert pf.can_afford(opp) is True


def test_can_afford_nonfinite_q_false():
    """q no finita/≤0 → no asequible (no se opera sobre datos corruptos)."""
    pf = _portfolio()
    opp = _viable(net=10.0, q=1.0, vwap_buy=40_000.0)
    opp.q_target = float("nan")
    assert pf.can_afford(opp) is False
