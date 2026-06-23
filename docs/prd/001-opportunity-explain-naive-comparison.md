# PRD-001: Opportunity Explain + Naive Comparison

Estado: Implementado  
Prioridad: P0  
Área: Backend, API, Frontend  
Dependencias: ninguna
Arquitectura: [docs/architecture/001-opportunity-explain-naive-comparison.md](../architecture/001-opportunity-explain-naive-comparison.md)

## Problema

El sistema ya calcula edge ejecutable, pero la explicación vive distribuida entre objetos, métricas, logs y paneles. Para jurado y usuarios técnicos, la diferencia entre "spread watcher" y "motor de capturabilidad" debe verse en una sola interacción.

## Objetivo

Cada oportunidad debe poder responder:

- Qué habría hecho un bot ingenuo.
- Qué calculó el motor real.
- Qué fricción mató o validó la oportunidad.
- Qué tan sensible es a tamaño, fees, latencia y peg.

## No objetivos

- No cambiar la fórmula económica base.
- No ejecutar órdenes reales.
- No añadir ML.
- No rediseñar todo el dashboard.

## Usuario

- Jurado que evalúa rápido.
- Desarrollador que audita una decisión.
- Operador que necesita saber por qué no se ejecutó.

## Estado actual

Existe:

- `Opportunity` con `vwap_buy`, `vwap_sell`, `fees`, `slippage`, `net_pnl`, `score`, `discard_reason`.
- `ExecutionCostModel` con `NetBreakdown`.
- UI con `OpportunitiesTable`, `EdgeWaterfall`, `FunnelPanel`.

Brecha:

- Breakdown persistido por oportunidad.
- Endpoint de explicación por ID.
- UI de comparación naive vs engine.

## Requisitos funcionales

### RF-001 Breakdown por oportunidad

Cada oportunidad evaluada debe conservar:

- `gross_usd`
- `gross_per_btc`
- `fees_buy_usd`
- `fees_sell_usd`
- `fees_total_usd`
- `slippage_buy_usd`
- `slippage_sell_usd`
- `slippage_total_usd`
- `rebalance_usd`
- `peg_factor_buy`
- `peg_factor_sell`
- `peg_adverse_bps`
- `latency_ms`
- `net_usd`
- `net_per_btc`
- `dominant_cost`
- `decision`
- `decision_reason`

### RF-002 Comparación naive

Para la misma oportunidad, calcular:

- `naive_buy_price`: best ask del venue de compra.
- `naive_sell_price`: best bid del venue de venta.
- `naive_spread_usd_per_btc`.
- `naive_gross_usd`.
- `engine_net_usd`.
- `delta_usd`.
- `would_naive_trade`: boolean.
- `engine_trades`: boolean.

### RF-003 Endpoint de explicación

Agregar:

```http
GET /api/v1/opportunities/{id}/explain
```

Respuesta mínima:

```json
{
  "id": "opp-id",
  "route": {
    "symbol": "BTC/USD",
    "buy_venue": "binance",
    "sell_venue": "kraken"
  },
  "decision": {
    "status": "discarded",
    "reason": "not_profitable_fees",
    "dominant_cost": "fees"
  },
  "naive": {
    "spread_usd_per_btc": 97.0,
    "gross_usd": 9.7,
    "would_trade": true
  },
  "engine": {
    "net_usd": -1.2,
    "net_per_btc": -12.0,
    "trades": false
  },
  "breakdown": [
    {"key": "gross", "label": "Gross", "usd": 9.7},
    {"key": "fees", "label": "Fees", "usd": -8.1},
    {"key": "slippage", "label": "Slippage", "usd": -2.4},
    {"key": "rebalance", "label": "Rebalance", "usd": -0.4},
    {"key": "net", "label": "Net", "usd": -1.2}
  ]
}
```

### RF-004 UI

En `OpportunitiesTable`:

- Click en fila abre un drawer o panel lateral.
- Mostrar `Naive` vs `Engine`.
- Mostrar waterfall específico de la oportunidad.
- Mostrar razón de descarte en lenguaje claro.

## Cambios técnicos

### Backend

Archivos probables:

- `backend/app/models/opportunity.py`
- `backend/app/engine/cost_model.py`
- `backend/app/engine/evaluator.py`
- `backend/app/state.py`
- `backend/app/api/v1/router.py`

Crear modelos:

- `OpportunityBreakdown`
- `NaiveComparison`
- `OpportunityExplanation`

Opciones:

1. Guardar campos directamente en `Opportunity`.
2. Crear campo `explain: OpportunityExplanation | None`.

Recomendación: empezar con campo opcional `explain` para evitar romper compatibilidad.

### Frontend

Archivos probables:

- `frontend/hooks/useStream.ts`
- `frontend/components/OpportunitiesTable.tsx`
- nuevo `frontend/components/OpportunityExplainDrawer.tsx`
- opcional: reutilizar `EdgeWaterfall.tsx` con datos dinámicos.

## Plan de implementación

1. Extender modelos Pydantic.
2. Crear builder puro `build_opportunity_explanation(opp, buy_book, sell_book, settings, peg)`.
3. Llamarlo desde `NetEvaluator.evaluate`.
4. Guardar explicación en el buffer de oportunidades.
5. Agregar endpoint por ID.
6. Agregar tests de contrato para explicación.
7. Agregar drawer UI.
8. Validar que oportunidades viejas sin explanation no rompan UI.

## Pruebas

Backend:

- `test_explain_contains_naive_and_engine`
- `test_explain_discard_reason_matches_opportunity`
- `test_explain_does_not_change_net_formula`
- `test_explain_endpoint_404_for_unknown_id`
- `test_explain_contract_json`

Frontend:

- Render con opportunity viable.
- Render con opportunity discarded.
- Render sin explanation.

## Criterios de aceptación

- Una oportunidad visible en la tabla puede abrirse y explicar su decisión.
- El panel muestra al menos gross, fees, slippage, rebalance y net.
- El panel muestra si el bot ingenuo habría operado.
- El endpoint responde en menos de 50 ms p95 para oportunidades en memoria.
- No se rompe `GET /api/v1/opportunities`.

## Riesgos

- Duplicar fórmula económica. Mitigación: usar `ExecutionCostModel` y no recalcular manualmente.
- Inflar payload SSE. Mitigación: explanation completa solo por endpoint; SSE conserva resumen.
- UI demasiado densa. Mitigación: drawer progresivo: resumen arriba, detalle abajo.

## Implementación

Implementado:

- Modelos `OpportunityExplanation`, `NaiveComparison`, `EngineDecision` y breakdown por coste.
- Builder de explicación desde el evaluador sin cambiar la fórmula económica base.
- `GET /api/v1/opportunities/{id}/explain`.
- Drawer `OpportunityExplainDrawer` y acción desde `OpportunitiesTable`.
- Tests de contrato en `backend/tests/test_opportunity_explain.py`.
