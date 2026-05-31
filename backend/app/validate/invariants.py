"""C15 — Invariantes del sistema (FR-021, NFR-004).

Validadores REUTILIZABLES que el sistema debe cumplir SIEMPRE. Cada función recibe
objetos del dominio (`Opportunity`, `Execution`, `Portfolio`, `NormalizedBook`) y
devuelve un `InvariantResult` estructurado (pasa/falla + detalle + métricas). Sirven
tanto a los tests (property-based / casos pasa-falla) como a la "aserción de
reconciliación de balances en runtime" del endpoint `/api/v1/validation` y del wiring.

Invariantes cubiertas (PRD FR-021 / product-brief §Validación):
  · conservación de valor (el P&L no crea/destruye dinero más allá de fees)
  · fee única por leg (no doble fee)
  · slippage >= 0 (nunca negativo: comprar mueve el precio en contra)
  · net = gross - fees - rebalanceo (identidad del neto del evaluador)
  · q ejecutada <= profundidad (no se llena más de lo que ofrece el book)
  · sin look-ahead / precios normalizados (no cross book: bid < ask en cada venue)
  · monotonía de fees (más fee ⇒ no más neto) y no-arbitraje degenerado (spread 0 ⇒ neto<0)

Determinista: sin red ni reloj. Tolerancias en USD/relativas documentadas como constantes.
"""
from __future__ import annotations

import math

from ..config import ExchangeConfig, Settings
from ..engine.evaluator import NetEvaluator
from ..models.enums import LegSide, OpportunityStatus, Strategy
from ..models.execution import Execution
from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity
from ..sim.inventory import Portfolio
from .results import InvariantResult

# Holgura absoluta (USD) para identidades de coma flotante (gross/fees/neto/equity).
_ABS_TOL_USD: float = 1e-6
# Holgura relativa pequeña para comparaciones de notional grandes (q*precio ~ 70k+).
_REL_TOL: float = 1e-9
# Holgura BTC para conservación de cantidad.
_BTC_TOL: float = 1e-9


def _close(a: float, b: float, *, abs_tol: float = _ABS_TOL_USD) -> bool:
    """Igualdad con holgura absoluta + relativa (notional grande no rompe por FP)."""
    return math.isclose(a, b, rel_tol=_REL_TOL, abs_tol=abs_tol)


# --------------------------------------------------------------------------- #
# 1) Identidad del neto: net == gross - fees - rebalanceo                      #
# --------------------------------------------------------------------------- #
def check_net_identity(opp: Opportunity, settings: Settings) -> InvariantResult:
    """`net = gross - fees - rebalanceo` sobre una `Opportunity` ya evaluada (C6).

    Reconstruye gross (`(vwap_sell - vwap_buy)*q`) y el rebalanceo amortizado a partir de
    config + campos de la opp, y verifica que `net_pnl == gross - fees - rebalanceo`. Sólo
    aplica a opps con neto computado (viable / not_profitable_fees); las descartadas
    temprano (thin_book, slippage) no tienen neto → se reportan como N/A (passed=True,
    nada que comprobar)."""
    name = "net_identity"
    if opp.net_pnl is None or opp.vwap_buy is None or opp.vwap_sell is None:
        return InvariantResult(
            name=name, passed=True,
            detail="opp sin neto computado (descarte temprano): nada que reconciliar",
        )
    q = opp.q_target
    gross = (opp.vwap_sell - opp.vwap_buy) * q
    fees = opp.fees if opp.fees is not None else 0.0

    def _wd(venue: str) -> float:
        cfg = settings.exchanges.get(venue)
        return cfg.withdrawal_btc if cfg is not None else 0.0

    rebalance = (_wd(opp.buy_venue) + _wd(opp.sell_venue)) * opp.vwap_buy
    expected = gross - fees - rebalance
    passed = _close(expected, opp.net_pnl)
    return InvariantResult(
        name=name, passed=passed,
        detail=(
            f"net={opp.net_pnl:.6f} vs gross-fees-rebalanceo={expected:.6f} "
            f"(gross={gross:.6f}, fees={fees:.6f}, rebalanceo={rebalance:.6f})"
        ),
        metrics={"net": opp.net_pnl, "gross": gross, "fees": fees,
                 "rebalance": rebalance, "expected": expected},
    )


# --------------------------------------------------------------------------- #
# 2) Fee única por leg (no doble fee)                                          #
# --------------------------------------------------------------------------- #
def check_single_fee_per_leg(
    execution: Execution, settings: Settings
) -> InvariantResult:
    """Cada `Leg` cobra EXACTAMENTE una vez su fee taker: `fee == qty_filled*vwap*fee_rate`.

    Detecta doble conteo (fee == 2x notional*rate) o fee inflada/inexistente. Una sola
    función de fees en todo el sistema (PRD FR-021: "una sola función de cálculo de fees").
    """
    name = "single_fee_per_leg"
    problems: list[str] = []
    for leg in execution.legs:
        cfg = settings.exchanges.get(leg.venue)
        rate = cfg.fee_taker if cfg is not None else 0.0
        expected = leg.qty_filled * leg.vwap * rate
        if not _close(expected, leg.fee):
            problems.append(
                f"{leg.venue}/{leg.side.value}: fee={leg.fee:.6f} "
                f"!= notional*rate={expected:.6f}"
            )
    passed = not problems
    return InvariantResult(
        name=name, passed=passed,
        detail="ok (fee única por leg)" if passed else "; ".join(problems),
        metrics={"legs": float(len(execution.legs))},
    )


# --------------------------------------------------------------------------- #
# 3) Slippage >= 0 (nunca negativo)                                            #
# --------------------------------------------------------------------------- #
def check_slippage_nonnegative(
    opp: Opportunity, buy_book: NormalizedBook, sell_book: NormalizedBook
) -> InvariantResult:
    """El slippage de cada leg es >= 0: el walk-the-book NUNCA mejora el top-of-book.

    `slip_buy = vwap_buy - best_ask >= 0` (comprar consume niveles cada vez más caros) y
    `slip_sell = best_bid - vwap_sell >= 0` (vender consume bids cada vez más bajos). Un
    slippage negativo señalaría VWAP mejor que el top-of-book = bug de recorrido o un libro
    desordenado. Tolerancia FP pequeña en relativo al precio."""
    name = "slippage_nonnegative"
    if opp.vwap_buy is None or opp.vwap_sell is None:
        return InvariantResult(
            name=name, passed=True, detail="opp sin VWAP (descarte temprano): N/A"
        )
    best_ask = buy_book.best_ask or 0.0
    best_bid = sell_book.best_bid or 0.0
    slip_buy = opp.vwap_buy - best_ask
    slip_sell = best_bid - opp.vwap_sell
    # Holgura proporcional al precio para no fallar por ruido FP en notionals grandes.
    tol = _REL_TOL * max(best_ask, best_bid, 1.0)
    passed = slip_buy >= -tol and slip_sell >= -tol
    return InvariantResult(
        name=name, passed=passed,
        detail=(
            f"slip_buy={slip_buy:.8f} (vwap_buy-best_ask), "
            f"slip_sell={slip_sell:.8f} (best_bid-vwap_sell)"
        ),
        metrics={"slip_buy": slip_buy, "slip_sell": slip_sell},
    )


# --------------------------------------------------------------------------- #
# 4) q ejecutada <= profundidad disponible                                     #
# --------------------------------------------------------------------------- #
def check_qty_within_depth(
    execution: Execution, buy_book: NormalizedBook, sell_book: NormalizedBook
) -> InvariantResult:
    """Lo llenado en cada leg no excede la profundidad de su lado del book.

    Suma la cantidad disponible en asks (compra) / bids (venta) y comprueba que cada
    `qty_filled <= profundidad`. Garantiza que el taker no fabrica liquidez inexistente."""
    name = "qty_within_depth"
    depth_asks = sum(qty for _, qty in buy_book.asks if math.isfinite(qty) and qty > 0)
    depth_bids = sum(qty for _, qty in sell_book.bids if math.isfinite(qty) and qty > 0)
    problems: list[str] = []
    for leg in execution.legs:
        depth = depth_asks if leg.side is LegSide.buy else depth_bids
        if leg.qty_filled > depth + _BTC_TOL:
            problems.append(
                f"{leg.venue}/{leg.side.value}: filled={leg.qty_filled:.9f} "
                f"> profundidad={depth:.9f}"
            )
    passed = not problems
    return InvariantResult(
        name=name, passed=passed,
        detail="ok (fills dentro de profundidad)" if passed else "; ".join(problems),
        metrics={"depth_asks": depth_asks, "depth_bids": depth_bids},
    )


# --------------------------------------------------------------------------- #
# 5) No cross book / precios normalizados (bid < ask)                          #
# --------------------------------------------------------------------------- #
def check_no_cross_book(book: NormalizedBook) -> InvariantResult:
    """`best_bid < best_ask` en un libro normalizado sano (no cross book).

    Un libro cruzado (bid >= ask en el MISMO venue) sería arbitraje degenerado intra-venue
    = dato corrupto o re-normalización indebida. Verifica también que asks suben y bids
    bajan (orden monotónico) — síntoma de precios bien normalizados a USD, no re-escalados."""
    name = "no_cross_book"
    bid, ask = book.best_bid, book.best_ask
    problems: list[str] = []
    if bid is not None and ask is not None and bid >= ask:
        problems.append(f"{book.exchange}: best_bid={bid} >= best_ask={ask} (cruzado)")
    # Orden monotónico de los niveles (asks asc, bids desc) ignorando niveles vacíos.
    asks = [p for p, q in book.asks if q > 0]
    bids = [p for p, q in book.bids if q > 0]
    if any(a > b for a, b in zip(asks, asks[1:], strict=False)):
        problems.append(f"{book.exchange}: asks no ascendentes (book desordenado)")
    if any(a < b for a, b in zip(bids, bids[1:], strict=False)):
        problems.append(f"{book.exchange}: bids no descendentes (book desordenado)")
    passed = not problems
    return InvariantResult(
        name=name, passed=passed,
        detail=f"{book.exchange}: bid={bid} ask={ask} ok" if passed else "; ".join(problems),
        metrics={"best_bid": bid or 0.0, "best_ask": ask or 0.0},
    )


# --------------------------------------------------------------------------- #
# 6) Conservación de valor (el P&L no crea/destruye dinero más allá de fees)   #
# --------------------------------------------------------------------------- #
def check_value_conservation(
    portfolio_before: dict[str, float],
    portfolio_after: Portfolio,
    *,
    realized_pnl: float,
    btc_before: float,
) -> InvariantResult:
    """Conservación de valor sobre la doble entrada del `Portfolio` tras aplicar un trade
    casado (ningún dinero se crea o destruye más allá de lo que explican spread y fees).

    Identidades EXACTAS de la doble entrada de un par CASADO (compra Q en un venue, vende Q
    en otro; PRD FR-021: "Σ entradas = Σ salidas + fees + posición"):
      a) QUOTE: el cambio en el quote TOTAL es EXACTAMENTE el `realized_pnl` del trade
         (`realized_pnl = gross_casado - fees`). No aparece valor de la nada: todo el
         delta de quote lo explican el spread casado y los fees pagados. Para un par
         perfectamente casado (sin leg risk) el quote total SUBE el P&L neto; si el bot
         perdiera tras fees, bajaría — el número refleja el coste real, no se infla.
      b) BTC: el BTC TOTAL se conserva (los trades casados mueven BTC ENTRE venues, no lo
         crean ni lo destruyen). El leg risk abierto sólo REUBICA BTC, tampoco lo crea.

    `portfolio_before` es `{venue: quote_inicial}` capturado ANTES del trade; `btc_before`
    el total de BTC inicial. Es la aserción de reconciliación de balances en runtime: si
    falla, el motor de balances está fabricando o destruyendo dinero."""
    name = "value_conservation"
    quote_before = sum(portfolio_before.values())
    quote_after = sum(vb.quote for vb in portfolio_after.venues.values())
    btc_after = sum(vb.btc for vb in portfolio_after.venues.values())
    delta_quote = quote_after - quote_before

    # a) El delta de quote total == realized P&L (gross casado - fees). Holgura proporcional
    #    al notional (q*precio ~ 70k+) para no fallar por ruido FP.
    quote_ok = _close(delta_quote, realized_pnl, abs_tol=1e-4)
    # b) El BTC total se conserva (los matched lo mueven entre venues, no lo crean).
    btc_ok = _close(btc_after, btc_before, abs_tol=_BTC_TOL)

    problems: list[str] = []
    if not quote_ok:
        problems.append(
            f"quote: Δ={delta_quote:.6f} != realized_pnl={realized_pnl:.6f}"
        )
    if not btc_ok:
        problems.append(f"btc: after={btc_after:.9f} != before={btc_before:.9f}")
    passed = not problems
    return InvariantResult(
        name=name, passed=passed,
        detail="ok (Δquote == realized_pnl; btc conservado)" if passed
        else "; ".join(problems),
        metrics={
            "quote_before": quote_before, "quote_after": quote_after,
            "delta_quote": delta_quote, "realized_pnl": realized_pnl,
            "btc_before": btc_before, "btc_after": btc_after,
        },
    )


# --------------------------------------------------------------------------- #
# 7) No-arbitraje degenerado: spread 0 + fees > 0 ⇒ neto < 0 (nunca viable)    #
# --------------------------------------------------------------------------- #
def check_no_degenerate_arbitrage(settings: Settings) -> InvariantResult:
    """Con spread CERO (mismo precio en ambos venues) y fees > 0, el neto DEBE ser < 0 y la
    opp NUNCA viable. Evalúa un escenario sintético por el `NetEvaluator` real.

    Property fundamental anti-falsos-positivos (PRD FR-021): si el sistema marcara viable
    un cruce sin spread, estaría inventando dinero. Determinista, sin red."""
    name = "no_degenerate_arbitrage"
    price = 70_000.0
    # Mismo precio en ambos lados (spread 0). Necesita fee > 0 en algún venue.
    buy = NormalizedBook(
        exchange="deg_buy", symbol="BTC/USD", quote_ccy="USD",
        bids=[(price - 1.0, 5.0)], asks=[(price, 5.0)],
        ts_recv_monotonic=0.0, ts_exchange=0.0,
    )
    sell = NormalizedBook(
        exchange="deg_sell", symbol="BTC/USD", quote_ccy="USD",
        bids=[(price, 5.0)], asks=[(price + 1.0, 5.0)],
        ts_recv_monotonic=0.0, ts_exchange=0.0,
    )
    opp = Opportunity(
        id="deg", strategy=settings_strategy(), symbol="BTC/USD",
        buy_venue="deg_buy", sell_venue="deg_sell",
    )
    # Evaluador con los venues `deg_*` presentes en config (fee y rebalanceo 0 si faltaban).
    # NO se fuerza fee > 0: la property exige que CON fees > 0 el neto sea < 0; si la config
    # trae fees 0 el escenario es degenerado-degenerado (spread 0 + fee 0 → neto 0) y la
    # property no se cumple — la invariante lo reporta como fallo (sin fees no hay margen
    # anti-falso-positivo), que es el comportamiento honesto y testeable.
    ev_settings = _with_venues(settings, "deg_buy", "deg_sell")
    NetEvaluator(ev_settings).evaluate(opp, buy, sell)
    net = opp.net_pnl if opp.net_pnl is not None else 0.0
    passed = net < 0.0 and opp.status is not OpportunityStatus.viable
    return InvariantResult(
        name=name, passed=passed,
        detail=f"spread=0, fees>0 => net={net:.6f}, status={opp.status.value}",
        metrics={"net": net},
    )


# --------------------------------------------------------------------------- #
# 8) Monotonía de fees: más fee ⇒ neto no aumenta                              #
# --------------------------------------------------------------------------- #
def check_fee_monotonicity() -> InvariantResult:
    """Subir el fee taker NUNCA puede aumentar el neto (a precios/cantidad fijos).

    Evalúa el mismo cruce con fee bajo vs fee alto por el `NetEvaluator` real y exige
    `net(fee_alto) <= net(fee_bajo)`. Property-based ligera (PRD FR-021: monotonía)."""
    name = "fee_monotonicity"
    price_buy, price_sell = 70_000.0, 70_500.0

    def _net(fee: float) -> float:
        exchanges = {
            "mono_buy": _mk_cfg("mono_buy", fee),
            "mono_sell": _mk_cfg("mono_sell", fee),
        }
        s = Settings(exchanges=exchanges, ingest_autostart=False,
                     default_trade_qty_btc=1.0, min_net_profit_usd=0.0,
                     max_slippage=1.0)
        buy = NormalizedBook(
            exchange="mono_buy", symbol="BTC/USD", quote_ccy="USD",
            bids=[(price_buy - 1.0, 5.0)], asks=[(price_buy, 5.0)],
            ts_recv_monotonic=0.0, ts_exchange=0.0,
        )
        sell = NormalizedBook(
            exchange="mono_sell", symbol="BTC/USD", quote_ccy="USD",
            bids=[(price_sell, 5.0)], asks=[(price_sell + 1.0, 5.0)],
            ts_recv_monotonic=0.0, ts_exchange=0.0,
        )
        opp = Opportunity(id="mono", strategy=settings_strategy(), symbol="BTC/USD",
                          buy_venue="mono_buy", sell_venue="mono_sell")
        NetEvaluator(s).evaluate(opp, buy, sell)
        return opp.net_pnl if opp.net_pnl is not None else 0.0

    net_low = _net(0.0005)
    net_high = _net(0.0050)
    passed = net_high <= net_low + _ABS_TOL_USD
    return InvariantResult(
        name=name, passed=passed,
        detail=f"net(fee=0.05%)={net_low:.4f} >= net(fee=0.50%)={net_high:.4f}",
        metrics={"net_low_fee": net_low, "net_high_fee": net_high},
    )


# --- Helpers internos (config sintética para invariantes property-based) --- #
def _mk_cfg(vid: str, fee: float) -> ExchangeConfig:
    return ExchangeConfig(
        id=vid, symbol="BTC/USD", quote_ccy="USD",
        fee_taker=fee, withdrawal_btc=0.0, ob_limit=10,
    )


def _with_venues(settings: Settings, *venues: str) -> Settings:
    """Devuelve un `Settings` con `venues` presentes y SIN rebalanceo (para aislar el efecto
    de los fees). Respeta el `fee_taker` de la config si el venue ya existe (incluido 0); a
    los faltantes les pone 0.1% por defecto. No muta el `settings` original."""
    exchanges = dict(settings.exchanges)
    for v in venues:
        if v in exchanges:
            cfg = exchanges[v]
            exchanges[v] = _mk_cfg(v, cfg.fee_taker)  # rebalanceo a 0, fee de la config
        else:
            exchanges[v] = _mk_cfg(v, 0.0010)
    return Settings(exchanges=exchanges, ingest_autostart=False,
                    default_trade_qty_btc=1.0, min_net_profit_usd=0.0, max_slippage=1.0)


def settings_strategy() -> Strategy:
    """Estrategia por defecto para opps sintéticas (espacial)."""
    return Strategy.spatial
