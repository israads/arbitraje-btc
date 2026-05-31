"""C15 — Ensamblado del `ValidationReport` para el endpoint y el runtime. FR-021.

`build_validation_report()` produce la "prueba de correctitud" que consume
`GET /api/v1/validation` (y el HERO Edge Waterfall, STORY-023): la reconciliación
$109.75 + la batería de invariantes evaluada sobre un escenario determinista derivado
del propio ejemplo del reto (más las property-based que no necesitan estado vivo).

Determinista y autostart-safe: no lee red, reloj real ni el estado vivo del proceso —
construye su propio escenario reproducible. Así el endpoint responde igual con o sin
ingesta y nunca depende de que haya habido trades reales.
"""
from __future__ import annotations

from ..config import ExchangeConfig, Settings
from ..models.opportunity import Opportunity
from ..sim.inventory import Portfolio
from ..sim.simulator import ExecutionSimulator
from .results import InvariantResult, ValidationReport


def build_validation_report() -> ValidationReport:
    """Construye el reporte completo: reconciliación + invariantes, todo determinista.

    El escenario base es el del ejemplo del reto (`harness.build_challenge_*`): se evalúa
    con el `NetEvaluator`, se simula con el `ExecutionSimulator` y se aplica a un
    `Portfolio` sembrado para ejercer la conservación de valor sobre datos reales del
    pipeline (mismo código que producción), no mocks.

    Importa los submódulos de forma perezosa dentro de la función para evitar un ciclo de
    import con `validate/__init__.py` (que re-exporta `build_validation_report`)."""
    from . import harness, invariants
    settings = harness.build_challenge_settings()
    buy_book, sell_book = harness._challenge_books()

    # 1) Reconciliación $109.75 (gate principal).
    reconciliation = harness.reconcile_challenge()

    # 2) Escenario evaluado + simulado para las invariantes sobre objetos reales.
    from ..engine.evaluator import NetEvaluator
    opp: Opportunity = harness.build_challenge_opportunity()
    NetEvaluator(settings).evaluate(opp, buy_book, sell_book)
    # Sin `sell_book_t1` (sin re-lectura t+Δ) el simulador NUNCA devuelve None (el gate
    # pre-trade de slippage sólo actúa bajo modelo de latencia): el assert lo afirma para el
    # type checker y documenta el contrato usado en la reconciliación $109.75.
    execution = ExecutionSimulator(settings).simulate(opp, buy_book, sell_book, ts=0.0)
    assert execution is not None

    # Cartera sembrada (con suficiente inventario para no faltar BTC/quote) sobre la que
    # medir la conservación: capturamos el estado ANTES y aplicamos el Execution.
    settings_seeded = _seed_settings(settings)
    pf = Portfolio(settings_seeded)
    quote_before = {v: vb.quote for v, vb in pf.venues.items()}
    btc_before = sum(vb.btc for vb in pf.venues.values())
    pf.apply_execution(execution)

    inv: list[InvariantResult] = [
        invariants.check_net_identity(opp, settings),
        invariants.check_single_fee_per_leg(execution, settings),
        invariants.check_slippage_nonnegative(opp, buy_book, sell_book),
        invariants.check_qty_within_depth(execution, buy_book, sell_book),
        invariants.check_no_cross_book(buy_book),
        invariants.check_no_cross_book(sell_book),
        invariants.check_value_conservation(
            quote_before, pf, realized_pnl=execution.realized_pnl, btc_before=btc_before,
        ),
        invariants.check_no_degenerate_arbitrage(settings),
        invariants.check_fee_monotonicity(),
    ]

    all_passed = reconciliation.passed and all(i.passed for i in inv)
    return ValidationReport(
        reconciliation=reconciliation, invariants=inv, all_passed=all_passed
    )


def _seed_settings(settings: Settings) -> Settings:
    """Clona `settings` con inventario inicial suficiente en los dos venues del reto para
    aplicar el Execution sin faltantes (la conservación se mide sobre balances vivos)."""
    exchanges: dict[str, ExchangeConfig] = {}
    for vid, cfg in settings.exchanges.items():
        exchanges[vid] = ExchangeConfig(
            id=cfg.id, symbol=cfg.symbol, quote_ccy=cfg.quote_ccy,
            fee_taker=cfg.fee_taker, withdrawal_btc=cfg.withdrawal_btc,
            ob_limit=cfg.ob_limit, initial_btc=5.0, initial_quote=500_000.0,
            enabled=True,
        )
    return Settings(exchanges=exchanges, ingest_autostart=False,
                    default_trade_qty_btc=settings.default_trade_qty_btc,
                    min_net_profit_usd=settings.min_net_profit_usd,
                    max_slippage=settings.max_slippage)
