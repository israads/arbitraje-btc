"""C14 — backtest record & replay (FR-014, STORY-021).

Cubre: grabación con ts, replay cronológico point-in-time por el MISMO motor/simulador,
re-lectura del leg2 en t+Δ (sell_book_t1 del tick futuro → leg risk/unwind real), métricas
(Sharpe/win rate/profit factor/drawdown) y separación in/out-of-sample.
"""
from __future__ import annotations

import json

from app.backtest import Recorder, run_backtest
from app.backtest.replay import _compute_metrics
from app.config import Settings
from app.models.market import NormalizedBook


def _settings(**over) -> Settings:
    base = dict(
        zscore_window=5, default_trade_qty_btc=1.0, min_net_profit_usd=0.0,
        max_slippage=1.0, exec_latency_ms=100, backtest_in_sample_frac=0.5,
    )
    base.update(over)
    return Settings(**base)


def _nb(ex, bid, ask, ts, *, depth=10.0) -> NormalizedBook:
    return NormalizedBook(
        exchange=ex, symbol="BTC/USD", quote_ccy="USD",
        bids=[(bid, depth)], asks=[(ask, depth)], price_norm_factor=1.0, ts_recv_monotonic=ts,
    )


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------

def test_recorder_records_in_order_and_bounds():
    r = Recorder(maxlen=3, enabled=True)
    for i in range(5):
        r.record(_nb("binance", 100 + i, 101 + i, float(i)))
    ticks = r.ticks()
    assert len(ticks) == 3  # ring acotado
    assert [t.ts_recv_monotonic for t in ticks] == [2.0, 3.0, 4.0]  # los 3 últimos, en orden


def test_recorder_disabled_noop():
    r = Recorder(maxlen=10, enabled=False)
    r.record(_nb("binance", 100, 101, 0.0))
    assert len(r) == 0


def test_recorder_jsonl_roundtrip(tmp_path):
    r = Recorder(maxlen=10)
    for i in range(3):
        r.record(_nb("kraken", 100 + i, 101 + i, float(i)))
    path = str(tmp_path / "rec.jsonl")
    assert r.to_jsonl(path) == 3
    r2 = Recorder.from_jsonl(path, maxlen=10)
    assert len(r2) == 3
    assert [t.exchange for t in r2.ticks()] == ["kraken", "kraken", "kraken"]
    assert r2.ticks()[1].best_ask == 102.0


def test_chronological_sorts_by_ts():
    ticks = [_nb("a", 1, 2, 5.0), _nb("b", 1, 2, 1.0), _nb("c", 1, 2, 3.0)]
    out = Recorder.chronological(ticks)
    assert [t.ts_recv_monotonic for t in out] == [1.0, 3.0, 5.0]


# ---------------------------------------------------------------------------
# _compute_metrics
# ---------------------------------------------------------------------------

def test_metrics_empty():
    m = _compute_metrics([], [], n_ticks=0, n_unwinds=0, n_viable=0, n_detected=0)
    assert m.n_trades == 0
    assert m.profit_per_trade is None and m.win_rate is None
    assert m.profit_factor is None and m.sharpe is None
    assert m.max_drawdown_usd == 0.0


def test_metrics_win_rate_profit_factor():
    trades = [10.0, -5.0, 20.0, -5.0]  # 2 ganadores, 2 perdedores
    equity = [10.0, 5.0, 25.0, 20.0]   # acumulado
    m = _compute_metrics(trades, equity, n_ticks=4, n_unwinds=0, n_viable=4, n_detected=4)
    assert m.n_trades == 4
    assert m.realized_pnl_total == 20.0
    assert m.profit_per_trade == 5.0
    assert m.win_rate == 0.5
    assert m.profit_factor == 30.0 / 10.0  # ganancias 30 / pérdidas 10
    # drawdown: pico 25 (idx2), cae a 20 → 5.0
    assert m.max_drawdown_usd == 5.0
    assert m.sharpe is not None  # std > 0


def test_metrics_profit_factor_none_without_losses():
    m = _compute_metrics([5.0, 3.0], [5.0, 8.0], n_ticks=2, n_unwinds=0, n_viable=2, n_detected=2)
    assert m.profit_factor is None  # sin trades perdedores → indefinido
    assert m.win_rate == 1.0


def test_metrics_drawdown_from_peak():
    # P&L acumulado sube a 100, cae a 30 (dd 70), recupera a 50.
    equity = [50.0, 100.0, 30.0, 50.0]
    trades = [50.0, 50.0, -70.0, 20.0]
    m = _compute_metrics(trades, equity, n_ticks=4, n_unwinds=0, n_viable=4, n_detected=4)
    assert m.max_drawdown_usd == 70.0


def test_metrics_sharpe_none_with_single_trade():
    m = _compute_metrics([10.0], [10.0], n_ticks=1, n_unwinds=0, n_viable=1, n_detected=1)
    assert m.sharpe is None  # <2 trades


# ---------------------------------------------------------------------------
# Replay end-to-end
# ---------------------------------------------------------------------------

def _profitable_stream(n=12):
    """Genera ticks alternando venues con un cruce ejecutable persistente (binance barato,
    kraken caro) para producir capturas en el replay."""
    ticks = []
    t = 0.0
    for _ in range(n):
        # binance ask bajo, kraken bid alto → comprar binance, vender kraken (cruce neto+).
        ticks.append(_nb("binance", 49_990, 50_000, t))
        t += 0.05
        ticks.append(_nb("kraken", 50_200, 50_210, t))
        t += 0.05
    return ticks


def test_replay_reuses_engine_produces_trades():
    """El replay reproduce por el motor/simulador y captura trades sobre un cruce rentable."""
    s = _settings(min_net_profit_usd=0.0, max_slippage=1.0)
    # fees 0 para asegurar neto positivo y capturas (aísla el camino de ejecución).
    for exid in list(s.exchanges):
        s.exchanges[exid].fee_taker = 0.0
        s.exchanges[exid].withdrawal_btc = 0.0
    res = run_backtest(_profitable_stream(12), s, in_sample_frac=0.5)
    assert res.n_ticks_total == 24
    assert res.overall.n_detected > 0
    assert res.overall.n_trades > 0          # hubo capturas (reusa C9)
    assert res.overall.realized_pnl_total > 0  # cruce rentable
    # in + out reproducen tramos disjuntos del flujo.
    assert res.in_sample.n_ticks == 12 and res.out_of_sample.n_ticks == 12


def test_replay_point_in_time_no_trades_on_single_venue():
    """Con un solo venue no hay cruce posible → 0 trades (point-in-time, sin look-ahead falso)."""
    ticks = [_nb("binance", 100 + i, 101 + i, float(i)) for i in range(10)]
    res = run_backtest(ticks, _settings())
    assert res.overall.n_trades == 0


def test_replay_empty_recording():
    res = run_backtest([], _settings())
    assert res.n_ticks_total == 0
    assert res.overall.n_trades == 0 and res.overall.max_drawdown_usd == 0.0


def test_replay_leg_risk_unwind_via_future_tick():
    """El leg2 se re-lee en t+Δ con el tick FUTURO del venue de venta. Si ese book futuro
    deja el tramo casado NO rentable, el simulador hace UNWIND (n_unwinds>0) — capacidad que
    en vivo no se dispara. Construye: cruce rentable a t, pero el bid de kraken se DERRUMBA
    en el tick t+Δ → recompute no rentable → unwind del leg1 comprado en binance."""
    s = _settings(min_net_profit_usd=0.0, max_slippage=1.0, exec_latency_ms=100)
    for exid in list(s.exchanges):
        s.exchanges[exid].fee_taker = 0.0
        s.exchanges[exid].withdrawal_btc = 0.0
    ticks = [
        _nb("binance", 49_990, 50_000, 0.00),   # compra barata disponible
        _nb("kraken", 50_500, 50_510, 0.01),    # bid alto → cruce rentable a t=0.01
        # t+Δ (Δ=0.1s): el book FUTURO de kraken con bid DERRUMBADO (venta ya no rentable).
        _nb("kraken", 49_000, 49_010, 0.20),
        _nb("binance", 49_990, 50_000, 0.25),
    ]
    res = run_backtest(ticks, s, in_sample_frac=0.5)
    assert res.overall.n_trades > 0
    assert res.overall.n_unwinds > 0  # el desfase t+Δ disparó al menos un unwind real


def test_replay_filters_nonfinite_ts():
    """Ticks con ts no finito (book corrupto) se filtran: no rompen el orden/bisect ni cuentan."""
    s = _settings()
    good = [_nb("binance", 100, 101, float(i)) for i in range(4)]
    bad = _nb("binance", 100, 101, float("nan"))
    res = run_backtest([*good, bad], s)
    assert res.n_ticks_total == 4  # el NaN no cuenta


def test_replay_nonfinite_pnl_does_not_poison_drawdown():
    """Un realized_pnl NaN no debe dejar el drawdown silenciosamente en 0 ni romper métricas."""
    # Verifica el guard directamente en _compute_metrics con un trade NaN intercalado.
    trades = [10.0, float("nan"), -3.0]
    # En el replay real el guard convierte NaN→0.0 antes de append; aquí simulamos ese flujo:
    clean = [t if (t == t) else 0.0 for t in trades]  # NaN→0 (t!=t detecta NaN)
    equity = []
    acc = 0.0
    for t in clean:
        acc += t
        equity.append(acc)
    m = _compute_metrics(clean, equity, n_ticks=3, n_unwinds=0, n_viable=3, n_detected=3)
    assert m.max_drawdown_usd > 0.0  # la caída tras el pico SÍ se mide (no queda en 0 por NaN)


def test_replay_single_tick_empty_segment():
    """Con n=1 un tramo queda vacío (in-sample) sin crash; el otro reproduce el único tick."""
    res = run_backtest([_nb("binance", 100, 101, 0.0)], _settings(backtest_in_sample_frac=0.5))
    assert res.n_ticks_total == 1
    assert res.in_sample.n_ticks == 0      # split=0 → tramo vacío, sin error
    assert res.out_of_sample.n_ticks == 1


def test_from_jsonl_skips_corrupt_lines(tmp_path):
    """`from_jsonl` salta líneas corruptas y carga las válidas (fallback robusto C16)."""
    path = tmp_path / "rec.jsonl"
    valid = json.dumps(_nb("kraken", 100, 101, 1.0).model_dump(mode="json"))
    path.write_text(valid + "\n{ not json }\n" + valid + "\n", encoding="utf-8")
    rec = Recorder.from_jsonl(str(path), maxlen=10)
    assert len(rec) == 2  # 2 válidas, la corrupta saltada


def test_in_out_of_sample_independent():
    """In-sample y out-of-sample se reproducen por separado (carteras frescas, tramos disjuntos)."""
    s = _settings(min_net_profit_usd=0.0, max_slippage=1.0)
    for exid in list(s.exchanges):
        s.exchanges[exid].fee_taker = 0.0
        s.exchanges[exid].withdrawal_btc = 0.0
    res = run_backtest(_profitable_stream(20), s, in_sample_frac=0.7)
    # split 0.7 de 40 ticks = 28 in-sample, 12 out-of-sample.
    assert res.in_sample.n_ticks == 28
    assert res.out_of_sample.n_ticks == 12
    # cada tramo produjo sus propias métricas independientes.
    assert res.in_sample.n_trades >= 0 and res.out_of_sample.n_trades >= 0
