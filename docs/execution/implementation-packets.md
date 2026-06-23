# Paquetes de implementación

Cada paquete define cómo arrancar una épica sin volver a leer todo el contexto. El work breakdown contiene tareas; este documento da la secuencia práctica de implementación.

## Paquete 001: Opportunity Explain

Rama sugerida: `feature/opportunity-explain`

Orden:

1. Crear `backend/app/models/explain.py`.
2. Crear `backend/app/engine/explain.py` con builder puro.
3. Agregar `opps_by_id` en `AppState`.
4. Integrar explanation parcial en `NetEvaluator.evaluate`.
5. Agregar endpoint `/api/v1/opportunities/{id}/explain`.
6. Agregar tipos TS y drawer UI.

Validación:

```bash
cd backend
uv run pytest tests/test_evaluator.py tests/test_cost_model.py
```

Luego agregar tests nuevos y correr:

```bash
uv run pytest
cd ../frontend
npm run typecheck
npm run lint
```

## Paquete 002: Demo determinista

Rama sugerida: `feature/jury-demo-export`

Orden:

1. Crear `backend/app/demo/scenarios.py`.
2. Crear `backend/app/demo/jury.py`.
3. Extender `POST /api/v1/demo?mode=jury`.
4. Crear `backend/app/models/session.py`.
5. Agregar `/api/v1/session/export`.
6. Agregar controles UI y actualizar guion.

Validación:

```bash
cd backend
uv run pytest tests/test_demo.py tests/test_stream.py
```

## Paquete 003: Testnet preflight

Rama sugerida: `feature/testnet-preflight`

Orden:

1. Agregar settings disabled por defecto.
2. Crear modelos preflight.
3. Crear adapter fake y registry.
4. Agregar endpoints protegidos.
5. Agregar Binance adapter detrás de flag.
6. Agregar UI mínima en drawer.

Validación:

```bash
cd backend
uv run pytest tests/test_config.py tests/test_control_auth.py
```

Gate obligatorio: ninguna ruta ejecuta test order sin `ARB_EXECUTION_MODE=testnet`, `ARB_ENABLE_TEST_ORDERS=true` y token de control.

## Paquete 004: Integridad por exchange

Rama sugerida: `feature/exchange-integrity`

Orden:

1. Agregar `RawOrderBook.meta`.
2. Extraer validator genérico.
3. Crear reportes extendidos.
4. Agregar registry por venue.
5. Implementar Binance en modo `warn`.
6. Implementar Kraken/Coinbase en modo `warn`.
7. Exponer `/api/v1/integrity`.

Validación:

```bash
cd backend
uv run pytest tests/test_integrity.py tests/test_ingest.py tests/test_health.py
```

## Paquete 005: Calibración

Rama sugerida: `feature/survival-calibration`

Orden:

1. Crear modelos de calibración.
2. Agregar ring buffer de shadow samples.
3. Capturar samples en `on_opp`.
4. Implementar future book lookup.
5. Implementar evaluator y buckets.
6. Exponer `/api/v1/calibration/survival`.

Validación:

```bash
cd backend
uv run pytest tests/test_backtest.py tests/test_projection.py tests/test_metrics.py
```

Gate obligatorio: modo inicial `observe_only`.

## Paquete 006: Observabilidad

Rama sugerida: `feature/ops-observability`

Orden:

1. Extender `/health`.
2. Crear renderer Prometheus.
3. Agregar `/metrics`.
4. Conectar métricas de integrity/demo/breakers/preflight.
5. Revisar runbooks.

Validación:

```bash
cd backend
uv run pytest tests/test_health.py tests/test_metrics.py tests/test_breakers.py
```

## Paquete 007: Rendimiento

Rama sugerida: `feature/depth-curves`

Orden:

1. Crear script de profiling.
2. Crear `DepthCurve`.
3. Probar equivalencia contra `walk_book`.
4. Integrar en `projection/frontier.py`.
5. Integrar en `projection/capacity.py`.
6. Medir antes/después.

Validación:

```bash
cd backend
uv run pytest tests/test_cost_model.py tests/test_projection.py tests/test_capacity.py
```

Gate obligatorio: resultados equivalentes dentro de tolerancia.

## Paquete 008: Extensiones de mercado

Rama sugerida: `feature/strategy-modules`

Orden:

1. Crear interfaz `StrategyModule`.
2. Adaptar spatial/stat actuales sin cambiar comportamiento.
3. Separar métricas por estrategia.
4. Implementar triangular solo demo/replay.
5. Implementar funding read-only.
6. Implementar MXN experimental.

Validación:

```bash
cd backend
uv run pytest tests/test_detect.py tests/test_statz.py tests/test_metrics.py
```

Gate obligatorio: estrategias nuevas desactivadas por defecto.

