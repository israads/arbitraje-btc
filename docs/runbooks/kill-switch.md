# Runbook: kill switch

## Síntoma

- Dashboard muestra `HALTED`.
- Oportunidades viables se reclasifican como descartadas por breaker.

## Revisar

```bash
curl http://localhost:8000/api/v1/control/status
curl http://localhost:8000/api/v1/metrics
```

## Acción segura

- Identificar breaker activo.
- Revisar feed, peg, drawdown o acción manual.
- Mantener pausa hasta entender la causa.

Para reanudar, solo con token de control:

```bash
curl -X POST http://localhost:8000/api/v1/control/resume \
  -H "X-Control-Token: <token>"
```

## No hacer

- No reanudar sin revisar causa.
- No ocultar estado halted durante demo.

## Recuperación

El incidente se considera resuelto cuando:

- `halted=false`.
- No hay breakers activos no explicados.
- Feeds y métricas vuelven a estado sano.

