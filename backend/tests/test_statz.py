"""C5 — arbitraje estadístico z-score del spread log entre venues (FR-006, STORY-019).

Cubre: spread = ln(mid_B)-ln(mid_A), z causal con ddof=0, máquina de estados
armed→fire/stand-down→re-arm con los tres umbrales (open/close/stop), dirección
por signo de z, exclusión de stale/degenerado, ventana incompleta, y la integración
con el evaluador de neto (validación del cruce ejecutable, AC#4).

NOTA algebraica: con población (ddof=0), ventana W y UN solo outlier, el z máximo del
outlier es sqrt(W-1) (el propio outlier infla la std). Por eso los tests de la máquina de
estados usan W=10 (un salto da z=3.0 exacto) con umbrales bien separados del borde, y los
tests de matemática/integración usan z_open=1.0 para que el z computado dispare sin pelear
con ese techo.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pytest

from app.config import Settings
from app.engine import NetEvaluator, StatZDetector
from app.models.enums import DiscardReason, OpportunityStatus, Strategy
from app.models.market import NormalizedBook


def _settings(**over) -> Settings:
    base = dict(zscore_window=5, z_open=2.0, z_close=0.5, z_stop=3.0, staleness_ms=750)
    base.update(over)
    return Settings(**base)


def _nb(ex: str, bid: float, ask: float, ts: float) -> NormalizedBook:
    return NormalizedBook(
        exchange=ex, symbol="BTC/USD", quote_ccy="USD",
        bids=[(bid, 5.0)], asks=[(ask, 5.0)], price_norm_factor=1.0, ts_recv_monotonic=ts,
    )


def _feed(d: StatZDetector, books: dict, ex: str, bid: float, ask: float, ts: float):
    """Actualiza el book de `ex` en `books` (espejo de SpatialDetector.books) y observa."""
    nb = _nb(ex, bid, ask, ts)
    books[ex] = nb
    return d.on_book(nb, books)


def _last_fire(out_iter):
    """Devuelve la última señal disparada de una lista de listas, o None."""
    last = None
    for out in out_iter:
        if out:
            last = out[0]
    return last


# ---------------------------------------------------------------------------
# Matemática del z-score
# ---------------------------------------------------------------------------

def test_no_signal_until_window_full():
    """Con ventana W=5, no hay señal hasta acumular 5 observaciones del par."""
    d = StatZDetector(_settings())
    books: dict = {}
    t = time.monotonic()
    _feed(d, books, "kraken", 100.0, 100.2, t)
    for i in range(4):  # 4 observaciones del par binance-kraken (binance dispara el par)
        opps = _feed(d, books, "binance", 100.0 + i * 0.01, 100.2 + i * 0.01, t)
        assert opps == [], f"no debe disparar con ventana incompleta (obs {i+1})"


def test_zscore_matches_numpy_ddof0_and_direction():
    """El z disparado coincide con (spread-mean)/std (ddof=0) sobre la ventana causal,
    y la dirección: spread alto (z>0) → vender en el venue 'b' (mid alto), comprar en 'a'."""
    s = _settings(zscore_window=5, z_open=1.0)  # z_open<2 para que el z≈2 dispare sin borde
    d = StatZDetector(s)
    books: dict = {}
    t = time.monotonic()
    _feed(d, books, "kraken", 100.0, 100.2, t)  # mid_kraken=100.1 estable
    # par ordenado (a=binance, b=kraken): spread = ln(mid_kraken) - ln(mid_binance).
    # mid_binance cae fuerte al final → spread alto → z>0 → vender kraken (b), comprar binance (a).
    binance_mids = [100.10, 100.11, 100.10, 100.12, 99.50]
    opp = _last_fire(_feed(d, books, "binance", m - 0.1, m + 0.1, t) for m in binance_mids)

    assert opp is not None, "el blow-out debe disparar una señal"
    assert opp.strategy == Strategy.stat_z
    assert opp.status == OpportunityStatus.detected
    assert opp.z_score is not None and opp.z_score > 0
    assert opp.buy_venue == "binance" and opp.sell_venue == "kraken"
    assert opp.id.startswith("statz-")
    assert opp.latency_ms is not None and opp.latency_ms >= 0

    spreads = [math.log(100.1) - math.log(m) for m in binance_mids]
    arr = np.array(spreads)
    expected_z = (spreads[-1] - arr.mean()) / arr.std()  # numpy ddof=0
    assert opp.z_score == pytest.approx(expected_z, rel=1e-9)


def test_direction_negative_z():
    """spread bajo (z<0) → mid_a (binance) caro → comprar en kraken (b), vender en binance (a)."""
    d = StatZDetector(_settings(zscore_window=5, z_open=1.0))
    books: dict = {}
    t = time.monotonic()
    _feed(d, books, "kraken", 100.0, 100.2, t)  # mid 100.1
    binance_mids = [100.10, 100.11, 100.10, 100.12, 100.80]  # sube fuerte → spread baja
    opp = _last_fire(_feed(d, books, "binance", m - 0.1, m + 0.1, t) for m in binance_mids)
    assert opp is not None and opp.z_score < 0
    assert opp.buy_venue == "kraken" and opp.sell_venue == "binance"


# ---------------------------------------------------------------------------
# Máquina de estados: open / close (re-arm) / stop / anti-flood (W=10 → z_jump=3.0)
# ---------------------------------------------------------------------------

def _flat(d, books, t, n):
    """Alimenta `n` observaciones del par binance-kraken con spread 0 (mids iguales 100.1)."""
    _feed(d, books, "kraken", 100.0, 100.2, t)
    for _ in range(n):
        _feed(d, books, "binance", 100.0, 100.2, t)


def test_fires_once_per_blowout_no_flood():
    """Estando armado, un blow-out sostenido dispara UNA sola señal (no una por tick)."""
    # W=10: un único salto da z=sqrt(9)=3.0. z_open=2.0, z_stop=5.0 → 3.0 dispara limpio.
    d = StatZDetector(_settings(zscore_window=10, z_open=2.0, z_stop=5.0))
    books: dict = {}
    t = time.monotonic()
    _flat(d, books, t, 9)  # ventana llena de ceros (std=0 → no dispara), par armado
    fires = sum(len(_feed(d, books, "binance", 99.4, 99.6, t)) for _ in range(4))
    assert fires == 1, "debe disparar exactamente una vez por blow-out (anti-flood)"


def test_rearm_after_close_then_fire_again():
    """Tras disparar y desarmar, sólo re-arma cuando |z|<z_close; entonces dispara de nuevo."""
    d = StatZDetector(_settings(zscore_window=10, z_open=2.0, z_stop=5.0, z_close=0.5))
    books: dict = {}
    t = time.monotonic()
    _flat(d, books, t, 9)
    assert len(_feed(d, books, "binance", 99.4, 99.6, t)) == 1  # 1er disparo → desarmado
    # Periodo largo cerca de la media: el salto viejo envejece y |z| cae bajo z_close → re-arma.
    for _ in range(15):
        _feed(d, books, "binance", 100.0, 100.2, t)
    fired_again = sum(len(_feed(d, books, "binance", 99.4, 99.6, t)) for _ in range(4))
    assert fired_again == 1, "debe re-armarse y disparar de nuevo en un segundo blow-out"


def test_stop_regime_does_not_open():
    """|z| >= z_stop (relación rota) NO dispara: stand-down."""
    # z_stop=2.5 < z=3.0 del salto → cae en zona de stop, no abre.
    d = StatZDetector(_settings(zscore_window=10, z_open=1.5, z_stop=2.5))
    books: dict = {}
    t = time.monotonic()
    _flat(d, books, t, 9)
    out = _feed(d, books, "binance", 80.0, 80.2, t)  # salto brutal → z=3.0 >= z_stop
    assert out == [], "en régimen roto (|z|>=z_stop) no se abre posición"


def test_stop_consumes_armed_no_fire_until_rearm():
    """Tras un stand-down por stop, no dispara aunque |z| baje a la zona de open, hasta re-armar."""
    d = StatZDetector(_settings(zscore_window=10, z_open=1.5, z_stop=2.5, z_close=0.5))
    books: dict = {}
    t = time.monotonic()
    _flat(d, books, t, 9)
    assert _feed(d, books, "binance", 80.0, 80.2, t) == []  # stop → desarmado
    # Inmediatamente otro salto que daría z de open: no debe disparar (sigue desarmado).
    # (el salto viejo aún en ventana; el nuevo no re-arma porque |z| no baja de z_close)
    out = _feed(d, books, "binance", 99.4, 99.6, t)
    assert out == [], "tras stop, requiere re-armar (|z|<z_close) antes de volver a abrir"


# ---------------------------------------------------------------------------
# Robustez: degenerado, stale, sin mid, un solo venue
# ---------------------------------------------------------------------------

def test_degenerate_zero_std_no_signal():
    """Spread constante (std=0) → z indefinido → ninguna señal, sin crash."""
    d = StatZDetector(_settings(zscore_window=5))
    books: dict = {}
    t = time.monotonic()
    _feed(d, books, "kraken", 100.0, 100.2, t)
    out_all = []
    for _ in range(8):
        out_all += _feed(d, books, "binance", 100.0, 100.2, t)  # mids idénticos → spread constante
    assert out_all == []


def test_stale_venue_excluded():
    """Si la contraparte está stale (book viejo > staleness_ms), el par no produce observación."""
    d = StatZDetector(_settings(zscore_window=3, staleness_ms=750))
    books: dict = {}
    t = time.monotonic()
    books["kraken"] = _nb("kraken", 100.0, 100.2, t - 1.0)  # 1s atrás > 750ms
    out = _feed(d, books, "binance", 99.0, 99.2, t)
    assert out == []


def test_stale_trigger_excluded():
    """Si el propio trigger está stale, no aporta observación (corta temprano)."""
    d = StatZDetector(_settings(zscore_window=3, staleness_ms=750))
    books: dict = {}
    t = time.monotonic()
    _feed(d, books, "kraken", 100.0, 100.2, t)
    stale = _nb("binance", 99.0, 99.2, t - 2.0)
    books["binance"] = stale
    assert d.on_book(stale, books) == []


def test_no_mid_book_excluded():
    """Un book sin lados (best_bid/ask None) no aporta mid y se excluye del cómputo."""
    d = StatZDetector(_settings(zscore_window=3))
    books: dict = {}
    t = time.monotonic()
    books["kraken"] = NormalizedBook(
        exchange="kraken", symbol="BTC/USD", quote_ccy="USD",
        bids=[], asks=[], price_norm_factor=1.0, ts_recv_monotonic=t,
    )
    assert _feed(d, books, "binance", 99.0, 99.2, t) == []


def test_three_venues_independent_pairs():
    """Con 3 venues (ruta de producción), un tick genera observaciones para los 2 pares
    que lo contienen; cada par mantiene su propia ventana/estado y dispara por separado."""
    d = StatZDetector(_settings(zscore_window=5, z_open=1.0, z_stop=10.0))
    books: dict = {}
    t = time.monotonic()
    # coinbase y kraken estables y MUY cerca entre sí; binance diverge contra ambos.
    _feed(d, books, "kraken", 100.00, 100.10, t)    # mid 100.05
    _feed(d, books, "coinbase", 100.01, 100.11, t)  # mid 100.06
    fired: list = []
    for m in [100.05, 100.06, 100.05, 100.07, 98.50]:  # binance cae al final
        fired += _feed(d, books, "binance", m - 0.05, m + 0.05, t)
    # binance forma par con kraken Y con coinbase: ambos deben disparar (spread similar).
    pairs = {(o.buy_venue, o.sell_venue) for o in fired}
    assert ("binance", "kraken") in pairs
    assert ("binance", "coinbase") in pairs
    # El par kraken-coinbase (ambos estables) NO debe disparar: su spread casi no varía.
    assert not any(
        {o.buy_venue, o.sell_venue} == {"kraken", "coinbase"} for o in fired
    )


def test_threshold_boundary_z_equal_open_fires():
    """En el borde exacto |z|==z_open dispara (la condición de no-disparo es estricta `<`).

    W=5 con 4 ceros + 1 salto da z_outlier = sqrt(W-1) = 2.0 exacto; con z_open=2.0 debe
    disparar (frontera inclusiva por diseño)."""
    d = StatZDetector(_settings(zscore_window=5, z_open=2.0, z_stop=10.0))
    books: dict = {}
    t = time.monotonic()
    _feed(d, books, "kraken", 100.0, 100.2, t)
    fired: list = []
    for _ in range(4):
        fired += _feed(d, books, "binance", 100.0, 100.2, t)  # 4 spreads = 0
    fired += _feed(d, books, "binance", 99.0, 99.2, t)        # 5º: salto → z=sqrt(4)=2.0
    assert len(fired) == 1
    assert fired[0].z_score == pytest.approx(2.0, rel=1e-9)


def test_single_venue_no_pair():
    """Con un único venue no hay par → nunca señal."""
    d = StatZDetector(_settings(zscore_window=3))
    books: dict = {}
    t = time.monotonic()
    out_all = []
    for i in range(6):
        out_all += _feed(d, books, "binance", 100.0 + i, 100.2 + i, t)
    assert out_all == []


# ---------------------------------------------------------------------------
# Integración con el evaluador de neto (AC#4: validar cruce ejecutable)
# ---------------------------------------------------------------------------

def _fire_signal(s: Settings):
    """Helper: dispara una señal z>0 (buy=binance, sell=kraken) y la devuelve."""
    d = StatZDetector(s)
    books: dict = {}
    t = time.monotonic()
    _feed(d, books, "kraken", 100.0, 100.2, t)
    opp = _last_fire(
        _feed(d, books, "binance", m - 0.1, m + 0.1, t)
        for m in [100.10, 100.11, 100.10, 100.12, 99.50]
    )
    return opp, t


def test_signal_validated_by_net_evaluator_discarded_when_not_executable():
    """Una señal z disparada que NO es un cruce ejecutable → discarded(not_profitable_fees).
    El z-score sólo da la dirección; la viabilidad la decide el neto (reusa FR-005)."""
    s = _settings(zscore_window=5, z_open=1.0)
    opp, t = _fire_signal(s)
    assert opp is not None
    ev = NetEvaluator(s)
    buy_book = _nb("binance", 99.4, 101.0, t)   # ask alto: comprar caro
    sell_book = _nb("kraken", 99.0, 100.2, t)   # bid bajo: vender barato
    ev.evaluate(opp, buy_book, sell_book)
    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.not_profitable_fees
    assert opp.z_score is not None  # el z se preserva tras la evaluación neta


def test_signal_can_be_viable_when_executable_net_positive():
    """Si la señal z coincide con un cruce ejecutable de neto positivo (fees=0), → viable."""
    s = _settings(zscore_window=5, z_open=1.0, min_net_profit_usd=0.0)
    for exid in list(s.exchanges):  # fees 0 para aislar la lógica de cruce
        s.exchanges[exid].fee_taker = 0.0
        s.exchanges[exid].withdrawal_btc = 0.0
    opp, t = _fire_signal(s)
    assert opp is not None and opp.buy_venue == "binance" and opp.sell_venue == "kraken"
    ev = NetEvaluator(s)
    buy_book = _nb("binance", 99.8, 100.0, t)   # compra @100.0
    sell_book = _nb("kraken", 101.0, 101.2, t)  # vende @101.0 → cruce neto+
    ev.evaluate(opp, buy_book, sell_book)
    assert opp.status == OpportunityStatus.viable
    assert opp.net_pnl is not None and opp.net_pnl > 0
    assert opp.z_score is not None
