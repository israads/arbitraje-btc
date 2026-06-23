# Work breakdown

Este documento descompone todos los PRDs en tareas implementables. Los IDs se pueden usar como issues.

## PRD-001: Opportunity Explain + Naive Comparison

| ID | Tarea | Archivos principales | Tests |
|---|---|---|---|
| 001-A | Crear modelos `CostComponent`, `NaiveComparison`, `EngineDecision`, `OpportunityExplanation` | `backend/app/models/explain.py` | serialización Pydantic |
| 001-B | Crear builder puro de explicación | `backend/app/engine/explain.py` | viable, descartada, thin book |
| 001-C | Agregar lookup `opps_by_id` acotado | `backend/app/state.py` | pruning y lookup |
| 001-D | Integrar builder en evaluator/main sin duplicar fórmula | `backend/app/engine/evaluator.py`, `backend/app/main.py` | no cambia neto existente |
| 001-E | Endpoint `GET /api/v1/opportunities/{id}/explain` | `backend/app/api/v1/router.py` | 200, 404, contrato JSON |
| 001-F | Tipos TS y fetch de explanation | `frontend/hooks/useStream.ts` | typecheck |
| 001-G | Drawer UI de explicación | `frontend/components/OpportunityExplainDrawer.tsx` | render estados |
| 001-H | Panel naive vs engine | `frontend/components/NaiveVsEnginePanel.tsx` | render viable/descartada |

## PRD-002: Demo determinista + export de sesión

| ID | Tarea | Archivos principales | Tests |
|---|---|---|---|
| 002-A | Crear fixtures de scenarios | `backend/app/demo/scenarios.py` | escenarios válidos |
| 002-B | Crear `JuryScenarioPlayer` | `backend/app/demo/jury.py` | orden y ciclo |
| 002-C | Integrar `mode=jury` | `backend/app/demo/fallback.py`, `router.py` | modo sin red |
| 002-D | Extender demo status con scenario | `backend/app/models` o dict actual | contrato |
| 002-E | Crear `SessionExport` | `backend/app/models/session.py` | redacción de settings |
| 002-F | Endpoint `/api/v1/session/export` | `router.py` | contrato y sin secretos |
| 002-G | Botón `JURY DEMO` y export | `ControlPanel.tsx` | UI básica |
| 002-H | Actualizar guion demo | `docs/guion-demo-jurado.md` | revisión manual |

## PRD-003: Testnet preflight + test order

| ID | Tarea | Archivos principales | Tests |
|---|---|---|---|
| 003-A | Settings de ejecución disabled por defecto | `backend/app/config.py` | defaults seguros |
| 003-B | Modelos preflight/test order | `backend/app/models/preflight.py` | serialización |
| 003-C | Registry de adapters | `backend/app/execution/registry.py` | venue desconocido |
| 003-D | Adapter fake para tests | `backend/app/execution/preflight.py` | checks locales |
| 003-E | Binance testnet adapter | `backend/app/execution/binance.py` | requests firmados mock |
| 003-F | Endpoints preflight/test-order/status | `router.py` | auth, flags, contrato |
| 003-G | UI mínima de preflight | drawer de PRD-001 | estados accepted/rejected |
| 003-H | Documentar env vars | README/docs | revisión manual |

## PRD-004: Integridad específica por exchange

| ID | Tarea | Archivos principales | Tests |
|---|---|---|---|
| 004-A | Agregar `RawOrderBook.meta` | `backend/app/models/market.py` | compatibilidad |
| 004-B | Extraer validator genérico | `backend/app/integrity/validators.py` | tests actuales pasan |
| 004-C | Reporte extendido | `backend/app/integrity/models.py` | counters |
| 004-D | Registry por venue | `checker.py` | fallback generic |
| 004-E | Binance sequence validator | `integrity/binance.py` | gaps/regresiones |
| 004-F | Kraken checksum validator | `integrity/kraken.py` | checksum fixture |
| 004-G | Coinbase gap validator | `integrity/coinbase.py` | sequence gaps |
| 004-H | Endpoint `/api/v1/integrity` | `router.py` | contrato |

## PRD-005: Calibración de supervivencia

| ID | Tarea | Archivos principales | Tests |
|---|---|---|---|
| 005-A | Modelo `ShadowOpportunitySample` | `models/calibration.py` | serialización |
| 005-B | Ring buffer de samples | `state.py` | maxlen |
| 005-C | Captura de sample | `main.py` | no cambia decisión |
| 005-D | Future book lookup point-in-time | `backtest/replay.py` | anti look-ahead |
| 005-E | Evaluador de supervivencia | `calibration/survival.py` | true/false/missing |
| 005-F | Bucketing de calibración | `calibration/survival.py` | observed rate |
| 005-G | Endpoint `/api/v1/calibration/survival` | `router.py` | contrato |
| 005-H | Panel de calibración | frontend component | render confidence |

## PRD-006: Observabilidad y operación

| ID | Tarea | Archivos principales | Tests |
|---|---|---|---|
| 006-A | Health operacional | `backend/app/api/health.py` | contrato |
| 006-B | Render Prometheus | `backend/app/metrics/prometheus.py` | formato |
| 006-C | Endpoint `/metrics` | app/router | content-type |
| 006-D | Métricas integrity/breakers/demo/preflight | collector/prometheus | valores |
| 006-E | Logs estructurados críticos | logging/main/integrity/execution | revisión |
| 006-F | Runbook feed stale | `docs/runbooks/feed-stale.md` | revisión |
| 006-G | Runbook peg/high latency/kill/preflight | `docs/runbooks/*.md` | revisión |

## PRD-007: Rendimiento y curvas de profundidad

| ID | Tarea | Archivos principales | Tests |
|---|---|---|---|
| 007-A | Script profile engine | `scripts/profile_engine.py`, `Makefile` | smoke |
| 007-B | `DepthCurve` | `engine/depth_curve.py` | equivalencia |
| 007-C | Integrar en frontier | `projection/frontier.py` | resultados iguales |
| 007-D | Integrar en capacity | `projection/capacity.py` | resultados iguales |
| 007-E | Benchmark antes/después | docs/execution o output | revisión |

## PRD-008: Extensiones de mercado

| ID | Tarea | Archivos principales | Tests |
|---|---|---|---|
| 008-A | Interfaz `StrategyModule` | `backend/app/strategies/base.py` | contrato |
| 008-B | Adapter para spatial/stat actuales | `strategies/*` | no regresión |
| 008-C | Métricas por estrategia | `metrics/collector.py` | separación |
| 008-D | Triangular demo/replay | `strategies/triangular.py` | fees/profundidad |
| 008-E | Funding read-only | `strategies/funding.py` | no ejecución |
| 008-F | Regional MXN experimental | `strategies/regional_mxn.py` | FX requerido |

