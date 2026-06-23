# Runbook: feed stale

## Síntoma

- Un exchange aparece como `stale` o deja de actualizar quotes.
- Oportunidades de ese venue desaparecen o se descartan.
- Puede activarse breaker de staleness.

## Revisar

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/quotes
curl http://localhost:8000/api/v1/metrics
```

Cuando PRD-006 esté implementado:

```bash
curl http://localhost:8000/metrics
```

Métricas esperadas:

- `arb_feed_live{exchange}`
- `arb_book_age_ms{exchange}`
- `arb_breaker_active{type="stale"}`

## Acción segura

- Confirmar si otros venues siguen live.
- Mantener el venue stale fuera de decisiones.
- Activar demo/replay si es una presentación.
- No forzar oportunidades sobre datos viejos.

## No hacer

- No bajar umbral de staleness para que aparezcan oportunidades.
- No reiniciar en loop sin revisar si el exchange está rate-limited.
- No presentar datos stale como live.

## Recuperación

El incidente se considera resuelto cuando:

- El book age vuelve bajo el umbral.
- El venue vuelve a `live`.
- El breaker stale se limpia o deja de estar activo.

