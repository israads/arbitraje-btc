# Revisión documental

Este documento registra las tres pasadas de revisión pedidas para dejar PRDs, arquitecturas y plan de ejecución consistentes.

## Pasada 1: estructura y navegación

Objetivo: que cualquier persona encuentre rápido qué construir, cómo construirlo y en qué orden.

Cambios aplicados:

- Se creó `docs/architecture` con arquitectura técnica para los 8 PRDs.
- Se creó `docs/execution` como capa de implementación.
- Se enlazó arquitectura desde `README.md` y `docs/prd/README.md`.
- Cada PRD enlaza su arquitectura específica.
- Se creó una ruta crítica única: explain -> demo -> preflight -> integridad -> calibración.

Resultado:

- PRD define el qué.
- Arquitectura define el cómo.
- Execution define el orden y gates.

## Pasada 2: redundancia y consistencia

Objetivo: reducir duplicación dañina y dejar una fuente de verdad por tipo de decisión.

Ajustes realizados:

- La fórmula económica queda referida a `ExecutionCostModel`; ningún documento debe pedir recalcular neto manualmente.
- Los PRDs mantienen requisitos; las arquitecturas contienen módulos y flujos.
- El plan de ejecución evita repetir requisitos y se enfoca en tareas.
- La demo determinista se define como P0, mientras triangular/funding/MXN quedan como P3 para evitar dispersión.
- `P_survive` calibrado queda en observe-only al inicio para no mezclar medición con decisión.

Regla posterior:

- Si cambia el alcance funcional, editar PRD.
- Si cambia el diseño interno, editar architecture.
- Si cambia el orden o tareas, editar execution.

## Pasada 3: robustez y cierre al 100%

Objetivo: agregar los controles necesarios para ejecutar sin ambigüedad.

Cambios aplicados:

- Se agregó work breakdown con IDs por tarea.
- Se agregaron paquetes de implementación por PRD.
- Se agregaron quality gates transversales.
- Se agregó matriz de trazabilidad PRD -> arquitectura -> tarea -> validación.
- Se agregaron runbooks operativos base.
- Se explicitó que toda ejecución real está disabled por defecto.
- Se separó `warn` y `enforce` para integridad por exchange.
- Se incluyó compatibilidad, seguridad operacional, correctitud financiera, integridad, observabilidad, pruebas y documentación como gates.

Resultado:

- El siguiente paso puede ser implementación directa de PRD-001.
- Cada PRD tiene tareas, arquitectura, pruebas y criterios de salida.

## Decisiones de implementación a confirmar

Estos puntos no se implementan en documentación porque deben resolverse durante código:

- Confirmar qué metadata exacta expone `ccxt.pro` por venue para checksums/gaps.
- Confirmar si frontend ya tiene o necesita script `typecheck`.
- Elegir si `OpportunityExplanation` vive embebido en `Opportunity` o solo referenciado por ID tras medir payload.
- Decidir si `prometheus-client` se agrega como dependencia o se renderiza texto manualmente.
