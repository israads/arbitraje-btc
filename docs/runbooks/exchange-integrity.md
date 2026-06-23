# Runbook: exchange integrity

## Síntoma

- `/api/v1/integrity` muestra `sequence_gaps` o `checksum_failures`.
- `/health` muestra rechazos de integridad en un venue.
- Aparecen oportunidades falsas o intermitentes en una ruta concreta.

## Revisar

```bash
curl http://localhost:8000/api/v1/integrity
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/metrics
```

Variables útiles:

- `ARB_INTEGRITY_MODE=warn` para observar sin bloquear.
- `ARB_INTEGRITY_MODE=enforce` para bloquear fallos específicos por venue.
- `ARB_INTEGRITY_MODE=generic` para volver al comportamiento estructural común.

## Acción segura

- Mantener `warn` hasta confirmar que ccxt.pro expone metadata estable para el venue.
- Si un venue acumula gaps/checksum failures, deshabilitar ese exchange antes de confiar en
  oportunidades originadas ahí.
- Pasar a `enforce` sólo después de validar fixtures y observar la sesión en vivo.

## No hacer

- No ignorar un venue con `checksum_failures` persistentes durante una demo.
- No activar `enforce` en producción sin observar primero en `warn`.
- No inventar checksums si no se conservan los strings originales del exchange.

## Recuperación

El incidente se considera resuelto cuando:

- `sequence_gaps` deja de crecer.
- `checksum_failures` deja de crecer.
- El venue vuelve a tener libros aceptados recientes.
