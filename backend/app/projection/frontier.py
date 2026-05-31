"""Capa 1 — Break-even Frontier v2 (Execution-Conditioned).

Barre una rejilla **tamaño (BTC) × fee tier** y calcula, con la MISMA aritmética del pipeline
(`engine.cost_model`), el edge neto/BTC de cada celda, su coste dominante, su `P_survive` (prob.
de sobrevivir la latencia) y su Expected Capturable Edge.

Dos modos:
  · `demo`  — cross representativo fijo (determinista, tests, fallback de demo, narrativa estable).
  · `live`  — construido desde los `NormalizedBook` reales: ruta de mayor spread.

Fees: en `demo`, una rejilla de tiers VIP0..VIP4; en `live`, el fee real del par de venues + la
misma rejilla como what-if. Eje de tamaños ADAPTATIVO (F2): se siembran tamaños redondos + los
quiebres reales de profundidad del libro. `best` expone 3 óptimos (F3).
"""
from __future__ import annotations

from ..config import Settings
from ..engine.cost_model import compute_net
from ..models.market import NormalizedBook
from ..models.projection import (
    FeeTier,
    FrontierBest,
    FrontierBestCell,
    FrontierResult,
)
from .survival import DEFAULT_SIGMA_USD_PER_SQRT_S, expected_capturable_edge

# --- Cross representativo (libro normalizado a USD, profundidad decreciente por nivel) ---
_BUY_ASKS: list[tuple[float, float]] = [
    (70_000.0, 0.30), (70_010.0, 0.50), (70_025.0, 1.00),
    (70_050.0, 2.00), (70_090.0, 3.00), (70_160.0, 5.00),
]
_SELL_BIDS: list[tuple[float, float]] = [
    (70_090.0, 0.30), (70_080.0, 0.50), (70_065.0, 1.00),
    (70_040.0, 2.00), (70_000.0, 3.00), (69_930.0, 5.00),
]
_WD_BTC_DEMO = 0.0003  # retiro on-chain por trade (wd_buy + wd_sell) del cross representativo

_FEE_TIERS: list[tuple[str, float]] = [
    ("VIP0", 0.0010), ("VIP1", 0.0007), ("VIP2", 0.0004), ("VIP3", 0.0002), ("VIP4", 0.0001),
]
_DEFAULT_SIZES: list[float] = [0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0]
# Latencia representativa para P_survive en demo (ms): orden de la deriva intra-ventana.
_DEMO_LATENCY_MS = 2_000.0


def _adaptive_sizes(
    asks: list[tuple[float, float]], bids: list[tuple[float, float]]
) -> list[float]:
    """Eje de tamaños (F2): tamaños redondos + quiebres reales de profundidad (cumsum de cada
    libro), acotado a la liquidez disponible. Ordenado, sin duplicados, máx. ~10 valores."""
    cap = min(
        sum(q for _, q in asks if q > 0.0),
        sum(q for _, q in bids if q > 0.0),
    )
    if cap <= 0.0:
        return []
    breaks: set[float] = set()
    for levels in (asks, bids):
        acc = 0.0
        for _price, qty in levels:
            if qty <= 0.0:
                continue
            acc += qty
            if acc < cap - 1e-9:
                breaks.add(round(acc, 6))
    for s in _DEFAULT_SIZES:
        if s < cap - 1e-9:
            breaks.add(s)
    breaks.add(round(cap, 6))
    sizes = sorted(b for b in breaks if b > 0.0)
    if len(sizes) > 10:  # submuestreo uniforme conservando extremos
        idx = [round(i * (len(sizes) - 1) / 9) for i in range(10)]
        sizes = sorted({sizes[i] for i in idx})
    return sizes


def _best_route(
    books: dict[str, NormalizedBook],
) -> tuple[str, str, NormalizedBook, NormalizedBook] | None:
    """Elige (buy_venue, sell_venue) con el mayor spread normalizado (mejor bid − mejor ask)."""
    live = {
        name: b for name, b in books.items()
        if b.best_ask is not None and b.best_bid is not None
        and b.best_ask > 0.0 and b.best_bid > 0.0
    }
    best: tuple[float, str, str] | None = None
    for buy_name, buy_b in live.items():
        for sell_name, sell_b in live.items():
            if buy_name == sell_name:
                continue
            ask = buy_b.best_ask
            bid = sell_b.best_bid
            if ask is None or bid is None:
                continue
            spread = bid - ask
            if best is None or spread > best[0]:
                best = (spread, buy_name, sell_name)
    if best is None:
        return None
    _, buy_name, sell_name = best
    return buy_name, sell_name, live[buy_name], live[sell_name]


def build_frontier(
    settings: Settings | None = None,
    books: dict[str, NormalizedBook] | None = None,
    *,
    mode: str = "demo",
    latency_ms: float | None = None,
    sigma_usd_per_sqrt_s: float = DEFAULT_SIGMA_USD_PER_SQRT_S,
) -> FrontierResult:
    """Construye la frontier. `mode='live'` requiere `books`; si no hay ruta viva, cae a demo."""
    route: dict[str, str] | None = None
    asof: float | None = None
    asks, bids = _BUY_ASKS, _SELL_BIDS
    wd_btc = _WD_BTC_DEMO
    lat = latency_ms if latency_ms is not None else _DEMO_LATENCY_MS

    if mode == "live":
        picked = _best_route(books) if books else None
        if picked is not None:
            buy_name, sell_name, buy_b, sell_b = picked
            asks, bids = buy_b.asks, sell_b.bids
            route = {"buy": buy_name, "sell": sell_name, "symbol": buy_b.symbol}
            asof = max(buy_b.ts_recv_monotonic, sell_b.ts_recv_monotonic)
            wd_btc = 0.0
            if settings is not None:
                bcfg = settings.exchanges.get(buy_name)
                scfg = settings.exchanges.get(sell_name)
                wd = (bcfg.withdrawal_btc if bcfg else 0.0) + (scfg.withdrawal_btc if scfg else 0.0)
                wd_btc = wd / settings.expected_trades_per_rebalance
                lat = latency_ms if latency_ms is not None else float(settings.exec_latency_ms)
        else:
            mode = "demo"  # sin books ni ruta viva → fallback honesto

    sizes = _adaptive_sizes(asks, bids) if mode == "live" else list(_DEFAULT_SIZES)
    if not sizes:
        sizes = list(_DEFAULT_SIZES)

    matrix: list[list[float | None]] = []
    net_usd: list[list[float | None]] = []
    psurv: list[list[float | None]] = []
    eedge: list[list[float | None]] = []
    depth_limited: list[list[bool]] = []
    dominant: list[list[str]] = []

    best_unit: FrontierBestCell | None = None
    best_total: FrontierBestCell | None = None
    best_risk: FrontierBestCell | None = None

    top_ask = asks[0][0] if asks else None
    top_bid = bids[0][0] if bids else None

    for _label, fee in _FEE_TIERS:
        r_npb: list[float | None] = []
        r_net: list[float | None] = []
        r_ps: list[float | None] = []
        r_ee: list[float | None] = []
        r_dl: list[bool] = []
        r_dc: list[str] = []
        for size in sizes:
            nb = compute_net(
                asks, bids, size, fee_buy=fee, fee_sell=fee,
                rebalance_btc=wd_btc, top_ask=top_ask, top_bid=top_bid,
            )
            if nb.filled <= 0.0:
                r_npb.append(None)
                r_net.append(None)
                r_ps.append(None)
                r_ee.append(None)
                r_dl.append(True)
                r_dc.append("none")
                continue
            p, ece = expected_capturable_edge(
                nb.net, nb.net_per_btc, nb.fees, lat,
                sigma_usd_per_sqrt_s=sigma_usd_per_sqrt_s,
            )
            r_npb.append(nb.net_per_btc)
            r_net.append(nb.net)
            r_ps.append(p)
            r_ee.append(ece)
            r_dl.append(nb.depth_limited)
            r_dc.append(nb.dominant_cost)

            cell = FrontierBestCell(
                size_btc=size, fee_bps=fee * 10_000, net_per_btc=nb.net_per_btc,
                net_usd=nb.net, expected_edge_usd=ece, p_survive=p,
            )
            if nb.net_per_btc > 0.0 and (
                best_unit is None or nb.net_per_btc > best_unit.net_per_btc
            ):
                best_unit = cell
            if nb.net > 0.0 and (best_total is None or nb.net > best_total.net_usd):
                best_total = cell
            if ece > 0.0 and (best_risk is None or ece > (best_risk.expected_edge_usd or 0.0)):
                best_risk = cell
        matrix.append(r_npb)
        net_usd.append(r_net)
        psurv.append(r_ps)
        eedge.append(r_ee)
        depth_limited.append(r_dl)
        dominant.append(r_dc)

    gross_top = (top_bid - top_ask) if (top_ask is not None and top_bid is not None) else 0.0

    return FrontierResult(
        mode=mode,
        route=route,
        asof_monotonic=asof,
        sizes_btc=sizes,
        fee_tiers=[FeeTier(label=lbl, bps=fee * 10_000) for lbl, fee in _FEE_TIERS],
        matrix=matrix,
        net_usd=net_usd,
        p_survive=psurv,
        expected_edge=eedge,
        depth_limited=depth_limited,
        dominant_cost=dominant,
        best=FrontierBest(
            by_unit_edge=best_unit, by_total_edge=best_total, by_risk_adjusted=best_risk,
        ),
        gross_top_per_btc=gross_top,
        survival_model=(
            f"P_survive = Φ(net_per_btc / (σ·√Δt)), σ={sigma_usd_per_sqrt_s} USD/√s, "
            f"Δt={lat:.0f} ms"
        ),
        notes=(
            "Cada celda pasa por la misma aritmética del pipeline (cost_model: walk-the-book "
            "VWAP + fees por leg + rebalanceo). P_survive pondera la deriva durante la latencia; "
            "Expected Edge = P_survive·neto − (1−P_survive)·coste de unwind. El edge muere por "
            "fees, profundidad y rebalanceo — no por velocidad."
        ),
    )


def build_edge_frontier() -> dict[str, object]:
    """Compat: forma legada (demo) que consumían router y tests previos. Devuelve dict."""
    return build_frontier(mode="demo").model_dump(mode="json")
