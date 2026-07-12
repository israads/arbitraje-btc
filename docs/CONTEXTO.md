# Contexto del proyecto — mapa para iterar sin re-explorar

> Documento vivo. Sirve para que cada ciclo de mejora (código/diseño) tenga el estado del proyecto
> a mano y no haya que re-escanear todo. Si cambias estructura, actualízalo.

**Tesis:** un motor de arbitraje BTC cross-exchange que no pregunta *dónde está más barato* sino
**cuánto queda tras ejecutar** con profundidad de libro, fees, latencia, inventario y peg. Todo es
simulación con datos públicos; ninguna operación real.

**Stack:** backend FastAPI (1 worker, estado en memoria) + pipeline asyncio · frontend Next.js +
Mantine (dark, verde #16D67F, Outfit/Inter/JetBrains Mono) · persistencia SQLite async · MCP server
read-only. **507 tests** (41 archivos), ruff + mypy --strict limpios; frontend tsc + lint + build
limpios (cero warnings).

## Backend (`backend/app/`)

| Paquete | Qué hace |
|---|---|
| `engine/` | Pipeline: `detector` (cruces), `evaluator` (viabilidad), `cost_model.compute_net` (neto = bruto − fees − rebalanceo, fuente única), `depth_curve` (VWAP por profundidad), `prioritizer` (score), `statz` (z-score), `explain` (explicación auditable) |
| `projection/` | Suite v2: `frontier` (heatmap tamaño×fee), `capacity` (curva cóncava Q*), `forward` (Monte Carlo bootstrap estacionario + PSR/DSR/MinTRL), `survival` (P_survive) |
| `analysis/` | `naive_vs_edge` — bruto ingenuo vs neto real, atribución de fugas |
| `store/` | `db`, `writer` (batch async), `retention` (poda + medición de tamaño) |
| `demo/` | `fallback` (auto/on/off/jury), `scenarios` (deterministas de jurado) |
| `risk/` | `breakers` (circuit breakers + kill switch), `watchdog` (staleness) |
| `metrics/` | `collector` (embudo + latencias + microestructura), `prometheus` |
| `sim/` | `simulator`, `inventory` (pre-posicionado), `rebalancer` |
| `ingest/` | `exchange_ingestor` (WS ccxt por venue) |
| `execution/` | testnet/dry-run protegida: `binance`, `preflight`, `registry` |
| `api/` | `api/v1/router.py` (REST+SSE), `api/security.py` (API key + rate limit opcionales) |
| `models/` | Pydantic por dominio |
| otros | `bus` (cola drop-oldest), `backtest` (recorder+replay), `integrity`, `normalize` (USD+peg), `strategies` (spatial/stat_z/triangular/funding/regional_mxn), `stream` (hub SSE), `validate` (reconciliación $109.75 + invariantes) |

**Concurrencia clave:** proyecciones en threadpool, serializadas por semáforo (1 a la vez), cache TTL 20s (`router.py:36-56`). Persistencia: `BatchWriter` con cola acotada drop-oldest; poda de fondo cada `db_prune_interval_s`.

## Endpoints (`backend/app/api/v1/router.py`, prefijo `/api/v1`)

- **Vivo:** `GET /stream` (SSE), `/quotes`, `/balances`, `/pnl`
- **Oportunidades:** `/opportunities`, `/opportunities/history`, `/opportunities/{id}/explain`, `POST /opportunities/{id}/what-if`, `/analysis/naive-vs-edge`, `/metrics`
- **Projection Suite:** `/projection`, `/capacity`, `/forward`, `/calibration/survival`
- **Config:** `/config/public`, `/params` (GET/PATCH/reset), `/storage`, `PATCH /storage/retention`
- **Estrategias:** `/strategies[/triangular|/funding|/regional/mxn]`
- **Control (token):** `/control/status|kill-switch|resume`
- **Ejecución:** `/execution/status|preflight|test-order`
- **Demo:** `/demo`, `/demo/scenarios`, `/demo/scenario/{name}`
- **Sistema:** `/info`, `/integrity`, `/validation`, `/session/export`, `/executions`, `/backtest`

Auth: endpoints de control/escritura usan `X-Control-Token` (vacío ⇒ sin auth en dev). API pública: `X-API-Key` + rate limit opcionales (off por defecto).

## Frontend (`frontend/`)

`app/page.tsx` orquesta todo vía `useStream(strategyParams)` (SSE buffer-ref + rAF; poll ligero 5s, pesado 30s). Devuelve: status, quotes, opportunities, routeStats, detectedCount, metrics, breakers, demo, pnl, validation, projection, capacity, forward, survival, naiveVsEdge.

Componentes: PricesTable, OpportunitiesTable, FunnelPanel, LifetimeHistogram, ControlPanel, LiveLineChart, EdgeWaterfall (HERO), BreakEvenFrontier, CapacityCurve, ForwardFanChart, SurvivalCalibrationPanel, NaiveVsEdgePanel, OpportunityExplainDrawer, StrategyLabPanel, StoragePanel, GuidedTour, **ProbabilityLattice** (Canvas), **RelationshipGraph** (Canvas), primitives.

Tour: ids `tour-edge-waterfall`, `tour-naive-edge`, `tour-frontier`, `tour-lattice`, `tour-forward`, `tour-config`.

## MCP server (`backend/mcp_server/server.py`)

`FastMCP`, read-only sobre la API local. Tools: info, list_opportunities, explain_opportunity, naive_vs_edge, get_pnl, get_metrics, get_projection, get_forward, storage_status, quotes. Config `ARB_API_BASE`/`ARB_API_KEY`. Ver `docs/mcp.md`.

## Comandos

```bash
make backend-dev      # uvicorn :8000
make frontend-dev     # next :3000
make backend-test     # pytest
cd backend && ruff check . && mypy app && mypy mcp_server
cd frontend && npx tsc --noEmit && npx next lint && npx next build
```

Verde de referencia: 507 tests · ruff/mypy limpios · frontend tsc/lint/build sin warnings.

## Estado / qué falta (actualizar cada ciclo)

**Hecho recientemente:** Strategy Lab (what-if), Naive-vs-Edge, retención de BD + estimación,
Probability Lattice, API profesionalizada (OpenAPI + /info + guard opcional), MCP server read-only,
tour guiado, Relationship Graph.

**Pendiente / candidatos:**
- Tail Probability Ridge — requiere que el backend exponga **densidades de P&L por horizonte**
  (hoy solo cuantiles por step); no hacerlo a medias.
- UI de estrategias triangular/funding/regional-MXN (endpoints existen sin panel propio).
- Modo replay/timeline con supervivencia observada por latencia.
- MCP remoto (HTTP/SSE + auth) si se quiere acceso fuera de la máquina local.

**Deuda técnica conocida:**
- ~~`useStream` flag `dirty` único~~ → RESUELTO: flags por slice (dirtyQuotes/Opps/Metrics) +
  `React.memo` en PricesTable/OpportunitiesTable/FunnelPanel. Un tick de quote ya no re-renderiza
  opps/routeStats/metrics.
- ~~`getattr(ctx, ...)` disperso en el router~~ → RESUELTO: 55 accesos cambiados a acceso directo
  tipado (`ctx.X`); todos eran campos declarados de AppState, el `getattr` era ruido y devolvía
  `Any` (ocultaba tipos a mypy). Queda solo 1 `getattr` dinámico legítimo (`ctx.settings, key`).
  Separar AppState en dos clases se evaluó y descartó: alto riesgo, valor marginal.

## Convenciones

- Commits sin atribución Claude (preferencia del usuario). Mensaje en español.
- Verificar en verde antes de declarar hecho. No tocar la ruta caliente ni romper $109.75/invariantes.
- Determinismo preservado en demo/validación. Sin deps nuevas salvo necesidad clara.
