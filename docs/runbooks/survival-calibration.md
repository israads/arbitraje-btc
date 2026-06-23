# Runbook: survival calibration

## Síntoma

- `/api/v1/calibration/survival` muestra `n_observed=0`.
- La confianza aparece como `low`.
- Muchos observations tienen `reason=missing_future_book`.

## Revisar

```bash
curl 'http://localhost:8000/api/v1/calibration/survival?latency_ms=100'
curl http://localhost:8000/api/v1/session/export
```

Variables útiles:

- `ARB_CALIBRATION_MODE=observe_only`
- `ARB_SHADOW_SAMPLE_MAXLEN=20000`
- `ARB_RECORD_ENABLED=true`

## Acción segura

- Confirmar que el recorder tiene ticks posteriores a las oportunidades.
- Aumentar duración de sesión si faltan books futuros para 500 ms o 1000 ms.
- Mantener `observe_only` hasta tener al menos confianza `medium`.

## No hacer

- No usar calibración para descartar oportunidades con `confidence=low`.
- No calcular supervivencia dentro del objeto oportunidad original.
- No mezclar ticks anteriores al target de latencia.

## Recuperación

El estado es saludable cuando:

- `n_observed` crece.
- `n_missing` se mantiene bajo para la latencia elegida.
- Los buckets muestran `observed_rate` estable con confianza media o alta.
