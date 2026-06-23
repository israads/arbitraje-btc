# Arquitectura PRD-006: Observabilidad y operación

## Objetivo arquitectónico

Exponer el estado operacional del sistema con métricas estándar, health enriquecido y runbooks, sin afectar la ruta caliente.

## Estado actual relevante

- `MetricsCollector` produce snapshot para API/SSE.
- `/health` existe.
- Breakers, watchdog, demo status y metrics existen en memoria.
- `/metrics` Prometheus y runbooks operativos están implementados.

## Componentes nuevos

```text
backend/app/metrics/prometheus.py
docs/runbooks/feed-stale.md
docs/runbooks/peg-adverse.md
docs/runbooks/high-latency.md
docs/runbooks/kill-switch.md
docs/runbooks/testnet-preflight.md
```

## Cambios existentes

```text
backend/app/api/health.py          -> health operacional
backend/app/api/v1/router.py       -> opcional /ops/status
backend/app/main.py                -> registrar eventos clave
backend/app/logging_config.py      -> formato estructurado
backend/app/metrics/collector.py   -> snapshot listo para exporter
```

## Flujo

```mermaid
flowchart LR
    State[AppState] --> Snapshot[Metrics Snapshot]
    Breakers --> Snapshot
    Integrity --> Snapshot
    Demo --> Snapshot
    Snapshot --> API[/api/v1/metrics]
    Snapshot --> Prom[/metrics Prometheus]
    Health[/health] --> Operator[Operador]
    Runbooks[docs/runbooks] --> Operator
```

## Endpoint Prometheus

Implementación ligera:

```python
def render_prometheus(ctx: AppState) -> str:
    lines = []
    ...
    return "\n".join(lines) + "\n"
```

Evitar dependencia inicialmente. Si se agrega `prometheus-client`, mantenerlo fuera del hot path.

## Métricas mínimas

```text
arb_up
arb_demo_active
arb_feed_live{exchange}
arb_book_age_ms{exchange}
arb_preflight_total{venue,result}
arb_opportunities_detected_total
arb_opportunities_discarded_total{reason}
arb_breaker_active{type}
arb_integrity_rejected_total{exchange,reason}
arb_detect_latency_p50_ms
arb_detect_latency_p99_ms
arb_execution_enabled
arb_test_orders_enabled
```

## Health operacional

`GET /health` debe incluir:

```json
{
  "status": "ok",
  "mode": "live_readonly",
  "execution_enabled": false,
  "test_orders_enabled": false,
  "demo_active": false,
  "breakers": {"halted": false, "active": []},
  "feeds": {"binance": "live"}
}
```

## Logs estructurados

Formato recomendado:

```text
event=breaker_active type=stale_venue exchange=kraken reason=book_age
event=integrity_reject exchange=binance reason=sequence_gap
event=preflight_result venue=binance result=accepted mode=testnet
```

No cambiar todo el logging al inicio. Empezar por breakers, integrity y preflight.

## Runbooks

Cada runbook debe contener:

- Síntoma.
- Métricas a revisar.
- Endpoint a consultar.
- Acción segura.
- Acción que no debe hacerse.
- Criterio de recuperación.

## Rollout

1. Health enriquecido.
2. `/metrics` texto Prometheus.
3. Runbooks básicos.
4. Logs estructurados en eventos críticos.
5. Deploy docs con scrape opcional.

## Pruebas

- `/metrics` tiene content-type de texto.
- Métricas core aparecen aunque no haya feeds.
- Health no expone secretos.
- Breaker activo se refleja en health y metrics.

## Riesgos y mitigación

- Cardinalidad alta: labels acotados.
- Coste de render: endpoint calcula bajo demanda.
- Divergencia entre health y metrics: ambos leen `AppState`.
