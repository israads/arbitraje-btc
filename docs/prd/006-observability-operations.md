# PRD-006: Observabilidad y operación

Estado: Implementado  
Prioridad: P2  
Área: Operación, Métricas, Deploy, Runbooks  
Dependencias: complementa PRD-003
Arquitectura: [docs/architecture/006-observability-operations.md](../architecture/006-observability-operations.md)

## Problema

El sistema tiene métricas internas y health, pero para operarlo como plataforma se necesita visibilidad estándar: feeds, latencia, descartes, breakers, replay, preflight y errores por exchange.

## Objetivo

Hacer que cualquier operador pueda responder en menos de 30 segundos:

- Qué feeds están vivos.
- Qué exchange está fallando.
- Qué fricción está matando oportunidades.
- Si el sistema está en demo, replay, live readonly o testnet.
- Si alguna ruta de ejecución está habilitada.

## No objetivos

- No requerir Kubernetes.
- No migrar a microservicios.
- No añadir observabilidad que degrade el hot path.

## Requisitos funcionales

### RF-001 Endpoint Prometheus

Agregar:

```http
GET /metrics
```

Métricas mínimas:

- `arb_feed_live{exchange}`
- `arb_book_age_ms{exchange}`
- `arb_integrity_rejected_total{exchange,reason}`
- `arb_opportunities_detected_total`
- `arb_opportunities_viable_total`
- `arb_opportunities_discarded_total{reason}`
- `arb_engine_detect_latency_ms`
- `arb_execution_latency_ms`
- `arb_breaker_active{type}`
- `arb_demo_active`
- `arb_preflight_total{venue,result}`

### RF-002 Runbooks

Crear:

- `docs/runbooks/feed-stale.md`
- `docs/runbooks/peg-adverse.md`
- `docs/runbooks/high-latency.md`
- `docs/runbooks/kill-switch.md`
- `docs/runbooks/testnet-preflight.md`

### RF-003 Modo operacional explícito

`GET /health` debe devolver:

- `mode`: `live_readonly`, `demo`, `replay`, `testnet`, `disabled`
- `execution_enabled`: boolean
- `test_orders_enabled`: boolean
- `control_token_required`: boolean

### RF-004 Logs estructurados

Eventos importantes deben incluir:

- `event`
- `exchange`
- `symbol`
- `opportunity_id`
- `mode`
- `reason`
- `latency_ms`

## Cambios técnicos

Archivos:

- `backend/app/metrics/collector.py`
- `backend/app/api/health.py`
- `backend/app/api/v1/router.py`
- `backend/app/logging_config.py`
- `deploy/`

Crear:

- `backend/app/metrics/prometheus.py`
- `docs/runbooks/*`

## Plan de implementación

1. Crear exporter Prometheus sin dependencia pesada o con `prometheus-client`.
2. Mapear métricas existentes a formato Prometheus.
3. Extender health con modo operacional.
4. Agregar runbooks.
5. Agregar logs estructurados en breakers, integrity y preflight.
6. Documentar scrape config opcional.

## Pruebas

- `test_prometheus_endpoint_contains_core_metrics`
- `test_prometheus_endpoint_content_type`
- `test_health_reports_operational_mode`
- `test_breaker_metric_flips_when_halted`
- `test_demo_metric_flips_when_demo_active`

## Criterios de aceptación

- `/metrics` responde texto Prometheus válido.
- `/health` permite saber si hay ejecución habilitada.
- Cada breaker activo aparece en health y métricas.
- Existe runbook para los incidentes principales.

## Riesgos

- Cardinalidad excesiva. Mitigación: labels acotados a exchange, reason, type.
- Coste de métricas. Mitigación: snapshots throttled, nada de serialización pesada por tick.
- Duplicar lógica. Mitigación: exporter lee de `MetricsCollector` y `AppState`.
