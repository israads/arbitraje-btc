# PRDs de ejecución

Fecha: 18 de junio de 2026.

Estos PRDs convierten la investigación competitiva y el análisis interno del repo en un plan ejecutable. El objetivo no es agregar features por volumen, sino convertir `arbitraje·btc` en un sistema que un jurado y un ingeniero puedan auditar: por qué vio una oportunidad, por qué la descartó o aceptó, y qué tendría que pasar para ejecutarla de forma controlada.

Documentos relacionados:

- [Arquitecturas de implementación](../architecture/README.md)
- [Plan de ejecución al 100%](../execution/README.md)

## Tesis del producto

El proyecto debe ganar por una diferencia clara:

> no detecta spreads; calcula capturabilidad bajo fricciones reales.

Eso exige tres pruebas visibles:

1. Explicar cada decisión con números.
2. Demostrar readiness de ejecución sin dinero real.
3. Probar que los datos de mercado son confiables.

## Línea base actual

| Área | Ya existe | Brecha principal |
|---|---|---|
| Motor económico | VWAP, fees, slippage, rebalance, peg, neto compartido en `ExecutionCostModel` | Brecha: breakdown persistido por oportunidad y explicación API/UI |
| Proyección | Frontier, capacity, forward, `P_survive` | `P_survive` todavía es heurístico, no calibrado con replay |
| Riesgo | Breakers, kill switch, watchdog, inventario, leg risk | Brecha: matriz operacional visible y preflight estilo ejecución real |
| Datos | Ingesta multi-venue, normalización, integridad estructural | Brecha: integridad específica por exchange: sequence/checksum/gaps |
| Demo | Dashboard, waterfall, funnel, fallback demo | Brecha: demo determinista empaquetada y exportable para jurado |
| UI | Tablas y paneles densos de decisión | Brecha: comparación "bot ingenuo vs motor" e inspector por oportunidad |
| Operación | Persistencia batch, métricas, health, deploy docs, runbooks base | Brecha: exporter/health operacional y métricas estándar |
| Escala de mercado | Cross-exchange spot BTC + módulos opt-in PRD-008 | Brecha futura: ingesta live de funding/MXN y UI dedicada |

## Orden de ejecución recomendado

| Orden | PRD | Arquitectura | Prioridad | Por qué va primero |
|---:|---|---|---:|---|
| 1 | [PRD-001 Opportunity Explain + Naive Comparison](001-opportunity-explain-naive-comparison.md) | [Arquitectura](../architecture/001-opportunity-explain-naive-comparison.md) | P0 | Hace visible la superioridad del motor |
| 2 | [PRD-002 Demo determinista + export de sesión](002-deterministic-demo-session-export.md) | [Arquitectura](../architecture/002-deterministic-demo-session-export.md) | P0 | Permite evaluación rápida y reproducible |
| 3 | [PRD-003 Testnet preflight + test order](003-testnet-preflight-test-order.md) | [Arquitectura](../architecture/003-testnet-preflight-test-order.md) | P1 | Demuestra readiness sin dinero real |
| 4 | [PRD-004 Integridad específica por exchange](004-exchange-specific-integrity.md) | [Arquitectura](../architecture/004-exchange-specific-integrity.md) | P1 | Evita decisiones sobre books corruptos |
| 5 | [PRD-005 Calibración de supervivencia con replay](005-survival-calibration-shadow-replay.md) | [Arquitectura](../architecture/005-survival-calibration-shadow-replay.md) | P1 | Convierte `P_survive` de heurística a señal medible |
| 6 | [PRD-006 Observabilidad y operación](006-observability-operations.md) | [Arquitectura](../architecture/006-observability-operations.md) | P2 | Vuelve operable el sistema |
| 7 | [PRD-007 Rendimiento y curvas de profundidad](007-performance-depth-curves.md) | [Arquitectura](../architecture/007-performance-depth-curves.md) | P2 | Reduce costo del hot path antes de escalar |
| 8 | [PRD-008 Extensiones de mercado](008-market-extensions.md) | [Arquitectura](../architecture/008-market-extensions.md) | P3 | Amplía superficie después de cerrar confianza |

## Dependencias

```text
PRD-001 -> PRD-002
PRD-001 -> PRD-005
PRD-004 -> PRD-005
PRD-003 -> PRD-006
PRD-007 -> PRD-008
```

La ruta crítica para una versión superior de competencia es:

```text
Explain API/UI -> Demo reproducible -> Preflight testnet -> Integridad por venue -> Calibración
```

## Primer sprint recomendado

El primer sprint debe cerrar P0 y dejar el proyecto listo para una demo superior. No conviene empezar por triangular, funding o rendimiento hasta que la decisión principal sea visible. El desglose completo de tareas vive en [work-breakdown.md](../execution/work-breakdown.md).

| Día | Trabajo | Resultado |
|---:|---|---|
| 1 | Crear modelos `OpportunityExplanation`, `NaiveComparison` y tests de serialización | Contrato estable para explicación |
| 2 | Implementar builder puro de explicación usando `ExecutionCostModel` | No se duplica fórmula económica |
| 3 | Agregar `GET /api/v1/opportunities/{id}/explain` | API auditable por oportunidad |
| 4 | Crear drawer UI `OpportunityExplainDrawer` | Jurado ve naive vs engine |
| 5 | Agregar fixtures de demo determinista `good_edge` y `naive_trap` | Demo reproducible mínima |
| 6 | Agregar escenarios `peg_adverse`, `stale_feed`, `latency_decay` | Demo completa de 90 segundos |
| 7 | Export de sesión y actualización del guion de demo | Evidencia compartible |

## Definición global de terminado

Un PRD no está completo hasta que cumpla estas condiciones:

- Tiene tests unitarios o de contrato para los cambios principales.
- No rompe endpoints existentes.
- Documenta configuración nueva en README o en docs dedicadas.
- La UI no muestra datos demo como live.
- Cualquier función relacionada con órdenes reales está desactivada por defecto.
- Tiene criterios de aceptación verificables con comandos o flujo de UI.

## No objetivos globales

- No ejecutar dinero real.
- No prometer rentabilidad.
- No meter IA en la ruta caliente de trading.
- No reemplazar el motor actual por microservicios.
- No extender a muchos activos antes de cerrar explicación, integridad y demo.

## Métrica norte

La métrica de producto no es "número de oportunidades verdes". Es:

> porcentaje de decisiones explicables y reproducibles sobre datos íntegros.

Métricas secundarias:

- Tiempo para que un jurado entienda la decisión: objetivo menor a 90 segundos.
- Porcentaje de oportunidades con breakdown completo: objetivo 100%.
- Books aceptados con integridad específica cuando aplica: objetivo 100% de venues soportados.
- Calibración `P_survive`: error esperado vs observado por bucket.
- Tiempo p99 de evaluación por tick antes y después de optimizaciones.
