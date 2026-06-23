# PRD-008: Extensiones de mercado

Estado: Implementado inicial  
Prioridad: P3  
Área: Estrategias, Mercado, Producto  
Dependencias: PRD-001, PRD-004, PRD-007 recomendados
Arquitectura: [docs/architecture/008-market-extensions.md](../architecture/008-market-extensions.md)

## Problema

El proyecto se enfoca en arbitraje spot cross-exchange BTC. Es una base sólida, pero la investigación externa muestra tres extensiones naturales: triangular intra-venue, funding/basis spot-perp y corredor México/MXN.

## Objetivo

Diseñar extensiones modulares que amplíen el campo de oportunidades sin contaminar el motor principal.

## No objetivos

- No mezclar estrategias sin etiquetarlas.
- No operar derivados reales.
- No ampliar a muchos símbolos sin integridad y observabilidad.
- No sacrificar la narrativa principal de edge ejecutable.

## Extensión A: triangular intra-venue

### Problema

Algunos competidores muestran triangular arbitrage. Es vistoso y algorítmicamente claro, pero puede generar falsos positivos si no cobra fees, profundidad y precisión.

### Requisitos

- Construir grafo de pares por exchange.
- Usar pesos `-log(rate_after_fee)` por dirección.
- Detectar ciclos negativos.
- Validar ciclo con profundidad real.
- Cobrar fee por cada pierna.
- Respetar min notional/precision.

### API propuesta

```http
GET /api/v1/strategies/triangular/opportunities
```

### Criterio de aceptación

- Un ciclo top-of-book no se reporta si muere por fee o profundidad.
- Cada ciclo muestra tres piernas y breakdown de costos.

## Extensión B: funding/basis arbitrage

### Problema

En Asia y en bots recientes aparece arbitraje por funding rate entre spot/perp o perp/perp. Es relevante porque los spreads spot puros suelen comprimirse.

### Requisitos

- Ingerir funding rates.
- Ingerir mark/index price.
- Calcular basis.
- Modelar costo de hedge.
- Separar carry esperado de PnL mark-to-market.
- Mostrar liquidación/riesgo de margin como no objetivo en demo.

### API propuesta

```http
GET /api/v1/strategies/funding/opportunities
```

### Criterio de aceptación

- Una oportunidad de funding muestra APR bruto, costos, riesgo y horizonte.
- Nunca se mezcla con PnL spot cross-exchange.

## Extensión C: corredor México/MXN

### Problema

El reto es mexicano. Una mejora diferenciadora es mostrar comprensión regional: MXN, Bitso, USD/MXN y stablecoin basis.

### Requisitos

- Ingerir BTC/MXN si el venue lo permite.
- Ingerir USD/MXN.
- Modelar conversión MXN -> USD.
- Separar spread regional de depeg stablecoin.
- Mostrar costo de transferencia fiat como fricción configurable.

### API propuesta

```http
GET /api/v1/strategies/regional/mxn
```

### Criterio de aceptación

- El sistema puede comparar BTC/MXN contra BTC/USD normalizado.
- La UI muestra que no es "precio gratis", sino spread regional con FX y costos.

## Arquitectura común

Crear interfaz:

```python
class StrategyModule(Protocol):
    id: str
    def on_book(self, book: NormalizedBook) -> list[Opportunity]: ...
    def explain(self, opportunity_id: str) -> StrategyExplanation: ...
```

Estrategias:

- `spatial_cross_exchange` actual.
- `stat_z` actual.
- `triangular` demo/replay, opt-in.
- `funding_basis` read-only, opt-in.
- `regional_mxn` experimental, opt-in.

## Plan de implementación

1. Formalizar interfaz de estrategia sin cambiar la actual.
2. Confirmar que `strategy` quede visible en métricas por módulo.
3. Implementar triangular solo en modo demo/replay.
4. Añadir funding como research/read-only.
5. Añadir MXN como módulo experimental.

## Pruebas

- `test_triangular_cycle_detected_when_fee_adjusted_positive`
- `test_triangular_cycle_rejected_when_fee_negative`
- `test_funding_opportunity_separates_apr_and_mark_risk`
- `test_mxn_normalization_uses_fx_rate`
- `test_strategy_metrics_are_separated`

## Criterios de aceptación

- Las extensiones se pueden desactivar por config.
- Las métricas separan estrategia.
- La UI no mezcla oportunidades de distinto riesgo.
- Cross-exchange BTC sigue siendo el flujo principal.

Implementado:

- Interfaz `StrategyModule` en `backend/app/strategies/base.py`.
- Adapters para `spatial` y `stat_z` sin reemplazar el pipeline vivo.
- `Opportunity.legs` y `Opportunity.strategy_payload` para payloads multi-pata.
- `triangular` cobra fee en tres legs, usa pesos `-log(rate_after_fee)` y valida profundidad.
- `funding_basis` calcula basis/APR en modelos read-only, separado de PnL spot.
- `regional_mxn` compara BTC/MXN contra BTC/USD con `USD/MXN` obligatorio y fricción fiat.
- Endpoints:
  - `GET /api/v1/strategies`
  - `GET /api/v1/strategies/triangular/opportunities`
  - `GET /api/v1/strategies/funding/opportunities`
  - `GET /api/v1/strategies/regional/mxn`
- Flags desactivados por defecto:
  - `ARB_STRATEGY_TRIANGULAR_ENABLED`
  - `ARB_STRATEGY_FUNDING_ENABLED`
  - `ARB_STRATEGY_REGIONAL_MXN_ENABLED`
- Tests en `backend/tests/test_strategy_modules.py`.

## Riesgos

- Dispersión del proyecto. Mitigación: dejar P3 hasta cerrar P0/P1.
- APIs de derivados más complejas. Mitigación: funding read-only primero.
- Confusión de riesgos. Mitigación: etiquetas de estrategia y breakdown separado.
