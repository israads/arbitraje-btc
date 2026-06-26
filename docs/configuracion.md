# Configuración del sistema

Todo lo que se puede configurar en el motor de arbitraje, qué controla cada cosa y qué necesitas
para que funcione (wallet, cuentas, montos). El motor **arranca sin configurar nada**: todos los
campos tienen defaults razonables y el flujo principal es simulación con datos públicos.

## Cómo se configura

- **Defaults en código:** `backend/app/config.py` (`Settings`, `ExchangeConfig`).
- **Override por entorno:** variables con prefijo `ARB_` (anidadas con `__`). Ej.
  `ARB_DEFAULT_TRADE_QTY_BTC=0.5`, `ARB_EXCHANGES__BINANCE__FEE_TAKER=0.0008`.
- **Archivo `.env`:** ver `backend/.env.example`.
- **En caliente desde la UI:** retención de BD (`PATCH /storage/retention`, operativo real) y
  Strategy Lab (`PATCH /params`, what-if / read-only — no muta el motor vivo).

---

## 1. Wallet y cuentas — lo mínimo para operar

El capital es **inventario pre-posicionado por exchange** (no hay transferencias on-chain). Se
siembra desde `ExchangeConfig` de cada venue habilitado (`app/sim/inventory.py`).

| Necesitas | Campo | Default | Notas |
|-----------|-------|---------|-------|
| Saldo BTC por venue | `ExchangeConfig.initial_btc` | 2.0 | inventario inicial para vender |
| Saldo quote por venue | `ExchangeConfig.initial_quote` | 100 000 | USD/USDT para comprar |
| Símbolo del par | `ExchangeConfig.symbol` | p.ej. `BTC/USDT` | unificado ccxt |
| Moneda de cotización | `ExchangeConfig.quote_ccy` | `USDT`/`USD` | usado para normalizar a USD |
| Venue activo | `ExchangeConfig.enabled` | `true` | filtra `enabled_exchanges` |

**Credenciales / API keys:** el flujo principal (spot cross-exchange, ingesta pública, simulación)
**no necesita credenciales**. Solo existen para **Binance testnet** (ejecución protegida, opt-in y
desactivada por defecto): `ARB_BINANCE_TESTNET_API_KEY`, `ARB_BINANCE_TESTNET_API_SECRET`.

**Exchanges por defecto** (`config.py:_default_exchanges`):
- Habilitados: kraken, coinbase, gemini, bitstamp, binance, bybit, bitget, kucoin, gateio.
- Deshabilitados: bitfinex, okx (`enabled=false`).
- Bitso (BTC/MXN) queda fuera por ahora (sin ccxt.pro); ver corredor MXN abajo.

---

## 2. Montos, fees y umbrales de decisión

| Campo | Default | Controla |
|-------|---------|----------|
| `default_trade_qty_btc` | 1.0 | tamaño objetivo por trade (BTC) |
| `min_net_profit_usd` | 0.0 | **monto mínimo** de neto para considerar viable |
| `net_margin_buffer_bps` | 0.0 | colchón extra exigido al margen |
| `max_slippage` | 0.0010 | slippage máximo tolerado (fracción) |
| `exec_latency_ms` | 150 | latencia simulada de ejecución |
| `expected_trades_per_rebalance` | 1.0 | amortización del coste de rebalanceo |
| `ExchangeConfig.fee_taker` | por venue | fee taker (fracción, 0.0010 = 0.10%) |
| `ExchangeConfig.withdrawal_btc` | por venue | BTC por retiro (coste de rebalanceo) |
| `ExchangeConfig.ob_limit` | por venue | profundidad válida del order book |

> No hay un "monto máximo" por trade como tope duro: el límite real lo imponen la **capacidad del
> libro** (ver Capacity Curve) y el **balance disponible** (`can_afford`). El tope de la UI para el
> tamaño what-if es 10 BTC.

## 3. Estrategia (z-score) y priorización

| Campo | Default | Controla |
|-------|---------|----------|
| `zscore_window` | 200 | ventana del z-score del spread |
| `z_open` / `z_close` / `z_stop` | 2.0 / 0.5 / 3.0 | umbrales de apertura/cierre/stop |
| `score_pfill_floor` | 0.05 | piso de probabilidad de fill en el score |
| `score_risk_aversion_bps` | 10.0 | aversión al riesgo en la priorización |

## 4. Peg / normalización de stablecoin

| Campo | Default | Controla |
|-------|---------|----------|
| `peg_pairs` | `{USDT: USDT/USD}` | pares para estimar el peg |
| `peg_source_exchange` | `kraken` | venue de referencia del peg |
| `peg_tolerance` | 0.005 | banda ±0.5% antes de penalizar |
| `quote_target` | `USD` | moneda de normalización global |

## 5. Riesgo y circuit breakers

| Campo | Default | Controla |
|-------|---------|----------|
| `staleness_ms` | 750 | edad máxima de un book antes de "stale" |
| `inventory_skew_limit` | 0.5 | desbalance de inventario tolerado |
| `max_drawdown_usd` | 5 000 | drawdown que dispara el breaker |
| `volatility_breaker_bps` | 200 | volatilidad que dispara el breaker |
| `rebalance_interval_ms` | 30 000 | cadencia del rebalanceador |
| `integrity_mode` | `warn` | `generic` / `warn` / `enforce` (CRC/secuencia de book) |

## 6. Ejecución protegida (opt-in, desactivada por defecto)

| Campo | Default | Controla |
|-------|---------|----------|
| `execution_mode` | `disabled` | `disabled` / `dry_run` / `testnet` |
| `enable_test_orders` | `false` | permite órdenes de prueba |
| `binance_testnet_api_key/secret` | "" | credenciales testnet |
| `execution_local_btc_balance` | 1.0 | balance del adapter determinista |
| `execution_local_quote_balance_usd` | 100 000 | balance quote del adapter |

## 7. Extensiones de mercado (desactivadas por defecto)

| Campo | Default | Controla |
|-------|---------|----------|
| `strategy_triangular_enabled` | `false` | arbitraje triangular intra-venue |
| `strategy_triangular_trade_size` | 1 000 | tamaño de la pierna triangular |
| `strategy_funding_enabled` | `false` | funding/basis |
| `strategy_regional_mxn_enabled` | `false` | corredor México (Bitso/MXN) |
| `strategy_mxn_usd_rate` | `null` | tipo de cambio MXN/USD |
| `strategy_mxn_fiat_fee_bps` | 20.0 | fee fiat del corredor MXN |

## 8. Almacenamiento y retención (configurable en caliente)

La BD (SQLite + SQLAlchemy async) persiste `opportunities` y `executions`. **Sin retención crece
sin límite** (~36 opps/s ≈ **28 MB/h, 670 MB/día**; en pruebas llegó a 14 GB en ~21 días).

| Campo | Default | Controla |
|-------|---------|----------|
| `db_url` | `sqlite+aiosqlite:///./arbitraje.db` | ubicación de la BD |
| `db_retention_hours` | 24.0 | horas de histórico a conservar (0 = sin límite) |
| `db_prune_interval_s` | 300.0 | cada cuánto corre la poda de fondo |
| `db_vacuum_on_prune` | false | `VACUUM` tras podar (recupera disco; costoso) |
| `store_batch_size` | 100 | tamaño de lote del writer |
| `store_flush_seconds` | 1.0 | flush periódico del writer |

**Estimación de tamaño en estado estacionario** (medida real, 217 B/fila):

| Retención | Tamaño BD |
|-----------|-----------|
| 1 h | ~28 MB |
| 6 h | ~167 MB |
| 12 h | ~334 MB |
| 18 h | ~502 MB |
| 24 h | ~669 MB |

Se ajusta desde el panel **Almacenamiento** del dashboard (`PATCH /storage/retention`), que poda de
inmediato y re-mide. Estado en vivo en `GET /storage`.

## 9. Strategy Lab (what-if, no muta el motor vivo)

`PATCH /params` guarda overrides que afectan **solo** what-if, proyecciones y export auditable
(`default_trade_qty_btc`, `fee_bps`, `exec_latency_ms`, `max_slippage`,
`expected_trades_per_rebalance`, `n_paths`, z-scores, `peg_tolerance`, `inventory_skew_limit`,
`enabled_exchange_overrides`). Es deliberado: no se cambian umbrales operativos por un movimiento de
UI. `POST /params/reset` los limpia.

---

## App / servidor

`app_name`, `env` (`dev`), `log_level`, `cors_origins` (`http://localhost:3000`), `control_token`
(token estático para endpoints de control; vacío = sin auth en dev).
