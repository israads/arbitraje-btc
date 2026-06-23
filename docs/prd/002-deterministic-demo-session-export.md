# PRD-002: Demo determinista + export de sesión

Estado: Implementado inicial  
Prioridad: P0  
Área: Demo, Backtest, API, Frontend, Docs  
Dependencias: PRD-001 recomendado
Arquitectura: [docs/architecture/002-deterministic-demo-session-export.md](../architecture/002-deterministic-demo-session-export.md)

## Problema

El proyecto tiene fallback demo y replay, pero el jurado necesita una ruta reproducible donde siempre aparezcan los escenarios que demuestran valor: oportunidad aceptada, falso positivo descartado, depeg, stale feed y breaker.

## Objetivo

Crear un modo de demo determinista para evaluación rápida y una forma de exportar la sesión para auditoría.

## No objetivos

- No reemplazar feeds live.
- No ocultar que los datos son demo.
- No crear una simulación irreal con spreads exagerados sin etiqueta.

## Escenarios obligatorios

| Escenario | Qué demuestra | Resultado esperado |
|---|---|---|
| `good_edge` | Spread sobrevive costos | Oportunidad viable/captured en sim |
| `naive_trap` | Spread bruto muere por fees/slippage | Descartada con explicación |
| `peg_adverse` | USDT/USD no es 1.00 garantizado | Descartada o penalizada por peg |
| `stale_feed` | Datos vencidos no se operan | Breaker o descarte |
| `latency_decay` | Edge muere tras latencia | Baja `P_survive` o unwind simulado |

## Requisitos funcionales

### RF-001 Modo demo de jurado

Agregar modo:

```http
POST /api/v1/demo?mode=jury
```

Comportamiento:

- Inyecta una secuencia fija de books.
- Marca todo evento como `DEMO/JURY`.
- No abre órdenes reales.
- No contamina replay live salvo que se configure explícitamente.

### RF-002 Estado de escenario

`GET /api/v1/demo` debe incluir:

```json
{
  "active": true,
  "mode": "jury",
  "source": "deterministic",
  "scenario": "naive_trap",
  "scenario_index": 2,
  "n_scenarios": 5
}
```

### RF-003 Export de sesión

Agregar:

```http
GET /api/v1/session/export
```

Debe devolver JSON con:

- metadata
- settings relevantes saneados
- quotes recientes
- oportunidades recientes
- explanations si existen
- métricas
- breakers
- demo status
- validación

### RF-004 Import opcional de sesión

No es necesario para P0. Se puede dejar como P2:

```http
POST /api/v1/session/import
```

## UX

En `ControlPanel`:

- Botón `JURY DEMO`.
- Badge visible `DEMO DATA`.
- Indicador de escenario actual.
- Botón `Export session`.

## Cambios técnicos

Archivos probables:

- `backend/app/demo/fallback.py`
- `backend/app/api/v1/router.py`
- `backend/app/backtest/recorder.py`
- `frontend/components/ControlPanel.tsx`
- `frontend/hooks/useStream.ts`
- `docs/guion-demo-jurado.md`

Crear:

- `backend/app/demo/scenarios.py`
- `backend/app/models/session.py`

## Plan de implementación

1. Definir fixtures de books para los 5 escenarios.
2. Crear `JuryScenarioPlayer` puro y testeable.
3. Integrarlo con `DemoFallback` o como ruta paralela controlada por modo.
4. Extender `/demo` para aceptar `jury`.
5. Crear `/session/export`.
6. Agregar botón en UI.
7. Actualizar guion de demo.

## Pruebas

- `test_jury_demo_cycles_scenarios`
- `test_jury_demo_marks_source_as_demo`
- `test_jury_demo_never_enables_live_execution`
- `test_session_export_contains_required_sections`
- `test_session_export_redacts_sensitive_settings`

## Criterios de aceptación

- En menos de 90 segundos se pueden ver los 5 escenarios.
- El dashboard siempre indica que son datos demo.
- Export session produce JSON válido y reproducible.
- El modo `jury` no requiere red externa.
- El guion de demo queda actualizado.

## Riesgos

- Que el jurado confunda demo con live. Mitigación: badges persistentes y campo `source`.
- Que los escenarios sean demasiado perfectos. Mitigación: incluir uno donde el edge muere.
- Que el export incluya secretos. Mitigación: lista blanca de settings exportables.
