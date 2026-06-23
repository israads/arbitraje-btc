# Arquitecturas de implementación

Fecha: 18 de junio de 2026.

Esta carpeta baja los PRDs a arquitectura técnica. Cada documento describe cómo implementar la épica sin romper la arquitectura actual: módulos nuevos, archivos existentes a tocar, contratos, flujos, pruebas y secuencia de rollout.

Documentos relacionados:

- [PRDs de ejecución](../prd/README.md)
- [Plan de ejecución al 100%](../execution/README.md)

## Principios

- Mantener el monolito modular: una sola app FastAPI con módulos claros.
- Mantener la ruta caliente simple: nada de red, LLM o serialización pesada en el evaluador.
- Preferir builders puros y modelos Pydantic para contratos estables.
- Desactivar por defecto cualquier ruta cercana a ejecución real.
- Exponer la diferencia entre "spread bruto" y "edge ejecutable" en API y UI.
- Instrumentar antes de optimizar.

## Índice

| PRD | Arquitectura | Objetivo técnico |
|---|---|---|
| PRD-001 | [Opportunity Explain + Naive Comparison](001-opportunity-explain-naive-comparison.md) | Explicación por oportunidad sin duplicar fórmula económica |
| PRD-002 | [Demo determinista + export de sesión](002-deterministic-demo-session-export.md) | Escenarios reproducibles y exportables |
| PRD-003 | [Testnet preflight + test order](003-testnet-preflight-test-order.md) | Adapter seguro para validación/test order |
| PRD-004 | [Integridad específica por exchange](004-exchange-specific-integrity.md) | Validadores por venue y reportes de calidad |
| PRD-005 | [Calibración de supervivencia](005-survival-calibration-shadow-replay.md) | Dataset shadow y calibración de `P_survive` |
| PRD-006 | [Observabilidad y operación](006-observability-operations.md) | Métricas, health operacional y runbooks |
| PRD-007 | [Rendimiento y curvas de profundidad](007-performance-depth-curves.md) | Depth curves, profiling y optimización segura |
| PRD-008 | [Extensiones de mercado](008-market-extensions.md) | Interfaz de estrategias para triangular/funding/MXN |

## Secuencia de construcción

```text
Semana 1: PRD-001 + PRD-002
Semana 2: PRD-003 + PRD-004
Semana 3: PRD-005 + PRD-006
Semana 4: PRD-007
Después: PRD-008
```

La primera semana debe producir una demo superior aunque no exista testnet ni calibración todavía. La explicación por oportunidad desbloquea el resto porque crea el contrato visual y de datos que usarán demo, calibración y nuevas estrategias.
