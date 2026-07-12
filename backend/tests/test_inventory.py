"""C10 — inventario pre-posicionado, doble entrada y P&L (STORY-010, FR-010/011).

Determinista: libros sintéticos, sin red ni reloj para los asserts numéricos.
Invariante de conservación verificada explícitamente.
"""
from __future__ import annotations

import asyncio

import pytest

from app.config import ExchangeConfig, Settings
from app.models.enums import LegSide, OpportunityStatus, Strategy
from app.models.execution import Execution, Leg
from app.models.market import NormalizedBook
from app.models.opportunity import Opportunity
from app.sim import ExecutionSimulator, Portfolio


def _exec(legs, *, realized_pnl=0.0, ts=1.0, eid="exec-hand") -> Execution:
    """`Execution` construido A MANO (sin simulador): control total de los números.

    Deriva los campos de LEG RISK del par buy/sell (como hace el simulador): el excedente
    `|filled_buy − filled_sell|` queda como posición abierta en el venue sobre-llenado, con
    coste base = VWAP de ese leg (los `_leg` a mano usan un único precio por leg, así el
    VWAP del excedente coincide con el del leg)."""
    buy = next((leg for leg in legs if leg.side is LegSide.buy), None)
    sell = next((leg for leg in legs if leg.side is LegSide.sell), None)
    fb = buy.qty_filled if buy else 0.0
    fs = sell.qty_filled if sell else 0.0
    matched = min(fb, fs)
    lr_qty = abs(fb - fs)
    lr_venue = lr_side = None
    lr_vwap = 0.0
    if lr_qty > 1e-12:
        if fb > fs:
            lr_venue, lr_side, lr_vwap = buy.venue, LegSide.buy, buy.vwap
        else:
            lr_venue, lr_side, lr_vwap = sell.venue, LegSide.sell, sell.vwap
    return Execution(
        id=eid, opportunity_id="opp-hand", legs=legs,
        matched_qty=matched, realized_pnl=realized_pnl, ts=ts,
        leg_risk_qty=lr_qty, leg_risk_entry_vwap=lr_vwap,
        leg_risk_venue=lr_venue, leg_risk_side=lr_side,
    )


def _leg(venue, side, qty, vwap, fee) -> Leg:
    return Leg(venue=venue, side=side, qty_filled=qty, vwap=vwap, fee=fee, qty_requested=qty)


def _book(ex: str, bids, asks) -> NormalizedBook:
    return NormalizedBook(
        exchange=ex, symbol="BTC/USD", quote_ccy="USD",
        bids=bids, asks=asks, price_norm_factor=1.0, ts_recv_monotonic=0.0,
        ts_exchange=1000.0,
    )


def _settings(skew_limit: float = 0.5, **over) -> Settings:
    base = dict(
        default_trade_qty_btc=1.0,
        exec_latency_ms=150,
        inventory_skew_limit=skew_limit,
        exchanges={
            "binance": ExchangeConfig(
                id="binance", symbol="BTC/USDT", quote_ccy="USDT",
                fee_taker=0.0010, withdrawal_btc=0.0002, ob_limit=20,
                initial_btc=2.0, initial_quote=100_000.0,
            ),
            "kraken": ExchangeConfig(
                id="kraken", symbol="BTC/USD", quote_ccy="USD",
                fee_taker=0.0040, withdrawal_btc=0.00005, ob_limit=25,
                initial_btc=2.0, initial_quote=100_000.0,
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


def _total_btc(pf: Portfolio) -> float:
    return sum(vb.btc for vb in pf.venues.values())


def _total_quote(pf: Portfolio) -> float:
    return sum(vb.quote for vb in pf.venues.values())


def _fingerprint(pf: Portfolio):
    """Fingerprint contable completo (PRD-009): campos por venue + realized_pnl."""
    return (
        {
            v: (vb.btc, vb.quote, vb.open_btc, vb.open_cost_basis_usd)
            for v, vb in pf.venues.items()
        },
        pf.realized_pnl,
    )


# --- Siembra ---------------------------------------------------------------

def test_seed_from_config():
    pf = Portfolio(_settings())
    assert set(pf.venues) == {"binance", "kraken"}
    assert pf.venues["binance"].btc == pytest.approx(2.0)
    assert pf.venues["binance"].quote == pytest.approx(100_000.0)
    assert pf.venues["kraken"].quote_ccy == "USD"
    assert pf.initial_quote_total == pytest.approx(200_000.0)
    assert pf.initial_btc_total == pytest.approx(4.0)
    assert pf.realized_pnl == pytest.approx(0.0)


def test_disabled_venue_not_seeded():
    s = _settings()
    s.exchanges["kraken"].enabled = False
    pf = Portfolio(s)
    assert set(pf.venues) == {"binance"}


# --- Doble entrada + conservación -----------------------------------------

def test_full_fill_double_entry_and_conservation():
    """Compra 1 BTC@100 en binance, vende 1 BTC@110 en kraken (fill simétrico).
    BTC total se conserva; el quote total baja SÓLO por las fees pagadas."""
    s = _settings()
    sim = ExecutionSimulator(s)
    pf = Portfolio(s)
    btc0, quote0 = _total_btc(pf), _total_quote(pf)

    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)
    assert pf.apply_execution(ex) is True  # PRD-009: el camino de aceptación devuelve True

    # BTC: compré 1 en binance (+1), vendí 1 en kraken (−1) → total conservado.
    assert _total_btc(pf) == pytest.approx(btc0)
    assert pf.venues["binance"].btc == pytest.approx(3.0)
    assert pf.venues["kraken"].btc == pytest.approx(1.0)
    # Quote: el total baja exactamente por las fees totales (nada se crea/destruye salvo coste).
    fees = 1.0 * 100.0 * 0.0010 + 1.0 * 110.0 * 0.0040
    assert _total_quote(pf) == pytest.approx(quote0 + (110.0 - 100.0) * 1.0 - fees)
    # binance: −coste −fee_buy ; kraken: +ingreso −fee_sell
    assert pf.venues["binance"].quote == pytest.approx(100_000.0 - 100.0 - 100.0 * 0.0010)
    assert pf.venues["kraken"].quote == pytest.approx(100_000.0 + 110.0 - 110.0 * 0.0040)
    # realized P&L = neto del simulador
    assert pf.realized_pnl == pytest.approx(ex.realized_pnl)


def test_realized_pnl_accumulates_over_executions():
    s = _settings()
    sim = ExecutionSimulator(s)
    pf = Portfolio(s)
    buy = _book("binance", bids=[(99.0, 50.0)], asks=[(100.0, 50.0)])
    sell = _book("kraken", bids=[(110.0, 50.0)], asks=[(111.0, 50.0)])
    total = 0.0
    for _ in range(3):
        ex = sim.simulate(_viable(), buy, sell, ts=1.0)
        assert pf.apply_execution(ex) is True
        total += ex.realized_pnl
    assert pf.realized_pnl == pytest.approx(total)
    assert pf.realized_pnl > 0.0  # spread amplio: positivo


def test_leg_risk_excess_moves_balance():
    """Excedente de leg risk (BTC comprado de más) SÍ movió balances: queda como inventario
    abierto. Conservación: el BTC neto de la cartera sube en el excedente largo no casado."""
    s = _settings()
    sim = ExecutionSimulator(s)
    pf = Portfolio(s)
    btc0 = _total_btc(pf)
    # compra llena 1.0, venta sólo 0.4 → 0.6 BTC largos en binance (excedente).
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[(110.0, 0.4)], asks=[(111.0, 5.0)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)
    assert pf.apply_execution(ex) is True  # leg risk efectivo en venue sembrado: acepta
    assert ex.leg_risk_qty == pytest.approx(0.6)
    # binance compró 1.0 (+1.0), kraken vendió 0.4 (−0.4) → neto +0.6 vs inicial.
    assert _total_btc(pf) == pytest.approx(btc0 + 0.6)
    assert pf.venues["binance"].btc == pytest.approx(3.0)
    assert pf.venues["kraken"].btc == pytest.approx(1.6)


# --- P&L no realizado / equity --------------------------------------------

def test_unrealized_pnl_and_equity_mark_to_market():
    """Tras un trade que deja inventario largo, el unrealized marca a mercado contra el
    libro actual; equity total = Σ (quote + btc·mark)."""
    s = _settings()
    sim = ExecutionSimulator(s)
    pf = Portfolio(s)
    buy = _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[(110.0, 0.4)], asks=[(111.0, 5.0)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)
    pf.apply_execution(ex)

    books = {"binance": buy, "kraken": sell}
    eq = pf.equity_total(books)
    # binance largo 3.0 BTC marcado a best_bid 99; kraken corto/largo 1.6 BTC a best_bid 110.
    expected = (
        pf.venues["binance"].quote + 3.0 * 99.0
        + pf.venues["kraken"].quote + 1.6 * 110.0
    )
    assert eq == pytest.approx(expected)
    # unrealized finito (no NaN) y por venue suma a la agregada.
    import math
    assert math.isfinite(pf.unrealized_pnl(books))


def test_unrealized_zero_without_books():
    s = _settings()
    sim = ExecutionSimulator(s)
    pf = Portfolio(s)
    ex = sim.simulate(
        _viable(),
        _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)]),
        _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)]),
        ts=1.0,
    )
    pf.apply_execution(ex)
    # Sin libros para marcar → unrealized 0; equity = sólo quote.
    assert pf.unrealized_pnl({}) == pytest.approx(0.0)
    assert pf.equity_total({}) == pytest.approx(_total_quote(pf))


def test_equity_finite_with_corrupt_book():
    s = _settings()
    sim = ExecutionSimulator(s)
    pf = Portfolio(s)
    ex = sim.simulate(
        _viable(),
        _book("binance", bids=[(99.0, 5.0)], asks=[(100.0, 5.0)]),
        _book("kraken", bids=[(110.0, 0.4)], asks=[(111.0, 5.0)]),
        ts=1.0,
    )
    pf.apply_execution(ex)
    import math
    bad = {"binance": _book("binance", bids=[(float("nan"), 1.0)], asks=[(float("inf"), 1.0)])}
    assert math.isfinite(pf.equity_total(bad))


# --- Skew de inventario ----------------------------------------------------

def test_skew_balanced_below_limit():
    pf = Portfolio(_settings(skew_limit=0.5))
    sk = pf.inventory_skew()
    # binance 2.0 / kraken 2.0 → media 2.0, sin desviación.
    assert sk["skew"] == pytest.approx(0.0)
    assert sk["breached"] is False
    assert sk["total_btc"] == pytest.approx(4.0)


def test_skew_breach_flag():
    s = _settings(skew_limit=0.2)
    pf = Portfolio(s)
    pf.venues["binance"].btc = 3.5
    pf.venues["kraken"].btc = 0.5
    sk = pf.inventory_skew()
    # media 2.0, max_dev 1.5, gross/n 2.0 → skew 0.75 > 0.2 → breach.
    assert sk["skew"] == pytest.approx(0.75)
    assert sk["breached"] is True


def test_skew_opposite_long_short_breaches():
    """El peor desbalance del arbitraje: un venue largo, otro corto, que netean ~0. Antes
    quedaba ciego (skew=0 por normalizar por el neto); ahora se normaliza por el GROSS medio
    y registra skew ALTO → breach. binance=+5 / kraken=-5: media 0, max_dev 5, gross/n 5 →
    skew 1.0 > 0.5."""
    s = _settings(skew_limit=0.5)
    pf = Portfolio(s)
    pf.venues["binance"].btc = 5.0
    pf.venues["kraken"].btc = -5.0
    sk = pf.inventory_skew()
    assert sk["total_btc"] == pytest.approx(0.0)
    assert sk["skew"] == pytest.approx(1.0)
    assert sk["breached"] is True


def test_skew_zero_total_btc():
    """Ambos venues realmente VACÍOS (gross ~0): no hay skew computable → 0/False. (Distinto
    de largo+corto que netean 0: ese SÍ tiene gross alto y debe romper, ver test anterior.)"""
    s = _settings()
    pf = Portfolio(s)
    pf.venues["binance"].btc = 0.0
    pf.venues["kraken"].btc = 0.0
    sk = pf.inventory_skew()
    assert sk["skew"] == pytest.approx(0.0)
    assert sk["breached"] is False


# --- Serie de equity / snapshot -------------------------------------------

def test_equity_series_records_points():
    s = _settings()
    sim = ExecutionSimulator(s)
    pf = Portfolio(s)
    buy = _book("binance", bids=[(99.0, 50.0)], asks=[(100.0, 50.0)])
    sell = _book("kraken", bids=[(110.0, 50.0)], asks=[(111.0, 50.0)])
    books = {"binance": buy, "kraken": sell}
    for i in range(3):
        ex = sim.simulate(_viable(), buy, sell, ts=float(i))
        pf.apply_execution(ex)
        pf.record_equity_point(books, ts=float(i))
    assert len(pf.equity_series) == 3
    assert pf.equity_series[0]["ts"] == 0.0
    assert all("equity" in p for p in pf.equity_series)


def test_equity_series_bounded():
    s = _settings()
    pf = Portfolio(s, equity_series_maxlen=5)
    books: dict = {}
    for i in range(20):
        pf.record_equity_point(books, ts=float(i))
    assert len(pf.equity_series) == 5
    assert pf.equity_series[0]["ts"] == 15.0   # drop-oldest mantiene los recientes


def test_snapshot_shape():
    s = _settings()
    pf = Portfolio(s)
    snap = pf.snapshot({}, ts=42.0)
    assert snap.ts == 42.0
    assert snap.total_usd == pytest.approx(_total_quote(pf))
    # 2 venues × (BTC + quote) = 4 balances
    assert len(snap.balances) == 4


def test_pnl_summary_shape():
    s = _settings()
    sim = ExecutionSimulator(s)
    pf = Portfolio(s)
    buy = _book("binance", bids=[(99.0, 50.0)], asks=[(100.0, 50.0)])
    sell = _book("kraken", bids=[(110.0, 50.0)], asks=[(111.0, 50.0)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)
    pf.apply_execution(ex)
    summary = pf.pnl_summary({"binance": buy, "kraken": sell})
    assert summary["total_pnl"] == pytest.approx(
        summary["realized_pnl"] + summary["unrealized_pnl"]
    )
    assert "equity_series" in summary
    assert "skew" in summary
    assert summary["equity_usd"] > 0.0


# --- API wiring ------------------------------------------------------------

def test_balances_endpoint_seeded_even_without_autostart(client):
    """La cartera se siembra en el lifespan SIEMPRE (también con autostart off), para que
    `/balances` exponga el inventario pre-posicionado desde el arranque (dashboard)."""
    r = client.get("/api/v1/balances")
    assert r.status_code == 200
    body = r.json()
    # Multi-venue: cada venue habilitado siembra BTC + quote ⇒ 2 balances por venue.
    from app.config import get_settings
    n_enabled = len(get_settings().enabled_exchanges)
    assert len(body["balances"]) == 2 * n_enabled
    assert n_enabled >= 3
    assert "skew" in body


def test_pnl_endpoint_zero_pnl_at_startup(client):
    """Sin trades, realized/unrealized/total = 0 (honestidad del neto) y serie vacía."""
    r = client.get("/api/v1/pnl")
    assert r.status_code == 200
    body = r.json()
    assert body["realized_pnl"] == 0.0
    assert body["total_pnl"] == pytest.approx(body["unrealized_pnl"])
    assert body["equity_series"] == []


def test_balances_endpoint_with_live_portfolio(client):
    """Inyecta una cartera viva en el ctx y verifica el snapshot expuesto."""
    ctx = client.app.state.ctx
    ctx.portfolio = Portfolio(_settings())
    r = client.get("/api/v1/balances")
    assert r.status_code == 200
    body = r.json()
    assert len(body["balances"]) == 4
    assert "equity_by_venue" in body
    assert "skew" in body
    assert body["snapshot"] is not None


def test_pnl_endpoint_with_live_portfolio(client):
    ctx = client.app.state.ctx
    pf = Portfolio(_settings())
    sim = ExecutionSimulator(_settings())
    buy = _book("binance", bids=[(99.0, 50.0)], asks=[(100.0, 50.0)])
    sell = _book("kraken", bids=[(110.0, 50.0)], asks=[(111.0, 50.0)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)
    pf.apply_execution(ex)
    ctx.portfolio = pf
    ctx.latest_norm = {"binance": buy, "kraken": sell}
    r = client.get("/api/v1/pnl")
    assert r.status_code == 200
    body = r.json()
    assert body["realized_pnl"] == pytest.approx(ex.realized_pnl)
    assert body["total_pnl"] == pytest.approx(body["realized_pnl"] + body["unrealized_pnl"])


# --- Numeros A MANO (Execution construido a mano, sin simulador) -----------

def test_hand_double_entry_conservation_exact():
    """Execution A MANO: compra 1.0 BTC@100 (fee 0.10) en binance, vende 1.0 BTC@110
    (fee 0.44) en kraken. Verifica los balances exactos y la INVARIANTE de conservacion:
    delta de equity (marcado al mismo libro) == realized_pnl, sin crear/destruir valor."""
    s = _settings()
    pf = Portfolio(s)
    btc0, quote0 = _total_btc(pf), _total_quote(pf)

    # realized_pnl neto del tramo casado calculado a mano: (110-100)*1 - 0.10 - 0.44 = 9.46
    realized = (110.0 - 100.0) * 1.0 - 0.10 - 0.44
    ex = _exec(
        [
            _leg("binance", LegSide.buy, 1.0, 100.0, 0.10),
            _leg("kraken", LegSide.sell, 1.0, 110.0, 0.44),
        ],
        realized_pnl=realized,
    )
    pf.apply_execution(ex)

    # binance: -coste(100) -fee(0.10) ; +1 BTC
    assert pf.venues["binance"].quote == pytest.approx(100_000.0 - 100.0 - 0.10)
    assert pf.venues["binance"].btc == pytest.approx(3.0)
    # kraken: +ingreso(110) -fee(0.44) ; -1 BTC
    assert pf.venues["kraken"].quote == pytest.approx(100_000.0 + 110.0 - 0.44)
    assert pf.venues["kraken"].btc == pytest.approx(1.0)
    # BTC total conservado (fill simetrico 1<->1)
    assert _total_btc(pf) == pytest.approx(btc0)
    # quote total: solo baja por fees y sube por el spread bruto del matched
    assert _total_quote(pf) == pytest.approx(quote0 + (110.0 - 100.0) - (0.10 + 0.44))
    assert pf.realized_pnl == pytest.approx(realized)

    # INVARIANTE de conservacion: marcando el inventario al MISMO precio en ambos venues
    # (100 en los dos libros) la equity solo cambia en el realized del matched: no se crea
    # ni destruye valor mas alla del P&L y las fees ya contabilizadas.
    books = {
        "binance": _book("binance", bids=[(100.0, 50.0)], asks=[(100.0, 50.0)]),
        "kraken": _book("kraken", bids=[(100.0, 50.0)], asks=[(100.0, 50.0)]),
    }
    equity = pf.equity_total(books)
    equity0 = quote0 + btc0 * 100.0   # equity inicial valorada al mismo mark
    assert equity - equity0 == pytest.approx(realized)


def test_hand_realized_pnl_accumulates_known_numbers():
    """Tres Execution A MANO con realized conocidos: 5.0, -1.5, 3.25 → suma 6.75."""
    s = _settings()
    pf = Portfolio(s)
    valores = [5.0, -1.5, 3.25]
    for i, r in enumerate(valores):
        ex = _exec(
            [
                _leg("binance", LegSide.buy, 0.5, 100.0, 0.05),
                _leg("kraken", LegSide.sell, 0.5, 101.0, 0.20),
            ],
            realized_pnl=r, ts=float(i), eid=f"exec-{i}",
        )
        pf.apply_execution(ex)
    assert pf.realized_pnl == pytest.approx(sum(valores))
    assert pf.realized_pnl == pytest.approx(6.75)


def test_hand_unrealized_mark_to_market_known_numbers():
    """Leg risk LARGO a mano: compra 1.0 BTC@100 en binance, vende 0.4 BTC@110 en kraken.
    Posición ABIERTA = SÓLO el excedente no casado: +0.6 BTC en binance (coste base
    100·0.6=60). El tramo CASADO (0.4) NO es posición abierta (su P&L vive en realized) y el
    BTC inicial pre-posicionado (coste 0) tampoco aporta unrealized fantasma. Marcado a
    best_bid=120: unrealized = 0.6·120 - 60 = 12.0; kraken sin posición abierta → 0."""
    s = _settings()
    pf = Portfolio(s)
    ex = _exec(
        [
            _leg("binance", LegSide.buy, 1.0, 100.0, 0.0),
            _leg("kraken", LegSide.sell, 0.4, 110.0, 0.0),
        ],
        realized_pnl=0.0,
    )
    pf.apply_execution(ex)
    assert pf.venues["binance"].btc == pytest.approx(3.0)   # 2 iniciales + 1 comprado (físico)
    assert pf.venues["binance"].open_btc == pytest.approx(0.6)  # SÓLO el leg risk no casado
    assert pf.venues["binance"].open_cost_basis_usd == pytest.approx(60.0)  # 0.6·100
    assert pf.venues["kraken"].btc == pytest.approx(1.6)
    assert pf.venues["kraken"].open_btc == pytest.approx(0.0)  # casado: 0 posición abierta

    # binance marcado a best_bid 120 (largo), kraken a best_bid 105.
    books = {
        "binance": _book("binance", bids=[(120.0, 50.0)], asks=[(121.0, 50.0)]),
        "kraken": _book("kraken", bids=[(105.0, 50.0)], asks=[(106.0, 50.0)]),
    }
    # SÓLO el leg risk abierto de binance: 0.6·120 - 60 = 12.0. kraken aporta 0.
    expected = 0.6 * 120.0 - 60.0
    assert pf.unrealized_pnl(books) == pytest.approx(expected)


def test_no_executions_realized_zero_equity_is_initial_marked():
    """Sin ejecuciones, CON libros: realized=0 y unrealized=0 → total_pnl=0. El inventario
    PRE-POSICIONADO NO es posición abierta del bot (open_btc=0): NO genera unrealized
    fantasma (honestidad del neto, el ticker arranca en 0 con o sin libros). La equity SÍ
    marca todo el BTC sembrado (correcto para equity/drawdown): 200_000 + 4·100 = 200_400."""
    s = _settings()
    pf = Portfolio(s)
    assert pf.realized_pnl == pytest.approx(0.0)
    books = {
        "binance": _book("binance", bids=[(100.0, 50.0)], asks=[(101.0, 50.0)]),
        "kraken": _book("kraken", bids=[(100.0, 50.0)], asks=[(101.0, 50.0)]),
    }
    summary = pf.pnl_summary(books)
    assert summary["realized_pnl"] == pytest.approx(0.0)   # cero trades → cero realized
    # SIN posición abierta (inventario sembrado, coste 0 fantasma eliminado) → unrealized 0.
    assert summary["unrealized_pnl"] == pytest.approx(0.0)
    assert summary["total_pnl"] == pytest.approx(0.0)
    # equity = 200_000 quote + 4.0 BTC · 100 (best_bid) = 200_400 (marca todo el BTC).
    assert summary["equity_usd"] == pytest.approx(200_000.0 + 4.0 * 100.0)
    assert summary["equity_series"] == []


def test_no_executions_unrealized_zero_without_books():
    """Sin ejecuciones y SIN libros para marcar: realized/unrealized/total = 0; equity =
    suma de los quote iniciales. Asi el arranque limpio del dashboard reporta P&L 0 honesto."""
    s = _settings()
    pf = Portfolio(s)
    summary = pf.pnl_summary({})
    assert summary["realized_pnl"] == pytest.approx(0.0)
    assert summary["unrealized_pnl"] == pytest.approx(0.0)
    assert summary["total_pnl"] == pytest.approx(0.0)
    assert summary["equity_usd"] == pytest.approx(200_000.0)   # solo quote
    assert summary["equity_series"] == []


def test_equity_series_multiple_snapshots_track_marks():
    """Varios snapshots: la serie registra equity creciente al subir el mark del inventario."""
    s = _settings()
    pf = Portfolio(s)
    eqs = []
    for i, px in enumerate([100.0, 110.0, 120.0]):
        books = {
            "binance": _book("binance", bids=[(px, 50.0)], asks=[(px + 1.0, 50.0)]),
            "kraken": _book("kraken", bids=[(px, 50.0)], asks=[(px + 1.0, 50.0)]),
        }
        eqs.append(pf.record_equity_point(books, ts=float(i)))
    assert len(pf.equity_series) == 3
    # equity = 200_000 + 4.0·px → estrictamente creciente con px.
    assert eqs[0] == pytest.approx(200_000.0 + 4.0 * 100.0)
    assert eqs[2] == pytest.approx(200_000.0 + 4.0 * 120.0)
    assert eqs[0] < eqs[1] < eqs[2]
    assert [p["ts"] for p in pf.equity_series] == [0.0, 1.0, 2.0]


# --- Invariante anti doble-conteo del tramo casado -------------------------

def test_matched_roundtrip_no_double_count_total_pnl_equals_delta_equity():
    """REGRESIÓN del bug de doble-conteo: un round-trip CASADO puro (compra 1@100, vende
    1@110, sin leg risk) no debe generar unrealized — su P&L vive ENTERO en realized. Antes
    total_pnl duplicaba el spread (realized 10 + unrealized 10 = 20). Ahora unrealized=0 y
    se cumple la invariante: total_pnl == delta de equity marcada al mismo libro."""
    s = _settings()
    pf = Portfolio(s)
    btc0, quote0 = _total_btc(pf), _total_quote(pf)
    realized = (110.0 - 100.0) * 1.0   # sin fees, para aislar
    ex = _exec(
        [
            _leg("binance", LegSide.buy, 1.0, 100.0, 0.0),
            _leg("kraken", LegSide.sell, 1.0, 110.0, 0.0),
        ],
        realized_pnl=realized,
    )
    pf.apply_execution(ex)
    # Tramo 100% casado → CERO posición abierta en ambos venues.
    assert pf.venues["binance"].open_btc == pytest.approx(0.0)
    assert pf.venues["kraken"].open_btc == pytest.approx(0.0)

    # Marcando ambos venues al MISMO mid=105, el matched no aporta unrealized (era el bug).
    books = {
        "binance": _book("binance", bids=[(105.0, 50.0)], asks=[(105.0, 50.0)]),
        "kraken": _book("kraken", bids=[(105.0, 50.0)], asks=[(105.0, 50.0)]),
    }
    summary = pf.pnl_summary(books)
    assert summary["realized_pnl"] == pytest.approx(10.0)
    assert summary["unrealized_pnl"] == pytest.approx(0.0)   # NO se duplica el spread
    assert summary["total_pnl"] == pytest.approx(10.0)
    # INVARIANTE: total_pnl == delta de equity (mismo libro), no se crea/destruye valor.
    equity0 = quote0 + btc0 * 105.0
    assert summary["equity_usd"] - equity0 == pytest.approx(summary["total_pnl"])


def test_total_pnl_equals_delta_equity_with_leg_risk():
    """Con leg risk (largo no casado) la invariante total_pnl == delta_equity también se
    cumple: el realized cubre el matched y el unrealized cubre SÓLO el excedente abierto,
    sin solaparse. Compra 1@100, vende 0.4@110 (matched 0.4, leg risk +0.6 en binance)."""
    s = _settings()
    pf = Portfolio(s)
    btc0, quote0 = _total_btc(pf), _total_quote(pf)
    realized = (110.0 - 100.0) * 0.4   # P&L del tramo casado (0.4), sin fees
    ex = _exec(
        [
            _leg("binance", LegSide.buy, 1.0, 100.0, 0.0),
            _leg("kraken", LegSide.sell, 0.4, 110.0, 0.0),
        ],
        realized_pnl=realized,
    )
    pf.apply_execution(ex)
    books = {
        "binance": _book("binance", bids=[(130.0, 50.0)], asks=[(130.0, 50.0)]),
        "kraken": _book("kraken", bids=[(130.0, 50.0)], asks=[(130.0, 50.0)]),
    }
    summary = pf.pnl_summary(books)
    equity0 = quote0 + btc0 * 130.0
    assert summary["unrealized_pnl"] == pytest.approx(0.6 * 130.0 - 0.6 * 100.0)  # 18.0
    assert summary["equity_usd"] - equity0 == pytest.approx(summary["total_pnl"])


# ===========================================================================================
# STORY-017 — Rebalanceo de inventario PERIÓDICO (FR-011). Detección de drift, coste on-chain
# real al P&L, conservación. Determinista (libros sintéticos, sin reloj).
# ===========================================================================================


def _uniform_books(mark: float = 100.0):
    return {
        "binance": _book("binance", bids=[(mark, 50.0)], asks=[(mark, 50.0)]),
        "kraken": _book("kraken", bids=[(mark, 50.0)], asks=[(mark, 50.0)]),
    }


def test_rebalance_noop_when_skew_within_limit():
    """Inventario balanceado (skew bajo el límite) → no rebalancea: devuelve None, sin coste
    ni cambio de balances."""
    pf = Portfolio(_settings())  # binance 2.0, kraken 2.0 → skew 0
    out = pf.rebalance(_uniform_books(), ts=1.0)
    assert out is None
    assert pf.rebalance_count == 0
    assert pf.realized_pnl == pytest.approx(0.0)
    assert pf.venues["binance"].btc == pytest.approx(2.0)


def test_rebalance_fires_when_skew_breached_and_charges_cost():
    """Drift de inventario sobre el límite → rebalancea: iguala BTC entre venues y carga el
    coste on-chain (withdrawal_btc del venue que ENVÍA) al realized P&L."""
    s = _settings()  # withdrawal binance 0.0002; skew_limit 0.5
    pf = Portfolio(s)
    # Drift: binance 3.5, kraken 0.5 → skew = 1.5/(4/2) = 0.75 > 0.5.
    pf.venues["binance"].btc = 3.5
    pf.venues["kraken"].btc = 0.5
    assert pf.inventory_skew()["breached"] is True
    mark = 100.0
    out = pf.rebalance(_uniform_books(mark), ts=2.0)
    assert out is not None
    fee_btc = 0.0002  # sólo binance envía (btc > media)
    assert out["fee_btc"] == pytest.approx(fee_btc)
    assert out["cost_usd"] == pytest.approx(fee_btc * mark)
    assert out["skew_after"] == pytest.approx(0.0)
    # Iguala ambos venues a (total − fee)/2.
    new_target = (4.0 - fee_btc) / 2.0
    assert pf.venues["binance"].btc == pytest.approx(new_target)
    assert pf.venues["kraken"].btc == pytest.approx(new_target)
    assert pf.realized_pnl == pytest.approx(-fee_btc * mark)
    assert pf.rebalance_count == 1
    assert pf.rebalance_cost_total == pytest.approx(fee_btc * mark)


def test_rebalance_conserves_total_pnl_equals_delta_equity():
    """Invariante: tras el rebalanceo (a precio de referencia ÚNICO) total_pnl == delta_equity.
    El BTC total baja sólo por el fee quemado; el reparto entre venues es neutral en equity."""
    s = _settings()
    pf = Portfolio(s)
    btc0, quote0 = _total_btc(pf), _total_quote(pf)
    pf.venues["binance"].btc = 3.5
    pf.venues["kraken"].btc = 0.5
    mark = 130.0
    pf.rebalance(_uniform_books(mark), ts=1.0)
    summary = pf.pnl_summary(_uniform_books(mark))
    equity0 = quote0 + btc0 * mark
    assert summary["equity_usd"] - equity0 == pytest.approx(summary["total_pnl"])
    assert summary["total_pnl"] == pytest.approx(-0.0002 * mark)
    assert summary["rebalance"]["count"] == 1
    assert summary["rebalance"]["cost_total_usd"] == pytest.approx(0.0002 * mark)


def test_rebalance_none_without_valid_book():
    """Skew sobre el límite pero sin precio válido en ningún venue → no rebalancea a ciegas
    (None, sin coste): no inventamos precio."""
    s = _settings()
    pf = Portfolio(s)
    pf.venues["binance"].btc = 3.5
    pf.venues["kraken"].btc = 0.5
    assert pf.rebalance({}, ts=1.0) is None          # sin libros
    bad = _uniform_books(float("nan"))
    assert pf.rebalance(bad, ts=1.0) is None          # precios no finitos
    assert pf.rebalance_count == 0


def test_rebalance_single_venue_noop():
    """Con menos de 2 venues no hay desbalance cross-venue posible → None."""
    s = _settings()
    s.exchanges["kraken"].enabled = False
    pf = Portfolio(s)  # sólo binance
    pf.venues["binance"].btc = 10.0
    assert pf.rebalance(_uniform_books(), ts=1.0) is None


def test_rebalance_preserves_leg_risk_open_position():
    """El rebalanceo reparte sólo el BTC LIBRE (`btc − open_btc`): la posición abierta de
    leg risk NO se mueve on-chain y `open_btc` queda intacto (nunca descalzado del físico)."""
    s = _settings()
    pf = Portfolio(s)
    # binance: 3.5 BTC físico, de los cuales 1.0 es leg risk largo abierto → libre 2.5.
    pf.venues["binance"].btc = 3.5
    pf.venues["binance"].add_open_position(LegSide.buy, 1.0, 100.0)
    assert pf.venues["binance"].open_btc == pytest.approx(1.0)
    pf.venues["kraken"].btc = 0.5  # libre 0.5
    out = pf.rebalance(_uniform_books(100.0), ts=1.0)
    assert out is not None
    # Libre total 3.0; fee 0.0002 (binance envía); free_target = (3 − 0.0002)/2.
    free_target = (3.0 - 0.0002) / 2.0
    assert pf.venues["binance"].open_btc == pytest.approx(1.0)  # posición abierta intacta
    assert pf.venues["binance"].btc == pytest.approx(1.0 + free_target)  # open + libre
    assert pf.venues["kraken"].btc == pytest.approx(free_target)
    # El físico nunca queda por debajo de la posición abierta que respalda.
    assert pf.venues["binance"].btc >= pf.venues["binance"].open_btc


def test_rebalance_realized_honest_with_nonuniform_marks():
    """Con marks per-venue DISTINTOS, el `realized_pnl` carga SÓLO el fee (cargo honesto): el
    diferencial de marca entre venues NO entra al ledger realizado (sólo es remark de equity,
    acotado por el spread inter-venue)."""
    s = _settings()
    pf = Portfolio(s)
    pf.venues["binance"].btc = 3.5
    pf.venues["kraken"].btc = 0.5
    books = {
        "binance": _book("binance", bids=[(100.0, 50.0)], asks=[(100.0, 50.0)]),
        "kraken": _book("kraken", bids=[(110.0, 50.0)], asks=[(110.0, 50.0)]),
    }
    out = pf.rebalance(books, ts=1.0)
    assert out is not None
    ref = (100.0 + 110.0) / 2.0
    assert out["ref_mark"] == pytest.approx(ref)
    # Ledger honesto: realized = −fee·ref, sin el diferencial de marca.
    assert pf.realized_pnl == pytest.approx(-0.0002 * ref)


def test_rebalance_skipped_when_free_btc_nets_to_zero():
    """Largo+corto opuestos que netean ~0 de BTC libre: aunque el skew esté quebrado, no hay
    transferencia on-chain real que hacer → None (no inventamos coste ni `new_target` negativo)."""
    s = _settings()
    pf = Portfolio(s)
    pf.venues["binance"].btc = 5.0
    pf.venues["kraken"].btc = -5.0
    assert pf.inventory_skew()["breached"] is True
    assert pf.rebalance(_uniform_books(100.0), ts=1.0) is None
    assert pf.rebalance_count == 0


def test_reference_mark_mixed_venues_uses_valid_one():
    """`_reference_mark` ignora venues sin libro válido y promedia los válidos; con uno solo
    válido, ése es la referencia."""
    s = _settings()
    pf = Portfolio(s)
    pf.venues["binance"].btc = 3.5
    pf.venues["kraken"].btc = 0.5
    # kraken ausente del dict de libros → sólo binance es válido.
    books = {"binance": _book("binance", bids=[(100.0, 50.0)], asks=[(102.0, 50.0)])}
    out = pf.rebalance(books, ts=1.0)
    assert out is not None
    assert out["ref_mark"] == pytest.approx(101.0)  # mid de binance (100+102)/2


async def test_rebalancer_periodic_task_fires_once_then_idles():
    """La tarea periódica `Rebalancer` dispara el rebalanceo cuando hay drift y, tras
    equilibrar, deja de actuar (skew bajo límite) → exactamente 1 evento."""
    from types import SimpleNamespace

    from app.sim import Rebalancer

    s = _settings()
    s.rebalance_interval_ms = 5
    pf = Portfolio(s)
    pf.venues["binance"].btc = 3.5
    pf.venues["kraken"].btc = 0.5
    state = SimpleNamespace(
        portfolio=pf,
        detector=SimpleNamespace(books=_uniform_books(100.0)),
    )
    rb = Rebalancer(state, s)  # type: ignore[arg-type]
    task = asyncio.create_task(rb.run())
    await asyncio.sleep(0.05)   # varios ticks
    rb.stop()
    await asyncio.sleep(0.01)
    task.cancel()
    # Sólo 1 rebalanceo: tras el primero el skew queda bajo el límite (ticks posteriores no-op).
    assert pf.rebalance_count == 1


def test_unwind_execution_conserves_in_portfolio():
    """STORY-016: un `Execution` de UNWIND (dos legs en el MISMO venue de compra: compra +
    venta de vuelta) aplicado a la cartera conserva los balances y cumple la invariante
    `total_pnl == delta_equity` (con fee=0, conservación exacta). Cubre el caso —antes sin
    test— de aplicar un unwind a `Portfolio`, incluido el residual de leg risk largo."""
    s = _settings(
        exchanges={
            "binance": ExchangeConfig(
                id="binance", symbol="BTC/USDT", quote_ccy="USDT",
                fee_taker=0.0, withdrawal_btc=0.0, ob_limit=20,
                initial_btc=2.0, initial_quote=100_000.0,
            ),
            "kraken": ExchangeConfig(
                id="kraken", symbol="BTC/USD", quote_ccy="USD",
                fee_taker=0.0, withdrawal_btc=0.0, ob_limit=25,
                initial_btc=2.0, initial_quote=100_000.0,
            ),
        },
    )
    sim = ExecutionSimulator(s)
    # Compra 1.0@100; bids del venue de compra sólo 0.3@99 → unwind 0.3, residual 0.7 largo.
    buy = _book("binance", bids=[(99.0, 0.3)], asks=[(100.0, 5.0)])
    sell_t0 = _book("kraken", bids=[(110.0, 5.0)], asks=[(111.0, 5.0)])
    sell_t1 = _book("kraken", bids=[(99.5, 5.0)], asks=[(100.5, 5.0)])  # colapso → unwind
    ex = sim.simulate(_viable(), buy, sell_t0, sell_book_t1=sell_t1, ts=1.0)
    assert ex is not None and ex.unwound is True

    pf = Portfolio(s)
    btc0, quote0 = _total_btc(pf), _total_quote(pf)
    pf.apply_execution(ex)
    # BTC total: sólo cambia por el residual no deshecho (0.7 que quedó largo en binance).
    assert _total_btc(pf) - btc0 == pytest.approx(0.7)
    # Quote total baja sólo por el coste neto (fee=0): −1.0·100 (compra) +0.3·99 (unwind).
    assert _total_quote(pf) - quote0 == pytest.approx(-1.0 * 100.0 + 0.3 * 99.0)
    # Invariante: total_pnl == delta_equity. Libro de marca UNIFORME (bid=ask=M en ambos
    # venues) → equity inicial = quote0 + btc0·M, sin ambigüedad de lado de marca.
    mark = 130.0
    books = {
        "binance": _book("binance", bids=[(mark, 50.0)], asks=[(mark, 50.0)]),
        "kraken": _book("kraken", bids=[(mark, 50.0)], asks=[(mark, 50.0)]),
    }
    summary = pf.pnl_summary(books)
    equity0 = quote0 + btc0 * mark
    assert summary["equity_usd"] - equity0 == pytest.approx(summary["total_pnl"])
    assert summary["total_pnl"] == pytest.approx(
        summary["realized_pnl"] + summary["unrealized_pnl"]
    )


def test_sell_cross_long_to_short_open_position_marks_flat_at_trade_price():
    """Cruce LARGO→CORTO del leg risk: si dos executions dejan la posición abierta cruzando
    de signo, el coste base del tramo nuevo se asienta a SU precio de entrada (no al avg
    viejo). Tras cruzar, marcando al precio del último trade el unrealized del tramo nuevo
    es ~0 (no aparece pérdida/ganancia fantasma del cruce)."""
    s = _settings()
    pf = Portfolio(s)
    vb = pf.venues["binance"]
    # 1) Abre largo +0.6 @100 (leg risk de compra).
    vb.add_open_position(LegSide.buy, 0.6, 100.0)
    assert vb.open_btc == pytest.approx(0.6)
    # 2) Vende 1.0 @150 sobre la posición: cruza a corto −0.4. El remanente corto se asienta
    #    a 150 (precio de entrada del tramo que abre el corto), no al avg viejo de 100.
    vb.add_open_position(LegSide.sell, 1.0, 150.0)
    assert vb.open_btc == pytest.approx(-0.4)
    assert vb.open_cost_basis_usd == pytest.approx(-0.4 * 150.0)
    # Marcado a 150 (el precio del último trade): unrealized del corto recién abierto ~0.
    assert vb.unrealized(150.0) == pytest.approx(0.0)


def test_pnl_summary_invariant_holds_in_shape_test():
    """La igualdad total_pnl == realized + unrealized se mantiene como contrato del summary."""
    s = _settings()
    sim = ExecutionSimulator(s)
    pf = Portfolio(s)
    buy = _book("binance", bids=[(99.0, 50.0)], asks=[(100.0, 50.0)])
    sell = _book("kraken", bids=[(110.0, 50.0)], asks=[(111.0, 50.0)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)
    pf.apply_execution(ex)
    summary = pf.pnl_summary({"binance": buy, "kraken": sell})
    assert summary["total_pnl"] == pytest.approx(
        summary["realized_pnl"] + summary["unrealized_pnl"]
    )


# --- Guards de robustez (ramas de borde de VenueBalance/Portfolio) ---------

def test_move_physical_ignores_nonpositive_qty():
    """`move_physical` con qty <= 0 es no-op: no mueve balances (guard de robustez)."""
    s = _settings()
    pf = Portfolio(s)
    vb = pf.venues["binance"]
    btc0, quote0 = vb.btc, vb.quote
    vb.move_physical(LegSide.buy, 0.0, 100.0, 0.10)
    vb.move_physical(LegSide.sell, -1.0, 100.0, 0.10)
    assert vb.btc == pytest.approx(btc0)
    assert vb.quote == pytest.approx(quote0)


def test_add_open_position_ignores_nonpositive_qty_or_vwap():
    """`add_open_position` con qty<=0 o entry_vwap<=0 no abre posición (guard)."""
    s = _settings()
    pf = Portfolio(s)
    vb = pf.venues["binance"]
    vb.add_open_position(LegSide.buy, 0.0, 100.0)   # qty 0
    vb.add_open_position(LegSide.buy, 1.0, 0.0)     # vwap 0
    assert vb.open_btc == pytest.approx(0.0)
    assert vb.open_cost_basis_usd == pytest.approx(0.0)


def test_add_open_position_reduce_without_sign_cross_uses_avg_cost():
    """Reducir una posición SIN cruzar de signo retira coste base al coste MEDIO previo
    (rama 113-114). Largo +1.0@100 (coste 100), luego vende 0.4 → queda +0.6 y el coste
    base baja en 0.4·avg(100) = 40 → 60."""
    s = _settings()
    pf = Portfolio(s)
    vb = pf.venues["binance"]
    vb.add_open_position(LegSide.buy, 1.0, 100.0)
    assert vb.open_btc == pytest.approx(1.0)
    assert vb.open_cost_basis_usd == pytest.approx(100.0)
    vb.add_open_position(LegSide.sell, 0.4, 130.0)  # reduce sin cruzar signo
    assert vb.open_btc == pytest.approx(0.6)
    assert vb.open_cost_basis_usd == pytest.approx(60.0)  # 100 - 0.4·100 (coste MEDIO previo)


def test_apply_execution_rejects_unknown_venue_leg():
    """INVERTIDO (PRD-009 RF-002): un leg en un venue NO sembrado RECHAZA la ejecución
    completa — `False`, cero mutación (ni siquiera el leg conocido) y sin venue fantasma."""
    s = _settings()
    pf = Portfolio(s)
    fp0 = _fingerprint(pf)
    ex = _exec([
        _leg("binance", LegSide.buy, 1.0, 100.0, 0.0),
        _leg("desconocido", LegSide.sell, 1.0, 110.0, 0.0),
    ])
    assert pf.apply_execution(ex) is False
    assert "desconocido" not in pf.venues          # no se crea el venue fantasma
    assert _fingerprint(pf) == fp0                 # el leg conocido TAMPOCO se aplicó (atómico)


def test_mark_falls_back_to_valid_side_when_primary_invalid():
    """`_mark`: si el lado primario del largo (best_bid) es inválido (0), cae al ÚNICO lado
    válido restante (best_ask). Rama de respaldo 249-251."""
    s = _settings()
    pf = Portfolio(s)
    pf.venues["binance"].btc = 1.0  # largo → lado primario = best_bid
    # best_bid 0 (inválido como primario), best_ask válido → respaldo al ask.
    book = _book("binance", bids=[(0.0, 5.0)], asks=[(120.0, 5.0)])
    mark = pf._mark("binance", {"binance": book}, pf.venues["binance"].btc)
    assert mark == pytest.approx(120.0)


def test_mark_none_when_no_valid_price():
    """`_mark` devuelve None cuando ningún lado del libro es válido (precios corruptos):
    el llamador marca a 0 ese tramo. Rama final 252."""
    s = _settings()
    pf = Portfolio(s)
    book = _book("binance", bids=[(0.0, 5.0)], asks=[(float("nan"), 5.0)])
    assert pf._mark("binance", {"binance": book}, 1.0) is None
    # Sin libro para el venue → None.
    assert pf._mark("binance", {}, 1.0) is None


# --- PRD-009: apply_execution transaccional (gate de salida, tests 1-3 y 4b) ------------

def test_apply_execution_unknown_buy_venue_rejected_atomically():
    """Test 1 del gate: buy venue desconocido → `False` y fingerprint completo intacto
    (cero mutación, cero P&L, aunque `realized_pnl` viniera > 0)."""
    pf = Portfolio(_settings())
    fp0 = _fingerprint(pf)
    ex = _exec([
        _leg("fantasma", LegSide.buy, 1.0, 100.0, 0.1),
        _leg("kraken", LegSide.sell, 1.0, 110.0, 0.1),
    ], realized_pnl=9.8)
    assert pf.apply_execution(ex) is False
    assert _fingerprint(pf) == fp0
    assert "fantasma" not in pf.venues
    assert len(pf.equity_series) == 0


def test_apply_execution_unknown_sell_venue_rejected_atomically():
    """Test 2 del gate: sell venue desconocido → `False` y fingerprint completo intacto."""
    pf = Portfolio(_settings())
    fp0 = _fingerprint(pf)
    ex = _exec([
        _leg("binance", LegSide.buy, 1.0, 100.0, 0.1),
        _leg("fantasma", LegSide.sell, 1.0, 110.0, 0.1),
    ], realized_pnl=9.8)
    assert pf.apply_execution(ex) is False
    assert _fingerprint(pf) == fp0
    assert "fantasma" not in pf.venues


def test_apply_execution_unknown_leg_risk_venue_rejects_whole_execution():
    """Leg risk EFECTIVO apuntando a un venue ausente rechaza la ejecución completa
    (fase leg_risk de la validación): ni los legs válidos se aplican."""
    pf = Portfolio(_settings())
    fp0 = _fingerprint(pf)
    ex = _exec([
        _leg("binance", LegSide.buy, 1.5, 100.0, 0.0),
        _leg("kraken", LegSide.sell, 1.0, 110.0, 0.0),
    ], realized_pnl=5.0)
    assert ex.leg_risk_qty == pytest.approx(0.5)  # leg risk efectivo (buy sobre-llenado)
    ex.leg_risk_venue = "fantasma"
    assert pf.apply_execution(ex) is False
    assert _fingerprint(pf) == fp0


def test_apply_execution_rolls_back_on_second_leg_failure(monkeypatch):
    """Test 3 del gate: fallo inyectado al mutar la SEGUNDA pata → rollback del snapshot
    completo (todos los campos contables) y sin punto de equity."""
    from app.sim.inventory import VenueBalance

    pf = Portfolio(_settings())
    fp0 = _fingerprint(pf)
    orig = VenueBalance.move_physical
    calls = {"n": 0}

    def boom(self, side, qty, price, fee):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("fallo inyectado en la segunda pata")
        orig(self, side, qty, price, fee)

    monkeypatch.setattr(VenueBalance, "move_physical", boom)
    ex = _exec([
        _leg("binance", LegSide.buy, 1.0, 100.0, 0.1),
        _leg("kraken", LegSide.sell, 1.0, 110.0, 0.1),
    ], realized_pnl=9.8)
    assert pf.apply_execution(ex) is False
    assert calls["n"] == 2                       # la primera pata SÍ llegó a mutar
    assert _fingerprint(pf) == fp0               # ...y el rollback la restauró
    assert len(pf.equity_series) == 0


def test_apply_execution_rolls_back_on_leg_risk_failure(monkeypatch):
    """Test 3 del gate (variante leg risk): fallo inyectado en `add_open_position` tras
    mover ambas patas físicas → rollback completo, cero P&L."""
    from app.sim.inventory import VenueBalance

    pf = Portfolio(_settings())
    fp0 = _fingerprint(pf)

    def boom(self, side, qty, entry_vwap):
        raise RuntimeError("fallo inyectado en el leg risk")

    monkeypatch.setattr(VenueBalance, "add_open_position", boom)
    ex = _exec([
        _leg("binance", LegSide.buy, 1.5, 100.0, 0.0),
        _leg("kraken", LegSide.sell, 1.0, 110.0, 0.0),
    ], realized_pnl=5.0)
    assert pf.apply_execution(ex) is False
    assert _fingerprint(pf) == fp0
    assert len(pf.equity_series) == 0


def test_can_afford_false_when_buy_or_sell_venue_missing():
    """RF-001: `can_afford` devuelve False por separado con buy o sell venue ausente."""
    pf = Portfolio(_settings())
    assert pf.can_afford(_viable(buy="fantasma", sell="kraken")) is False
    assert pf.can_afford(_viable(buy="binance", sell="fantasma")) is False


def test_no_phantom_pnl_with_disabled_venue():
    """Test 4b del gate: reproducción del Problema del PRD — venue `enabled=false` no
    sembrado. La opp que lo usa NO es asequible (→ discarded insufficient_balance en vivo)
    y una aplicación FORZADA de su ejecución devuelve `False`: cero mutación, cero P&L."""
    s = _settings()
    s.exchanges["kraken"].enabled = False
    pf = Portfolio(s)                            # kraken no sembrado
    assert set(pf.venues) == {"binance"}
    opp = _viable(buy="binance", sell="kraken")
    assert pf.can_afford(opp) is False
    fp0 = _fingerprint(pf)
    ex = _exec([
        _leg("binance", LegSide.buy, 1.0, 100.0, 0.0),
        _leg("kraken", LegSide.sell, 1.0, 110.0, 0.0),
    ], realized_pnl=8.0)
    assert pf.apply_execution(ex) is False
    assert _fingerprint(pf) == fp0
    assert pf.realized_pnl == pytest.approx(0.0)
    assert len(pf.equity_series) == 0
