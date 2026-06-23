# Plan de ejecución al 100%

Fecha: 18 de junio de 2026.

Este directorio convierte PRDs y arquitecturas en trabajo ejecutable. La separación de fuentes queda así:

| Documento | Decide | No decide |
|---|---|---|
| [`docs/prd`](../prd/README.md) | Qué se debe construir y por qué | Diseño interno detallado |
| [`docs/architecture`](../architecture/README.md) | Cómo se integra en el sistema | Priorización diaria |
| [`docs/execution`](README.md) | En qué orden se implementa, con qué gates y cómo se valida | Nuevos requisitos de producto |

## Ruta crítica

```text
1. Explicar oportunidades
2. Demo determinista
3. Preflight testnet
4. Integridad por exchange
5. Calibración de supervivencia
6. Observabilidad
7. Rendimiento
8. Extensiones de mercado
```

La regla de ejecución es simple: no avanzar a extensiones de mercado hasta que la oportunidad principal sea explicable, reproducible y basada en datos íntegros.

## Documentos de ejecución

- [Work breakdown](work-breakdown.md): tareas concretas por PRD.
- [Paquetes de implementación](implementation-packets.md): cómo arrancar cada PRD en código.
- [Quality gates](quality-gates.md): criterios obligatorios antes de dar algo por terminado.
- [Matriz de trazabilidad](traceability-matrix.md): PRD -> arquitectura -> tarea -> validación.
- [Revisión documental](documentation-review.md): tres pasadas de revisión y ajustes aplicados.
- [Benchmark DepthCurve](depth-curve-benchmark.md): evidencia de PRD-007.
- [Runbooks operativos](../runbooks/README.md): diagnóstico para feed stale, peg, latencia, kill switch y preflight.

## Hitos

| Hito | Incluye | Resultado |
|---|---|---|
| H1: Demo superior | PRD-001, PRD-002 | Jurado entiende naive vs engine en 90 segundos |
| H2: Readiness controlado | PRD-003, PRD-004 | Preflight/test order y calidad de books visible |
| H3: Confianza cuantitativa | PRD-005, PRD-006 | `P_survive` observado y sistema operable |
| H4: Escala técnica | PRD-007 | Menor costo por proyección/evaluación |
| H5: Expansión | PRD-008 | Nuevas estrategias sin contaminar el flujo principal |

## Definición de listo para implementar

Una tarea puede iniciarse si:

- Tiene PRD enlazado.
- Tiene arquitectura enlazada.
- Tiene tests esperados definidos.
- Tiene flags de rollout si toca ejecución, datos live, demo o decisiones de trading.
- Tiene una forma de validar con comando, endpoint o UI.

## Definición de terminado

Una tarea está terminada si:

- El código está implementado con cambios acotados.
- Los tests relevantes pasan.
- Los endpoints mantienen compatibilidad o documentan cambios.
- La UI maneja estados vacíos, loading, error y demo/live.
- La documentación afectada queda actualizada.
- No se expone ningún secreto.
- Nada cercano a órdenes reales queda activo por defecto.

## Orden de implementación recomendado

1. Implementar PRD-001 completo.
2. Implementar PRD-002 completo.
3. Hacer review de UX y demo.
4. Implementar PRD-003 con adapter fake primero.
5. Implementar PRD-004 en modo `warn`.
6. Implementar PRD-005 en `observe_only`.
7. Implementar PRD-006 y conectar métricas nuevas.
8. Implementar PRD-007 solo después de medir.
9. Mantener PRD-008 en modo experimental/read-only, no como flujo principal.
