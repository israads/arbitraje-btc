"""Tests de la Capacity Curve (curva de capacidad)."""
from __future__ import annotations

from app.models.projection import CapacityResult
from app.projection.capacity import build_capacity_curve


def test_capacity_demo_shape() -> None:
    """La curva demo no está vacía y tiene fee_bps coherente."""
    res = build_capacity_curve(mode="demo")
    assert isinstance(res, CapacityResult)
    assert res.mode == "demo"
    assert res.points
    # fee VIP2 por defecto = 0.0004 -> 4 bps
    assert res.fee_bps == 4.0


def test_capacity_q_star_positivo() -> None:
    """En demo existe un Q* óptimo positivo con edge definido."""
    res = build_capacity_curve(mode="demo")
    assert res.q_star_btc is not None
    assert res.q_star_btc > 0
    assert res.q_star_edge_usd is not None


def test_capacity_concavidad() -> None:
    """El edge en Q* supera al de un Q diminuto y al de un Q enorme."""
    res = build_capacity_curve(mode="demo")
    assert res.q_star_edge_usd is not None
    edge_min = res.points[0].edge_total_usd
    edge_max_q = res.points[-1].edge_total_usd
    assert res.q_star_edge_usd >= edge_min
    assert res.q_star_edge_usd >= edge_max_q
    # la curva efectivamente cae tras el pico (no es monótona creciente)
    assert edge_max_q < res.q_star_edge_usd


def test_capacity_marginal_decreciente() -> None:
    """El edge marginal por BTC decrece en general (curva cóncava).

    La derivada discreta del tramo profundo debe ser menor que la del tramo
    inicial: a más Q, cada BTC extra aporta menos (o destruye) edge. Se compara
    la media de la primera mitad contra la media de la segunda mitad para evitar
    ruido por niveles discretos del libro.
    """
    res = build_capacity_curve(mode="demo")
    marginals = [p.edge_marginal_per_btc for p in res.points]
    half = len(marginals) // 2
    first_half = sum(marginals[:half]) / half
    second_half = sum(marginals[half:]) / (len(marginals) - half)
    assert first_half > second_half
    # el marginal del tramo más profundo es claramente negativo (edge cae)
    assert marginals[-1] < 0.0


def test_capacity_hard_capacity_tras_q_star() -> None:
    """Si hay hard capacity, está por encima de Q*."""
    res = build_capacity_curve(mode="demo")
    if res.hard_capacity_btc is not None:
        assert res.q_star_btc is not None
        assert res.hard_capacity_btc > res.q_star_btc


def test_capacity_throughput_igual_a_edge_star() -> None:
    """El throughput por oportunidad coincide con el edge en Q*."""
    res = build_capacity_curve(mode="demo")
    assert res.throughput_usd_per_opp == res.q_star_edge_usd


def test_capacity_sqrt_overlay_creciente() -> None:
    """El overlay square-root es no negativo y crece con Q."""
    res = build_capacity_curve(mode="demo")
    impacts = [p.sqrt_impact_usd for p in res.points]
    assert all(i is not None and i >= 0 for i in impacts)
    vals = [i for i in impacts if i is not None]
    assert vals[-1] > vals[0]


def test_capacity_live_falls_back_to_demo() -> None:
    """live sin books vivos cae a demo y lo documenta."""
    res = build_capacity_curve(mode="live", books=None)
    assert res.mode == "demo"
    assert "demo" in res.notes


def test_capacity_fee_override() -> None:
    """Un fee explícito se refleja en fee_bps."""
    res = build_capacity_curve(mode="demo", fee=0.0016)
    assert res.fee_bps == 16.0


def test_capacity_determinismo() -> None:
    """Dos llamadas idénticas devuelven el mismo resultado."""
    a = build_capacity_curve(mode="demo")
    b = build_capacity_curve(mode="demo")
    assert a.model_dump() == b.model_dump()
