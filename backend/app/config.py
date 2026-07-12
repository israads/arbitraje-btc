"""C17 — Configuración tipada (pydantic-settings). NFR-009.

Toda constante económica / umbral vive aquí: nunca hardcode en la lógica.
Defaults = Apéndice E de la arquitectura. Override por entorno (prefijo `ARB_`)
o archivo `.env`. Nested vía `__` (p.ej. `ARB_EXCHANGES__BINANCE__FEE_TAKER=0.0009`).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExchangeConfig(BaseModel):
    """Parámetros por exchange. `fee_taker`/`withdrawal_btc` en fracción/BTC."""

    id: str                       # ccxt id: binance | kraken | coinbase
    symbol: str                   # símbolo unificado ccxt (BTC/USDT, BTC/USD)
    quote_ccy: str                # moneda de cotización (USDT, USD)
    fee_taker: float              # 0.0010 = 0.10%
    withdrawal_btc: float         # BTC por retiro (rebalanceo amortizado)
    ob_limit: int                 # profundidad VÁLIDA por exchange (ver C1)
    initial_btc: float = 2.0      # inventario pre-posicionado
    initial_quote: float = 100_000.0
    enabled: bool = True


def _default_exchanges() -> dict[str, ExchangeConfig]:
    """Multi-venue vía ccxt.pro (watch_order_book). Quote USDT usa el peg USDT global;
    quote USD no necesita peg → todos se normalizan a USD y alimentan el motor por igual.

    `ob_limit` respeta los depths válidos por exchange (un valor inválido NO tumba el loop:
    el ingestor lo registra y reintenta, pero el venue quedaría fuera). Verificado por
    `scripts/probe_exchanges.py`. Bitso (BTC/MXN) queda fuera: no expone ccxt.pro (solo REST)
    y requeriría un ingestor REST + peg USD/MXN (trabajo aparte).

    `fee_taker` = taker spot público aproximado (override por entorno: ARB_EXCHANGES__...).
    """
    return {
        # --- USD (sin peg) ---
        "kraken": ExchangeConfig(
            id="kraken", symbol="BTC/USD", quote_ccy="USD",
            fee_taker=0.0040, withdrawal_btc=0.00005, ob_limit=25,
        ),
        "coinbase": ExchangeConfig(
            id="coinbase", symbol="BTC/USD", quote_ccy="USD",
            fee_taker=0.0060, withdrawal_btc=0.0001, ob_limit=50,
        ),
        "gemini": ExchangeConfig(
            id="gemini", symbol="BTC/USD", quote_ccy="USD",
            fee_taker=0.0040, withdrawal_btc=0.0001, ob_limit=50,
        ),
        "bitstamp": ExchangeConfig(
            id="bitstamp", symbol="BTC/USD", quote_ccy="USD",
            fee_taker=0.0030, withdrawal_btc=0.0001, ob_limit=100,
        ),
        "bitfinex": ExchangeConfig(
            id="bitfinex", symbol="BTC/USD", quote_ccy="USD",
            fee_taker=0.0020, withdrawal_btc=0.0001, ob_limit=100,  # bitfinex len ∈ {1,25,100}
            enabled=False,  # ver nota en okx
        ),
        # --- USDT (peg USDT/USD global) ---
        "binance": ExchangeConfig(
            id="binance", symbol="BTC/USDT", quote_ccy="USDT",
            fee_taker=0.0010, withdrawal_btc=0.0002, ob_limit=20,
        ),
        # okx/bitfinex: conectan en el probe (scripts/probe_exchanges.py) pero NO sostienen
        # el WS en-app aquí (okx cuelga el canal público; bitfinex `len` quisquilloso). Se
        # dejan deshabilitados y documentados → re-activar tras tuning por-exchange (auth/geo).
        "okx": ExchangeConfig(
            id="okx", symbol="BTC/USDT", quote_ccy="USDT",
            # ob_limit>5 ⇒ canal books-l2-tbt (requiere login).
            fee_taker=0.0010, withdrawal_btc=0.0001, ob_limit=5,
            enabled=False,
        ),
        "bybit": ExchangeConfig(
            id="bybit", symbol="BTC/USDT", quote_ccy="USDT",
            fee_taker=0.0010, withdrawal_btc=0.0001, ob_limit=50,
        ),
        "bitget": ExchangeConfig(
            id="bitget", symbol="BTC/USDT", quote_ccy="USDT",
            fee_taker=0.0010, withdrawal_btc=0.0001, ob_limit=15,
        ),
        "kucoin": ExchangeConfig(
            id="kucoin", symbol="BTC/USDT", quote_ccy="USDT",
            fee_taker=0.0010, withdrawal_btc=0.0001, ob_limit=50,
        ),
        "gateio": ExchangeConfig(
            id="gateio", symbol="BTC/USDT", quote_ccy="USDT",
            fee_taker=0.0020, withdrawal_btc=0.0001, ob_limit=20,
        ),
    }


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARB_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # --- App / server ---
    app_name: str = "arbitraje-btc"
    env: str = "dev"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    # Token estático para los endpoints de CONTROL (kill switch / resume / demo / backtest).
    # Vacío ⇒ sin auth (dev/demo local). Si se setea (ARB_CONTROL_TOKEN), esos POST exigen el
    # header `X-Control-Token` — protección mínima antes de exponer el panel en público.
    control_token: str = ""
    # API pública: protecciones opcionales (default OFF para dev/demo local; no rompen el frontend
    # ni los tests). `api_key` vacío ⇒ sin auth; si se setea, las rutas /api/v1/* exigen header
    # `X-API-Key` (salvo health/docs/openapi). `api_rate_limit_per_min`=0 ⇒ sin límite.
    api_key: str = ""
    api_rate_limit_per_min: int = 0

    # --- Exchanges / mercado ---
    exchanges: dict[str, ExchangeConfig] = Field(default_factory=_default_exchanges)
    quote_target: str = "USD"          # todo se normaliza a USD
    ingest_autostart: bool = True      # arranca feeds en el lifespan (False en tests)
    ingest_max_backoff: float = 30.0   # tope de reconexión exponencial (C1)

    # --- Bus / concurrencia (C4, C11) ---
    bus_maxsize: int = 1000            # cola acotada, política drop-oldest
    sse_client_queue_maxsize: int = 500
    # Tope de clientes SSE concurrentes: cada cliente cuesta una cola de `maxsize` eventos en
    # memoria y /stream no pasa por el rate limiter (streaming + BaseHTTPMiddleware no conviven),
    # así que sin cota es un vector de DoS trivial en el deploy público. 0 = sin límite (dev).
    sse_max_clients: int = 64
    sse_ping_seconds: int = 15
    quote_throttle_ms: int = 100       # máx. ~10 quotes/s por venue hacia el cliente

    # --- Normalización de moneda / peg (C3, FR-003) ---
    peg_pairs: dict[str, str] = Field(default_factory=lambda: {"USDT": "USDT/USD"})
    peg_source_exchange: str = "kraken"
    peg_tolerance: float = 0.005       # ±0.5%

    # --- Neto / ejecución (C6, C9) ---
    min_net_profit_usd: float = 0.0    # umbral de margen neto por trade
    net_margin_buffer_bps: float = 0.0  # colchón sobre ruido de peg
    max_slippage: float = 0.0010       # 0.10% filtro pre-trade
    exec_latency_ms: int = 150         # latencia simulada (leg risk, 100-200)
    default_trade_qty_btc: float = 1.0
    # F1 — amortización del rebalanceo por CICLO (no por trade). El coste on-chain fijo
    # (wd_buy+wd_sell) se reparte entre los trades esperados antes de rebalancear. Default 1.0
    # = un rebalanceo completo por trade (conservador, comportamiento histórico). >1 lo amortiza.
    # OJO: es la métrica de DECISIÓN del evaluador/proyección; NO debe duplicar el débito real
    # del `Rebalancer` periódico (C10/STORY-017), que es el único que toca el ledger.
    expected_trades_per_rebalance: float = Field(default=1.0, gt=0.0)

    # --- Estrategia estadística / z-score (C5, FR-006) ---
    # gt=1: con W<=1 la std de población es 0 (degenera a no-op) y numpy emitiría warning.
    zscore_window: int = Field(default=200, gt=1)  # W (100-300 ticks)
    z_open: float = 2.0
    z_close: float = 0.5
    z_stop: float = 3.0

    # --- Priorización / ranking por score (C7, FR-007) ---
    # score = E[neto] × P(fill) × factor_liquidez − penalización_riesgo (Apéndice D.4).
    score_pfill_floor: float = Field(default=0.05, ge=0.0, le=1.0)  # P(fill) mínimo (>0)
    # Penalización de riesgo de ejecución: bps de deriva adversa por segundo de latencia
    # aplicados sobre el notional (proxy de leg risk durante la ventana de ejecución).
    score_risk_aversion_bps: float = Field(default=10.0, ge=0.0)

    # --- Backtesting record & replay (C14, FR-014) ---
    record_enabled: bool = True          # graba books normalizados para replay/demo
    record_maxlen: int = Field(default=20_000, gt=0)  # tope del buffer de grabación (ring)
    backtest_in_sample_frac: float = Field(default=0.7, gt=0.0, lt=1.0)  # split in/out-of-sample

    # --- Riesgo / breakers (C8, FR-012) ---
    staleness_ms: int = Field(default=750, gt=0)          # excluye venue del cómputo
    watchdog_interval_ms: int = Field(default=250, gt=0)  # cadencia (≈ staleness/3)
    inventory_skew_limit: float = 0.5  # fracción de desvío permitido
    max_drawdown_usd: float = 5_000.0
    volatility_breaker_bps: float = 200.0
    # Circuit breakers (C8, FR-012, STORY-018): cadencia del monitor y ventana de volatilidad.
    breaker_interval_ms: int = Field(default=500, gt=0)    # recomputa breakers (auto)
    volatility_window_ms: int = Field(default=5_000, gt=0)  # rango de mid para el breaker vol
    # Rebalanceo de inventario periódico (C10, FR-011, STORY-017): cadencia del chequeo de
    # drift. NO por trade — evento periódico que sólo actúa si el skew supera el límite.
    rebalance_interval_ms: int = Field(default=30_000, gt=0)

    # --- Integridad de book por exchange (PRD-004) ---
    # generic: sólo estructura/seq genérica. warn: reporta gaps/checksum por venue sin bloquear.
    # enforce: bloquea también los fallos específicos por venue.
    integrity_mode: Literal["generic", "warn", "enforce"] = "warn"

    # --- Fallback a replay para demo (C16, FR-018, STORY-024) ---
    demo_fallback_enabled: bool = True       # arma el controlador en el lifespan
    demo_stale_ms: int = Field(default=2_000, gt=0)  # sin dato real > esto → activa replay
    demo_replay_interval_ms: int = Field(default=50, gt=0)  # cadencia de inyección de ticks
    demo_recording_path: str = ""            # JSONL de respaldo si el buffer vivo está vacío

    # --- Ejecución protegida / testnet (PRD-003) ---
    # Default agresivamente seguro: ninguna ruta de ejecución queda activa sin opt-in explícito.
    execution_mode: Literal["disabled", "dry_run", "testnet"] = "disabled"
    enable_test_orders: bool = False
    execution_request_timeout_s: float = Field(default=5.0, gt=0.0)
    binance_testnet_api_key: str = ""
    binance_testnet_api_secret: str = ""
    binance_testnet_base_url: str = "https://testnet.binance.vision"
    # Balance local usado por el adapter determinista de testnet/dry_run. No representa dinero
    # real; sirve para probar min-notional/lot/balance sin tocar red ni credenciales.
    execution_local_btc_balance: float = Field(default=1.0, ge=0.0)
    execution_local_quote_balance_usd: float = Field(default=100_000.0, ge=0.0)

    # --- Métricas del jurado (C13, FR-017, NFR-001/010, STORY-022) ---
    metrics_window: int = Field(default=2_000, gt=0)   # muestras por métrica en ventana
    lifetime_gap_ms: int = Field(default=250, gt=0)    # gap que cierra un episodio de cruce
    metrics_emit_ms: int = Field(default=1_000, gt=0)  # cadencia máx. del push SSE de métricas

    # --- Extensiones de mercado (PRD-008) ---
    # Opt-in explícito: el flujo principal spot cross-exchange sigue siendo la demo primaria.
    strategy_triangular_enabled: bool = False
    strategy_triangular_start_currency: str = "USD"
    strategy_triangular_trade_size: float = Field(default=1_000.0, gt=0.0)
    strategy_triangular_min_profit_bps: float = Field(default=0.0, ge=0.0)
    strategy_funding_enabled: bool = False
    strategy_funding_hedge_cost_bps: float = Field(default=0.0, ge=0.0)
    strategy_regional_mxn_enabled: bool = False
    strategy_mxn_usd_rate: float | None = Field(default=None, gt=0.0)
    strategy_mxn_fiat_fee_bps: float = Field(default=20.0, ge=0.0)

    # --- Calibración de supervivencia (PRD-005) ---
    calibration_mode: Literal["observe_only", "report", "score", "gate"] = "observe_only"
    shadow_sample_maxlen: int = Field(default=20_000, gt=0)
    survival_latencies_ms: list[int] = Field(
        default_factory=lambda: [50, 100, 200, 500, 1000]
    )

    # --- Persistencia (C12, FR-013) ---
    db_url: str = "sqlite+aiosqlite:///./arbitraje.db"
    store_batch_size: int = 100
    store_flush_seconds: float = 1.0
    # Retención: las opportunities se insertan a ~36/s; sin poda la DB crece sin límite
    # (~28 MB/h, ~670 MB/día). `db_retention_hours`=0 → sin límite (comportamiento previo).
    db_retention_hours: float = 24.0
    db_prune_interval_s: float = 300.0  # cada cuánto corre la poda de fondo
    db_vacuum_on_prune: bool = False    # VACUUM tras podar (recupera espacio en disco; costoso)

    @model_validator(mode="after")
    def _require_control_token_in_prod(self) -> Settings:
        """En prod el plano de control NUNCA arranca sin auth: con token vacío, kill-switch,
        purga de BD y rewrites de config quedarían abiertos a Internet. Fallar el arranque es
        deliberado — un deploy inseguro debe ser imposible de levantar por accidente."""
        if self.env == "prod" and not self.control_token:
            raise ValueError(
                "ARB_CONTROL_TOKEN es obligatorio con ARB_ENV=prod: los endpoints de control "
                "(kill-switch, retención, config) no pueden quedar sin auth en un deploy público."
            )
        return self

    @property
    def enabled_exchanges(self) -> list[ExchangeConfig]:
        return [e for e in self.exchanges.values() if e.enabled]


@lru_cache
def get_settings() -> Settings:
    return Settings()
