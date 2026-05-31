"""C15 — Reconciliación contra el ejemplo del reto ($109.75/BTC). FR-021, NFR-004.

OBJETIVO: demostrar que NUESTRO cálculo de neto (el `NetEvaluator`, C6) reproduce
exactamente el número de referencia del enunciado del reto. Es la "prueba #1" de que el
neto es correcto (research §"Reconciliación contra el ejemplo del reto") y la línea de
referencia del HERO Edge Waterfall del dashboard (STORY-023).

---
INPUTS DEL EJEMPLO DEL RETO:

    "compra 1 BTC a $70,000 + fee 0.1%, venta a $70,250 − fee 0.1% → ganancia neta
     $109.75/BTC".

Los inputs están completamente especificados por el enunciado; NO se reconstruye nada del
escenario base. La aritmética de referencia es el ejemplo canónico del reto:

    gross    = (70250 - 70000) * 1 BTC                 = 250.00 USD
    fee_buy  = 70000 * 1 BTC * 0.001                    =  70.00 USD
    fee_sell = 70250 * 1 BTC * 0.001                    =  70.25 USD
    net      = 250.00 - 70.00 - 70.25                   = 109.75 USD/BTC   ✓

Esto coincide EXACTAMENTE con la fórmula del Apéndice D.1 de la arquitectura:
    gross_net = Qe * (vwap_sell*(1-fee_sell) - vwap_buy*(1+fee_buy))
              = 1 * (70250*0.999 - 70000*1.001) = 70179.75 - 70070.00 = 109.75
y con `NetEvaluator.evaluate` cuando `net = gross - fees - rebalanceo`.

---
SUPOSICIONES EXPLÍCITAS del escenario que pasa por el `NetEvaluator` (honestidad ante el
jurado financiero — no forzamos el número, lo derivamos):

  1. FEES: 0.1% taker en AMBOS venues (= 0.0010), tal cual el enunciado ("fee 0.1%").
     NO usamos los fees por defecto de producción (Binance 0.10% / Kraken 0.40%): el
     ejemplo del reto fija 0.1% en las DOS patas. Construimos un `Settings` ad-hoc con
     dos venues simétricos a 0.1% para reproducir el enunciado al pie de la letra.

  2. REBALANCEO ON-CHAIN = 0. El ejemplo del reto modela el coste de transacción ÚNICA
     y EXCLUSIVAMENTE como el fee 0.1% por pata; NO incluye coste de retiro on-chain /
     rebalanceo. Por eso el escenario de reconciliación usa `withdrawal_btc = 0.0` en
     ambos venues (en producción el rebalanceo amortizado SÍ se cobra; ver
     `evaluator.py`, pero NO es parte del ejemplo del reto). Si se dejara el rebalanceo
     por defecto, el neto bajaría ~17.85 USD y NO reconciliaría — sería deshonesto
     comparar contra 109.75 incluyendo un coste que el enunciado no contempla.

  3. LIBRO DE 1 SOLO NIVEL con profundidad >= 1 BTC en cada lado: así el VWAP recorrido
     (walk-the-book) es exactamente el precio top-of-book (70000 ask de compra, 70250
     bid de venta), el slippage es 0 (no hay niveles peores) y `q` efectiva = 1 BTC. El
     ejemplo del reto es un trade a precio único; no hay impacto de profundidad.

  4. SLIPPAGE = 0 (un solo nivel) → pasa el filtro `max_slippage` sin recortar `q`.

El neto resultante se compara contra 109.75 con tolerancia `RECONCILE_TOLERANCE_USD`
(1e-6 USD): es aritmética exacta en doble precisión, así que la holgura sólo absorbe el
ruido de coma flotante, no una discrepancia de modelo.

Determinista: sin red ni reloj; el `ts` de los libros se fija a un valor sintético fijo.
"""
from __future__ import annotations

from ..config import ExchangeConfig, Settings
from ..engine.evaluator import NetEvaluator
from ..models.enums import OpportunityStatus, Strategy
from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity
from .results import ReconciliationResult

# --- Inputs EXACTOS del ejemplo del reto (PRD FR-021) ---
TARGET_NET_USD: float = 109.75        # ganancia neta/BTC de referencia del reto
CHALLENGE_QTY_BTC: float = 1.0        # "compra 1 BTC"
CHALLENGE_BUY_PRICE: float = 70_000.0  # "compra ... a $70,000"
CHALLENGE_SELL_PRICE: float = 70_250.0  # "venta a $70,250"
CHALLENGE_FEE_TAKER: float = 0.0010   # "fee 0.1%" en ambas patas

# Tolerancia documentada: aritmética exacta en doble precisión; sólo absorbe ruido FP.
RECONCILE_TOLERANCE_USD: float = 1e-6

# `ts` sintético fijo (determinismo: no se lee reloj real en el cómputo ni en asserts).
_FIXED_TS: float = 0.0


def build_challenge_settings() -> Settings:
    """`Settings` ad-hoc que reproduce el enunciado del reto: dos venues simétricos con
    fee taker 0.1% y SIN rebalanceo on-chain (ver SUPOSICIONES 1-2 del módulo).

    No toca la config de producción (`get_settings`): es un escenario aislado y
    determinista, sólo para la reconciliación."""
    exchanges = {
        # Venue de COMPRA (rol "A" del Apéndice D.1). 0.1% taker, 0 retiro on-chain.
        "challenge_buy": ExchangeConfig(
            id="challenge_buy", symbol="BTC/USD", quote_ccy="USD",
            fee_taker=CHALLENGE_FEE_TAKER, withdrawal_btc=0.0, ob_limit=10,
        ),
        # Venue de VENTA (rol "B"). Mismo fee, mismo 0 retiro.
        "challenge_sell": ExchangeConfig(
            id="challenge_sell", symbol="BTC/USD", quote_ccy="USD",
            fee_taker=CHALLENGE_FEE_TAKER, withdrawal_btc=0.0, ob_limit=10,
        ),
    }
    return Settings(
        exchanges=exchanges,
        ingest_autostart=False,            # nunca abre red
        default_trade_qty_btc=CHALLENGE_QTY_BTC,
        min_net_profit_usd=0.0,            # 109.75 > 0 → viable
        max_slippage=CHALLENGE_FEE_TAKER,  # holgura amplia; el escenario tiene slippage 0
    )


def _challenge_books() -> tuple[NormalizedBook, NormalizedBook]:
    """Libros normalizados (ya en USD) de un solo nivel con 1 BTC de profundidad: el VWAP
    recorrido = top-of-book, slippage 0 (ver SUPOSICIÓN 3). El bid del venue de COMPRA y
    el ask del venue de VENTA son irrelevantes para el neto (sólo se recorren asks de
    compra y bids de venta); se rellenan coherentes (bid<ask) para no violar `no_cross_book`.
    """
    # Venue de compra: compramos contra sus ASKS → 70000. Su bid (no usado para el neto)
    # se fija por debajo del ask para mantener bid < ask.
    buy_book = NormalizedBook(
        exchange="challenge_buy", symbol="BTC/USD", quote_ccy="USD",
        bids=[(CHALLENGE_BUY_PRICE - 1.0, 5.0)],
        asks=[(CHALLENGE_BUY_PRICE, 5.0)],
        price_norm_factor=1.0, ts_exchange=_FIXED_TS, ts_recv_monotonic=_FIXED_TS,
    )
    # Venue de venta: vendemos contra sus BIDS → 70250. Su ask se fija por encima del bid.
    sell_book = NormalizedBook(
        exchange="challenge_sell", symbol="BTC/USD", quote_ccy="USD",
        bids=[(CHALLENGE_SELL_PRICE, 5.0)],
        asks=[(CHALLENGE_SELL_PRICE + 1.0, 5.0)],
        price_norm_factor=1.0, ts_exchange=_FIXED_TS, ts_recv_monotonic=_FIXED_TS,
    )
    return buy_book, sell_book


def build_challenge_opportunity() -> Opportunity:
    """`Opportunity(detected)` del ejemplo del reto: comprar en `challenge_buy`, vender en
    `challenge_sell`."""
    return Opportunity(
        id="reconcile-109.75",
        strategy=Strategy.spatial,
        symbol="BTC/USD",
        buy_venue="challenge_buy",
        sell_venue="challenge_sell",
    )


def reconcile_challenge(
    *, tolerance: float = RECONCILE_TOLERANCE_USD
) -> ReconciliationResult:
    """Reproduce el ejemplo del reto pasándolo por el `NetEvaluator` REAL (C6) y reconcilia
    el neto contra $109.75/BTC.

    Devuelve un `ReconciliationResult` con `computed`, `diff`, `passed` (abs(diff) <=
    tolerance) y el `breakdown` gross/fees/rebalanceo para el waterfall del dashboard.

    Usa el MISMO `NetEvaluator.evaluate` que el pipeline en producción — no una fórmula
    paralela —, de modo que un cambio que rompa el cálculo de neto rompe esta
    reconciliación (gate de regresión, NFR-004)."""
    settings = build_challenge_settings()
    evaluator = NetEvaluator(settings)
    buy_book, sell_book = _challenge_books()
    opp = build_challenge_opportunity()

    evaluator.evaluate(opp, buy_book, sell_book)

    # `net_pnl` es el neto/BTC para qty=1 (la qty del reto). En el caso general sería
    # neto total; aquí qty=1 BTC, así que neto total == neto/BTC.
    computed = float(opp.net_pnl) if opp.net_pnl is not None else float("nan")
    diff = computed - TARGET_NET_USD
    passed = abs(diff) <= tolerance and opp.status is OpportunityStatus.viable

    # Desglose para el HERO Edge Waterfall (gross → -fees → net). Rebalanceo = 0 por
    # construcción (ver SUPOSICIÓN 2). Recalculado desde los campos de la opp evaluada.
    q = opp.q_target
    # Tras evaluar el escenario del reto (viable) vwap_buy/vwap_sell están siempre poblados;
    # el `or 0.0` los normaliza a float (tipado) sin cambiar el número en el caso real.
    vwap_sell = opp.vwap_sell or 0.0
    vwap_buy = opp.vwap_buy or 0.0
    gross = (vwap_sell - vwap_buy) * q
    fees = float(opp.fees) if opp.fees is not None else 0.0
    rebalance = gross - fees - computed  # cierre del balance (0 en este escenario)

    return ReconciliationResult(
        target=TARGET_NET_USD,
        computed=computed,
        diff=diff,
        tolerance=tolerance,
        passed=passed,
        qty_btc=q,
        breakdown={
            "gross": gross,
            "fees": fees,
            "rebalance": rebalance,
            "net": computed,
        },
        notes=(
            "Ejemplo del reto (PRD FR-021): compra 1 BTC a $70,000 +0.1% fee, "
            "venta a $70,250 -0.1% fee => neto $109.75/BTC. Reconciliado vía "
            "NetEvaluator (C6) con fee 0.1% por pata y rebalanceo on-chain = 0 "
            "(el enunciado no incluye coste de retiro)."
        ),
    )
