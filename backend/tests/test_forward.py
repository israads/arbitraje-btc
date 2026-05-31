"""Tests deterministas de la Proyección FORWARD (Monte Carlo + honestidad estadística).

Cubren: guard de muestra insuficiente, muestra claramente positiva, muestra net-negativa,
determinismo por semilla y rangos válidos de PSR/DSR (incluida la deflación con N grande).
"""
from __future__ import annotations

from app.models.projection import ForwardResult
from app.projection.forward import build_forward_projection


def _bands_monotonas(res: ForwardResult) -> bool:
    """Verifica que en cada paso se cumple P95 >= P75 >= P50 >= P25 >= P5."""
    b = res.bands
    return all(
        p95 >= p75 >= p50 >= p25 >= p5
        for p5, p25, p50, p75, p95 in zip(b.p5, b.p25, b.p50, b.p75, b.p95, strict=True)
    )


def test_muestra_vacia_no_revienta() -> None:
    """Muestra vacía -> available=False sin lanzar excepción."""
    res = build_forward_projection([])
    assert res.available is False
    assert res.n_trades == 0


def test_muestra_un_elemento_no_disponible() -> None:
    """Un solo trade (n<2) -> available=False."""
    res = build_forward_projection([1.0])
    assert res.available is False
    assert res.n_trades == 1


def test_muestra_constante_std_cero() -> None:
    """Std=0 (todos iguales) -> available=False, sin reventar."""
    res = build_forward_projection([2.0, 2.0, 2.0, 2.0])
    assert res.available is False


def test_muestra_positiva_clara() -> None:
    """Muestra con edge positivo claro -> prob_profit alto, sharpe>0, bandas monótonas."""
    pnls = [1.0, 2.0, 1.5, 0.8, 1.2, 2.1, 1.7, 0.9, 1.4, 1.6] * 5
    res = build_forward_projection(pnls, n_paths=2000, seed=42)

    assert res.available is True
    assert res.n_trades == 50
    assert res.sharpe_per_trade is not None and res.sharpe_per_trade > 0
    assert res.prob_profit is not None and res.prob_profit > 0.9
    assert res.terminal_p50 is not None and res.terminal_p50 > 0
    assert res.psr is not None and 0.0 <= res.psr <= 1.0
    assert _bands_monotonas(res)
    # block_mean es la heurística n^(1/3) acotada [2, n].
    assert res.block_mean is not None and 2.0 <= res.block_mean <= float(res.n_trades)
    # MinTRL alcanzable (SR>0).
    assert res.min_trl is not None and res.min_trl > 0
    # Drawdown reportado como magnitud positiva.
    assert res.max_dd_p50 is not None and res.max_dd_p50 >= 0
    assert res.max_dd_p95 is not None and res.max_dd_p95 >= res.max_dd_p50


def test_muestra_net_negativa() -> None:
    """Muestra con esperanza negativa -> prob_profit bajo, sharpe<0, MinTRL None."""
    pnls = [-2.0, 1.0, -1.5, -0.5, -2.2, 0.8, -1.8, -0.9, -1.1, 0.5] * 5
    res = build_forward_projection(pnls, n_paths=2000, seed=7)

    assert res.available is True
    assert res.sharpe_per_trade is not None and res.sharpe_per_trade < 0
    assert res.prob_profit is not None and res.prob_profit < 0.5
    assert res.min_trl is None  # SR <= 0 => no alcanzable
    assert res.psr is not None and 0.0 <= res.psr <= 1.0


def test_determinismo_misma_semilla() -> None:
    """Dos llamadas con la misma semilla -> bandas idénticas."""
    pnls = [0.5, -0.2, 1.3, 0.1, -0.6, 0.9, 0.4, -0.3, 1.1, 0.2] * 3
    a = build_forward_projection(pnls, n_paths=1500, seed=99)
    b = build_forward_projection(pnls, n_paths=1500, seed=99)

    assert a.bands.p50 == b.bands.p50
    assert a.bands.p5 == b.bands.p5
    assert a.bands.p95 == b.bands.p95
    assert a.terminal_p50 == b.terminal_p50
    assert a.prob_profit == b.prob_profit


def test_semillas_distintas_difieren() -> None:
    """Semillas distintas -> trayectorias (y por tanto bandas) distintas."""
    pnls = [0.5, -0.2, 1.3, 0.1, -0.6, 0.9, 0.4, -0.3, 1.1, 0.2] * 3
    a = build_forward_projection(pnls, n_paths=1500, seed=1)
    b = build_forward_projection(pnls, n_paths=1500, seed=2)
    assert a.bands.p50 != b.bands.p50


def test_psr_dsr_en_rango_y_dsr_deflactado() -> None:
    """PSR y DSR en [0,1]; con n_configs grande, DSR <= PSR (deflación por selección)."""
    pnls = [1.0, 2.0, 1.5, 0.8, 1.2, 2.1, 1.7, 0.9, 1.4, 1.6] * 5

    base = build_forward_projection(pnls, n_paths=1000, n_configs=1, seed=42)
    deflated = build_forward_projection(pnls, n_paths=1000, n_configs=1000, seed=42)

    for r in (base, deflated):
        assert r.psr is not None and 0.0 <= r.psr <= 1.0
        assert r.dsr is not None and 0.0 <= r.dsr <= 1.0

    # Con n_configs=1, DSR == PSR (SR0=0).
    assert base.dsr == base.psr
    # Con muchas configuraciones probadas, el DSR se deflacta por debajo del PSR.
    assert deflated.dsr is not None and base.psr is not None
    assert deflated.dsr <= base.psr


def test_horizon_grande_submuestrea_pasos() -> None:
    """Horizonte > 200 -> fan chart submuestreado (<= ~150 pasos), conservando extremos."""
    pnls = [0.3, -0.1, 0.5, 0.2, -0.4, 0.6] * 4
    res = build_forward_projection(pnls, n_paths=500, horizon=600, seed=3)

    assert res.available is True
    assert len(res.bands.step) <= 151
    assert res.bands.step[0] == 1
    assert res.bands.step[-1] == 600


def test_ruin_threshold_explicito() -> None:
    """Un ruin_threshold pequeño eleva prob_ruin frente a uno enorme."""
    pnls = [-1.0, 0.5, -0.8, 0.3, -1.2, 0.6, -0.9, 0.4, -1.1, 0.2] * 3
    bajo = build_forward_projection(pnls, n_paths=2000, ruin_threshold=1.0, seed=5)
    alto = build_forward_projection(pnls, n_paths=2000, ruin_threshold=1e9, seed=5)

    assert bajo.prob_ruin is not None and alto.prob_ruin is not None
    assert bajo.prob_ruin > alto.prob_ruin
    assert alto.prob_ruin == 0.0
