# MCP server (consulta del motor desde Claude)

Un servidor **MCP read-only** que permite a cualquier cliente MCP —como Claude— **consultar el
motor en lenguaje natural**: qué oportunidades hay, por qué se rechazó una, cómo va el P&L, qué
proyecta el Monte Carlo, cuánto ocupa la base de datos. Es el mismo patrón que conecta Claude con
herramientas externas, pero sobre **tu propio backend** — sin suscripciones, sin APIs de terceros
y sin riesgo de Términos de Uso.

> **Solo lectura por diseño.** Las herramientas envuelven la API REST local y nunca ejecutan
> operaciones ni mutan umbrales: no hay kill switch, ni PATCH, ni control. Un test lo verifica.

## Arquitectura

```
Cliente MCP (Claude) ↔ mcp_server (stdio) ↔ API REST local (/api/v1) ↔ motor
```

## Requisitos

- Backend corriendo (`make backend-dev`, default `http://localhost:8000`).
- Dependencia opcional `mcp`: `uv pip install "mcp>=1.2"` (o `pip install -e ".[mcp]"`).

## Herramientas expuestas

| Herramienta | Qué responde |
|-------------|--------------|
| `info` | versión, modo (demo/live), venues, capacidades |
| `list_opportunities(status?, limit?)` | oportunidades recientes (filtrables por estado) |
| `explain_opportunity(id)` | spread ingenuo vs edge neto, costes y razón de la decisión |
| `naive_vs_edge` | agregado de sesión: bruto aparente vs neto real y fugas |
| `get_pnl` | P&L realizado/no realizado, equity y curva |
| `get_metrics` | embudo y métricas de ejecución |
| `get_projection(mode)` | break-even frontier |
| `get_forward(n_paths)` | Monte Carlo forward + honestidad estadística |
| `storage_status` | uso de la DB y estimación de retención |
| `quotes` | mejores precios por venue + peg |

## Configuración

Variables de entorno del server:
- `ARB_API_BASE` — base de la API (default `http://localhost:8000`)
- `ARB_API_KEY` — se reenvía como `X-API-Key` si la API tiene guard activo

## Conectarlo a Claude Code

Añade a tu configuración MCP (`~/.claude.json` o `claude mcp add`):

```json
{
  "mcpServers": {
    "arbitraje-btc": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/ruta/al/repo/backend",
      "env": { "ARB_API_BASE": "http://localhost:8000" }
    }
  }
}
```

O por CLI:

```bash
claude mcp add arbitraje-btc -- python -m mcp_server.server
```

Luego, en Claude:

> *¿Cuáles son las 3 mejores oportunidades ahora y por qué el motor las tomaría o no?*
> *¿Por qué se descartó la oportunidad opp-1242?*
> *¿Cuánto ocuparía la base de datos con retención de 12 horas?*

## Ejecutar directamente (debug)

```bash
cd backend
python -m mcp_server.server   # transporte stdio
```
