# Arquitectura PRD-008: Extensiones de mercado

## Objetivo arquitectónico

Preparar una interfaz de estrategias que permita agregar triangular, funding/basis y MXN sin mezclar riesgos ni romper el flujo principal de arbitraje spot cross-exchange.

## Estado actual relevante

- `SpatialDetector` y `StatZDetector` ya conviven.
- `Opportunity.strategy` existe.
- Métricas separan por estrategia.
- El pipeline asume oportunidades con buy venue y sell venue.
- PRD-008 está implementado como capa opt-in/read-only alrededor del flujo principal.

## Componentes nuevos

```text
backend/app/strategies/__init__.py
backend/app/strategies/base.py
backend/app/strategies/triangular.py
backend/app/strategies/funding.py
backend/app/strategies/regional_mxn.py
backend/app/strategies/spatial.py
backend/app/strategies/stat_z.py
backend/app/models/strategy.py
```

## Interfaz de estrategia

```python
class StrategyModule(Protocol):
    id: str
    enabled: bool
    def on_book(self, book: NormalizedBook, books: dict[str, NormalizedBook]) -> list[Opportunity]: ...
    def explain(self, opportunity: Opportunity) -> StrategyExplanation: ...
```

Para no romper lo actual, el primer paso no reemplaza `SpatialDetector`. Solo crea la interfaz y adapters alrededor de detectores existentes.

## Modelo de oportunidad extendible

`Opportunity` puede seguir con campos actuales, pero agregar:

```python
legs: list[OpportunityLeg] | None = None
strategy_payload: dict[str, Any] = Field(default_factory=dict)
```

`legs` permite triangular y funding sin forzar todo a buy/sell de dos venues.

## Triangular

Arquitectura:

```mermaid
flowchart LR
    Books[Venue books] --> Graph[Currency graph]
    Graph --> Cycles[Negative cycle scan]
    Cycles --> Depth[Depth validation]
    Depth --> Opp[Opportunity legs=3]
    Opp --> Explain[Strategy explanation]
```

Módulo:

```text
backend/app/strategies/triangular.py
```

Reglas:

- Pesos `-log(rate_after_fee)`.
- Validación por profundidad después de detectar ciclo.
- Fee por cada leg.
- Min notional/precision queda documentado como riesgo de venue; el cálculo valida tamaño y profundidad.
- Desactivado por defecto.

## Funding/basis

Requiere nuevos modelos:

```python
class FundingRate(BaseModel):
    venue: str
    symbol: str
    rate: float
    next_funding_ts: float

class BasisOpportunity(BaseModel):
    spot_venue: str
    perp_venue: str
    basis_bps: float
    funding_apr: float
```

Vive read-only al inicio. No usa el simulador spot existente para derivados.

## Regional MXN

Nuevos inputs:

- BTC/MXN book.
- USD/MXN FX.
- USDT/MXN si aplica.
- costo fiat configurable.

Regla central: mostrar spread regional neto, no mezclarlo con depeg.

Implementación actual:

- `RegionalMXNStrategy.compare(...)` exige `USD/MXN`.
- `strategy_mxn_fiat_fee_bps` resta fricción fiat configurable.
- La ruta API devuelve vacío con nota si falta FX o books.

## API

```http
GET /api/v1/strategies
GET /api/v1/strategies/triangular/opportunities
GET /api/v1/strategies/funding/opportunities
GET /api/v1/strategies/regional/mxn
```

## UI

No agregar nuevas pantallas grandes al inicio.

- Tabs por estrategia.
- Badges de riesgo.
- Reutilizar `OpportunityExplainDrawer` con `strategy_payload`.

## Rollout

1. Interfaz `StrategyModule`. Implementado.
2. Adapter para spatial/stat actuales. Implementado.
3. Métricas por estrategia. Implementado vía `MetricsCollector.by_strategy`.
4. Triangular demo/replay. Implementado, opt-in.
5. Funding read-only. Implementado, opt-in y sin ingesta live de funding.
6. MXN experimental. Implementado, opt-in y exige FX explícito.

## Pruebas

- Estrategia deshabilitada no emite oportunidades.
- Métricas separan estrategia.
- Triangular cobra fees por 3 legs.
- Funding no usa endpoints de ejecución spot.
- MXN exige FX rate.

## Riesgos y mitigación

- Dispersión del producto: P3, después de P0/P1.
- Riesgo financiero distinto: badges y modelos separados.
- Forzar `Opportunity` demasiado: usar `legs` y `strategy_payload`.

## Validación

```bash
cd backend
uv run pytest tests/test_strategy_modules.py tests/test_metrics.py tests/test_health.py
uv run mypy app
```
