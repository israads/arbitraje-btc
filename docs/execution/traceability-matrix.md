# Matriz de trazabilidad

Esta matriz conecta requisitos, arquitectura, tareas y validación. Sirve para revisar que cada épica pueda pasar de documentación a implementación sin ambigüedad.

| PRD | Arquitectura | Tareas | Validación mínima | Gate crítico |
|---|---|---|---|---|
| [PRD-001](../prd/001-opportunity-explain-naive-comparison.md) | [Arquitectura 001](../architecture/001-opportunity-explain-naive-comparison.md) | 001-A a 001-H | Endpoint explain 200/404, drawer renderiza viable/descartada, neto no cambia | Correctitud financiera |
| [PRD-002](../prd/002-deterministic-demo-session-export.md) | [Arquitectura 002](../architecture/002-deterministic-demo-session-export.md) | 002-A a 002-H | `mode=jury`, escenarios visibles, export sin secretos | Seguridad operacional |
| [PRD-003](../prd/003-testnet-preflight-test-order.md) | [Arquitectura 003](../architecture/003-testnet-preflight-test-order.md) | 003-A a 003-H | Disabled por defecto, token requerido, test order bloqueado sin flag | Seguridad operacional |
| [PRD-004](../prd/004-exchange-specific-integrity.md) | [Arquitectura 004](../architecture/004-exchange-specific-integrity.md) | 004-A a 004-H | Gap/checksum visible, rejected book no actualiza estado vivo | Integridad de datos |
| [PRD-005](../prd/005-survival-calibration-shadow-replay.md) | [Arquitectura 005](../architecture/005-survival-calibration-shadow-replay.md) | 005-A a 005-H | Observe-only, anti look-ahead, buckets con confianza | Correctitud financiera |
| [PRD-006](../prd/006-observability-operations.md) | [Arquitectura 006](../architecture/006-observability-operations.md) | 006-A a 006-G | `/metrics`, health operacional, runbooks | Observabilidad |
| [PRD-007](../prd/007-performance-depth-curves.md) | [Arquitectura 007](../architecture/007-performance-depth-curves.md) | 007-A a 007-E | DepthCurve == walk_book, benchmark antes/después | Pruebas |
| [PRD-008](../prd/008-market-extensions.md) | [Arquitectura 008](../architecture/008-market-extensions.md) | 008-A a 008-F | Estrategias desactivables, métricas separadas, no mezcla riesgos | Compatibilidad |

## Reglas de revisión antes de merge

Para cada PR:

1. Identificar el ID de tarea del work breakdown.
2. Confirmar que el PRD no cambió de alcance.
3. Confirmar que la arquitectura sigue siendo válida.
4. Ejecutar los tests definidos.
5. Revisar quality gates aplicables.
6. Actualizar documentación si cambió contrato, config o UI.

## Señales de bloqueo

No mergear si ocurre cualquiera de estas condiciones:

- Se duplica cálculo financiero fuera de `ExecutionCostModel`.
- Un endpoint nuevo expone secretos o payload firmado.
- Una mejora de demo no etiqueta claramente datos demo.
- Una validación de integridad bloquea feeds en modo inicial sin pasar por `warn`.
- `P_survive` calibrado afecta decisión antes de tener muestra suficiente.
- Una extensión de mercado mezcla PnL/riesgo con spot cross-exchange sin etiqueta.

