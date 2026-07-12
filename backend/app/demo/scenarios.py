"""Escenarios deterministas para la demo de jurado (PRD-002).

El player no toca red ni reloj. Produce snapshots pequeños de `NormalizedBook`
que el fallback inyecta por el mismo pipeline vivo: detector -> evaluador ->
simulador -> métricas -> SSE.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models.market import NormalizedBook

# Cadencia mínima de la ventana de observación (PRD-013 RF-002): la duración por escenario
# debe garantizar una baseline de métricas Y una muestra posterior dentro de la activación:
#   repeats × demo_replay_interval_ms >= 2 × metrics_emit_ms + 250 ms
# Con los defaults (50 ms de replay, 1000 ms de métricas) el mínimo es 45 (2.25 s).
REPEATS_PER_SCENARIO = 45

# RF-003B (PRD-013, decisión por defecto): `order_failure` NO ejerce ejecución — el player
# sólo inyecta books y el fallback nunca invoca preflight/test-order. El contrato promete
# EXACTAMENTE lo que la demo muestra; el rechazo pre-trade lo demuestra `thin_book` y el
# unwind se demuestra vía replay/backtest (RF-004), nunca aquí.
ORDER_FAILURE_NO_CLAIM = "sin claim de ejecución; sólo books deterministas"


@dataclass(frozen=True)
class PegUpdate:
    stable: str
    usd_rate: float
    source: str = "jury"


@dataclass(frozen=True)
class JuryScenario:
    name: str
    description: str
    books: tuple[NormalizedBook, ...]
    kind: str = "market"
    expected_result: str | None = None
    peg_updates: tuple[PegUpdate, ...] = ()
    stale: bool = False


@dataclass(frozen=True)
class JuryFrame:
    scenario: JuryScenario
    scenario_index: int
    n_scenarios: int
    repeat_index: int
    books: tuple[NormalizedBook, ...]


def _book(
    exchange: str,
    *,
    bid: float,
    ask: float,
    bids: list[tuple[float, float]] | None = None,
    asks: list[tuple[float, float]] | None = None,
    quote_ccy: str = "USD",
    factor: float = 1.0,
    ts: float = 1_700_000_000_000.0,
) -> NormalizedBook:
    symbol = f"BTC/{quote_ccy}"
    return NormalizedBook(
        exchange=exchange,
        symbol=symbol,
        quote_ccy=quote_ccy,
        bids=bids or [(bid, 2.0), (bid - 20.0, 4.0)],
        asks=asks or [(ask, 2.0), (ask + 20.0, 4.0)],
        price_norm_factor=factor,
        ts_exchange=ts,
        ts_recv_monotonic=0.0,
    )


def build_jury_scenarios() -> tuple[JuryScenario, ...]:
    """Siete escenarios del catálogo jury: los cinco obligatorios del PRD-002 más
    `thin_book` y `order_failure` (PRD-013).

    Los precios ya están normalizados a USD. En los escenarios USDT se incluye
    `price_norm_factor` y el player actualiza el peg para que el evaluador pueda
    aplicar el gate `peg_adverse`.
    """
    return (
        JuryScenario(
            name="good_edge",
            description="Spread amplio que sobrevive VWAP, fees y rebalanceo.",
            books=(
                _book(
                    "binance",
                    bid=62_980.0,
                    ask=63_000.0,
                    quote_ccy="USDT",
                    factor=1.0,
                    ts=1_700_000_000_001.0,
                ),
                _book("kraken", bid=63_600.0, ask=63_620.0, ts=1_700_000_000_001.0),
            ),
            peg_updates=(PegUpdate("USDT", 1.0),),
            expected_result="captured",
        ),
        JuryScenario(
            name="naive_trap",
            description="Top-of-book positivo, pero el neto muere por fees y rebalanceo.",
            books=(
                _book("bitstamp", bid=62_980.0, ask=63_000.0, ts=1_700_000_000_002.0),
                _book("kraken", bid=63_100.0, ask=63_120.0, ts=1_700_000_000_002.0),
            ),
            peg_updates=(PegUpdate("USDT", 1.0),),
            expected_result="not_profitable_fees",
        ),
        JuryScenario(
            name="peg_adverse",
            description="USDT se desvía del peg y el motor no confía en el cruce.",
            books=(
                _book(
                    "binance",
                    bid=62_960.0,
                    ask=63_000.0,
                    quote_ccy="USDT",
                    factor=0.985,
                    ts=1_700_000_000_003.0,
                ),
                _book(
                    "bybit",
                    bid=63_250.0,
                    ask=63_280.0,
                    quote_ccy="USDT",
                    factor=0.985,
                    ts=1_700_000_000_003.0,
                ),
            ),
            peg_updates=(PegUpdate("USDT", 0.985),),
            expected_result="peg_adverse",
        ),
        JuryScenario(
            name="stale_feed",
            description="Books vencidos: el detector los excluye y el watchdog los marca stale.",
            books=(
                _book("bitstamp", bid=62_980.0, ask=63_000.0, ts=1_700_000_000_004.0),
                _book("kraken", bid=63_500.0, ask=63_520.0, ts=1_700_000_000_004.0),
            ),
            peg_updates=(PegUpdate("USDT", 1.0),),
            stale=True,
            # Señal: estado feed/breaker stale (NO un DiscardReason); la ausencia de
            # oportunidad por sí sola no prueba el claim (PRD-013, tabla de contratos).
            expected_result="stale_data_excluded",
        ),
        JuryScenario(
            name="latency_decay",
            description="El cruce existe arriba, pero la profundidad lo vuelve no ejecutable.",
            books=(
                _book(
                    "bitstamp",
                    bid=62_980.0,
                    ask=63_000.0,
                    asks=[(63_000.0, 0.05), (63_340.0, 2.0)],
                    ts=1_700_000_000_005.0,
                ),
                _book(
                    "kraken",
                    bid=63_180.0,
                    ask=63_220.0,
                    bids=[(63_180.0, 0.05), (62_760.0, 2.0)],
                    ts=1_700_000_000_005.0,
                ),
            ),
            peg_updates=(PegUpdate("USDT", 1.0),),
            expected_result="slippage_over_limit",
        ),
        JuryScenario(
            name="thin_book",
            description=(
                "Spread aparente fuerte, pero no hay profundidad suficiente "
                "para el tamaño objetivo."
            ),
            books=(
                _book(
                    "bitstamp",
                    bid=62_980.0,
                    ask=63_000.0,
                    asks=[(63_000.0, 0.03), (63_010.0, 0.02)],
                    ts=1_700_000_000_006.0,
                ),
                _book(
                    "kraken",
                    bid=63_700.0,
                    ask=63_720.0,
                    bids=[(63_700.0, 0.03), (63_690.0, 0.02)],
                    ts=1_700_000_000_006.0,
                ),
            ),
            peg_updates=(PegUpdate("USDT", 1.0),),
            expected_result="thin_book",
        ),
        JuryScenario(
            name="order_failure",
            # RF-003B: reformulado. Antes prometía `preflight_or_test_order_reject`, pero el
            # fallback SÓLO inyecta books: nunca invoca preflight ni test-order. El claim se
            # retira; badge en UI: `NO EJERCE EJECUCIÓN`.
            description=(
                "NO EJERCE EJECUCIÓN: ruta con Binance sólo con books deterministas; "
                "preflight/test-order no se invoca en esta demo."
            ),
            books=(
                _book(
                    "binance",
                    bid=62_980.0,
                    ask=63_000.0,
                    quote_ccy="USDT",
                    factor=1.0,
                    ts=1_700_000_000_007.0,
                ),
                _book("kraken", bid=63_650.0, ask=63_680.0, ts=1_700_000_000_007.0),
            ),
            kind="execution",
            expected_result=ORDER_FAILURE_NO_CLAIM,
            peg_updates=(PegUpdate("USDT", 1.0),),
        ),
    )


class JuryScenarioPlayer:
    """Cicla escenarios con una cadencia visualmente estable.

    `repeats_per_scenario` mantiene el mismo escenario varios ticks para que la UI
    pueda mostrarlo, pero la secuencia completa sigue tardando pocos segundos.
    """

    def __init__(
        self,
        scenarios: tuple[JuryScenario, ...] | None = None,
        *,
        repeats_per_scenario: int = REPEATS_PER_SCENARIO,
    ) -> None:
        self._scenarios = scenarios or build_jury_scenarios()
        self._repeats = max(1, repeats_per_scenario)
        self._scenario_idx = 0
        self._repeat_idx = 0

    @property
    def n_scenarios(self) -> int:
        return len(self._scenarios)

    def scenarios(self) -> tuple[JuryScenario, ...]:
        return self._scenarios

    def reset(self) -> None:
        self._scenario_idx = 0
        self._repeat_idx = 0

    def select(self, name: str) -> JuryScenario | None:
        for idx, scenario in enumerate(self._scenarios):
            if scenario.name == name:
                self._scenario_idx = idx
                self._repeat_idx = 0
                return scenario
        return None

    def next_frame(self) -> JuryFrame:
        scenario = self._scenarios[self._scenario_idx]
        frame = JuryFrame(
            scenario=scenario,
            scenario_index=self._scenario_idx + 1,
            n_scenarios=len(self._scenarios),
            repeat_index=self._repeat_idx + 1,
            books=scenario.books,
        )
        self._repeat_idx += 1
        if self._repeat_idx >= self._repeats:
            self._repeat_idx = 0
            self._scenario_idx = (self._scenario_idx + 1) % len(self._scenarios)
        return frame
