# Runbook: peg adverso

## Síntoma

- Oportunidades USD/USDT se descartan por `peg_adverse`.
- El spread bruto parece atractivo, pero el motor lo rechaza.

## Revisar

```bash
curl http://localhost:8000/api/v1/quotes
curl http://localhost:8000/api/v1/opportunities
curl http://localhost:8000/api/v1/metrics
```

Datos a confirmar:

- `price_norm_factor`
- tolerancia de peg configurada
- quote currency por venue
- razón de descarte

## Acción segura

- Mantener rechazo si el peg está fuera de tolerancia.
- Explicar que USDT/USD no se asume como 1.0000.
- Para demo, usar escenario `peg_adverse`.

## No hacer

- No desactivar el gate de peg para crear oportunidades.
- No mezclar USD, USDT y MXN sin factor explícito.

## Recuperación

El incidente se considera resuelto cuando:

- El peg vuelve dentro de tolerancia.
- Las oportunidades cross-stablecoin muestran penalización normal o dejan de descartarse por peg.

