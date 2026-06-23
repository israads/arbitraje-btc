# PRD-005: Calibración de supervivencia con shadow replay

Estado: Implementado inicial  
Prioridad: P1  
Área: Proyección, Backtest, Métricas, Research  
Dependencias: PRD-001 y PRD-004 recomendados
Arquitectura: [docs/architecture/005-survival-calibration-shadow-replay.md](../architecture/005-survival-calibration-shadow-replay.md)

## Problema

`P_survive` existe y es interpretable, pero hoy depende de una heurística gaussiana con sigma fijo. Eso es defendible como primer modelo, pero el proyecto puede ser mucho más fuerte si mide la supervivencia real de señales usando replay y datos observados.

## Objetivo

Convertir `P_survive` en una probabilidad calibrada con datos del propio sistema.

## No objetivos

- No entrenar un modelo opaco en P1.
- No depender de datasets externos pagados.
- No convertir el sistema en ML-first.
- No cambiar decisiones de ejecución hasta tener calibración suficiente.

## Definición de supervivencia

Una oportunidad sobrevive a `latency_ms` si, al re-evaluar la misma ruta con el book futuro más cercano a `t_detect + latency_ms`, el neto sigue siendo mayor que el umbral:

```text
survived(latency) = net_future_usd > min_net_profit_usd
```

Latencias objetivo:

- 50 ms
- 100 ms
- 200 ms
- 500 ms
- 1000 ms

## Requisitos funcionales

### RF-001 Shadow dataset

Guardar muestras de oportunidades detectadas, aceptadas y descartadas.

Campos mínimos:

- `id`
- `ts_detect`
- `strategy`
- `symbol`
- `buy_venue`
- `sell_venue`
- `q_target`
- `gross_usd`
- `net_usd`
- `net_per_btc`
- `fees_usd`
- `slippage_usd`
- `dominant_cost`
- `latency_ms`
- `book_age_buy_ms`
- `book_age_sell_ms`
- `spread_bps`
- `peg_factor_buy`
- `peg_factor_sell`
- `status`
- `discard_reason`

Campos P2:

- OFI
- MLOFI
- microprice
- volatility bucket
- hour bucket
- venue quality score

Implementación inicial:

- Ring buffer en memoria `AppState.shadow_samples`.
- Captura en el camino de oportunidades después de los gates y simulación.
- El sample no guarda resultados futuros; sólo features point-in-time.
- Export de sesión incluye `calibration.shadow_samples` limitado a las 500 muestras recientes.

### RF-002 Replay survival evaluator

Agregar función:

```python
evaluate_survival(sample, recorder_ticks, latencies_ms) -> SurvivalObservation
```

Implementación inicial:

- `evaluate_survival(sample, recorder_ticks, latencies_ms, settings)` busca el primer book de
  cada venue con `ts_recv_monotonic >= ts_detect + latency`.
- Si falta un book futuro, marca `observed=null` y `reason=missing_future_book`.
- Recalcula el neto con `engine.cost_model.compute_net`, sin tocar la oportunidad original.

Salida:

```json
{
  "opportunity_id": "opp-id",
  "observations": [
    {"latency_ms": 100, "survived": true, "future_net_usd": 1.25},
    {"latency_ms": 500, "survived": false, "future_net_usd": -0.8}
  ]
}
```

### RF-003 Calibración por buckets

Crear endpoint:

```http
GET /api/v1/calibration/survival
```

Debe devolver:

- bucket de `p_survive` estimado.
- supervivencia observada.
- número de muestras.
- error absoluto.
- recomendación de confianza: low/medium/high.

Implementación inicial:

- Endpoint `GET /api/v1/calibration/survival?latency_ms=100`.
- Buckets fijos de probabilidad estimada: 0-20%, 20-40%, 40-60%, 60-80%, 80-100%.
- Confianza por tamaño observado: low `<30`, medium `>=30`, high `>=100`.

### RF-004 Uso gradual

Fases:

1. `observe_only`: solo mide.
2. `report`: muestra en API/UI.
3. `score`: afecta ranking, no decisión final.
4. `gate`: puede descartar, solo con evidencia suficiente.

Default inicial: `observe_only`.

Implementado: `ARB_CALIBRATION_MODE=observe_only` por defecto. Las fases `score` y `gate`
quedan modeladas en settings, pero no alteran ranking ni decisiones en esta etapa.

## Cambios técnicos

Archivos:

- `backend/app/projection/survival.py`
- `backend/app/backtest/replay.py`
- `backend/app/metrics/collector.py`
- `backend/app/store/writer.py`
- `backend/app/api/v1/router.py`

Crear:

- `backend/app/calibration/__init__.py`
- `backend/app/calibration/survival.py`
- `backend/app/models/calibration.py`

Implementado además:

- `backend/app/calibration/samples.py`
- `frontend/components/SurvivalCalibrationPanel.tsx`
- Polling ligero en `frontend/hooks/useStream.ts`

## Plan de implementación

1. Crear modelo de `ShadowOpportunitySample`.
2. Capturar samples en memoria con ring buffer.
3. Exportar samples en session export.
4. Implementar survival evaluator sobre replay.
5. Crear agregador por buckets.
6. Exponer endpoint de calibración.
7. Mostrar panel simple de calibración en UI o métricas.
8. Documentar fases de uso.

## Pruebas

- `test_shadow_sample_contains_required_features`
- `test_survival_observed_true_when_future_net_positive`
- `test_survival_observed_false_when_future_net_negative`
- `test_calibration_bucket_counts`
- `test_calibration_endpoint_contract`
- `test_observe_only_does_not_change_decisions`

Pruebas implementadas:

- Sample con campos/features mínimos.
- Supervivencia true/false con books futuros.
- Missing future book.
- Anti look-ahead: ignora ticks anteriores al target.
- Buckets y contrato endpoint.
- Observe-only no muta oportunidades.

## Criterios de aceptación

- El sistema puede medir supervivencia observada para una sesión replay.
- `P_survive` estimado puede compararse contra supervivencia real.
- El modo inicial no cambia decisiones.
- La calibración reporta tamaño de muestra y confianza.

## Riesgos

- Pocas muestras. Mitigación: mostrar confianza baja y no activar gating.
- Replay insuficiente para latencias largas. Mitigación: marcar observación como `missing_future_book`.
- Look-ahead accidental. Mitigación: pruebas point-in-time.
