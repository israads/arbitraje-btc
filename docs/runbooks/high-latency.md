# Runbook: latencia alta

## Síntoma

- `detect_latency` o `exec_latency` sube.
- `P_survive` baja.
- Aumentan descartes o oportunidades dejan de ser capturables.

## Revisar

```bash
curl http://localhost:8000/api/v1/metrics
curl http://localhost:8000/api/v1/control/status
```

Cuando PRD-006 esté implementado:

```bash
curl http://localhost:8000/metrics
```

Métricas esperadas:

- `arb_detect_latency_p50_ms`
- `arb_detect_latency_p99_ms`
- `arb_execution_latency_ms`

## Acción segura

- Mantener el motor en readonly si la latencia invalida oportunidades.
- Revisar si hay CPU alta, red lenta o exchange degradado.
- Usar demo determinista si es presentación.

## No hacer

- No reducir artificialmente `exec_latency_ms` para mejorar frontier.
- No operar rutas con `P_survive` bajo sin justificación.

## Recuperación

El incidente se considera resuelto cuando:

- p99 vuelve bajo el umbral operativo.
- `P_survive` y oportunidades vuelven a rangos esperados.

