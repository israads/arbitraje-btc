"""MCP server read-only sobre el motor de arbitraje BTC.

Cualquier cliente MCP (p.ej. Claude) puede conectarse y CONSULTAR el motor en lenguaje natural:
qué oportunidades hay, por qué se rechazó una, cómo va el P&L, qué proyecta el Monte Carlo,
cuánto ocupa la base de datos. Todas las herramientas son de SOLO LECTURA: envuelven la API REST
local y nunca ejecutan operaciones ni mutan umbrales (no hay kill switch, ni PATCH, ni control).

Config por entorno:
- `ARB_API_BASE`  base de la API REST (default http://localhost:8000)
- `ARB_API_KEY`   se reenvía como header X-API-Key si la API tiene guard activo

Ejecutar:  `python -m mcp_server.server`  (transporte stdio)
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_BASE = os.environ.get("ARB_API_BASE", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("ARB_API_KEY", "")
_PREFIX = f"{API_BASE}/api/v1"
_TIMEOUT = 10.0

mcp = FastMCP("arbitraje-btc")

# Cliente reusado entre herramientas (pool de conexiones persistente, no uno por request).
_HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}
_client = httpx.AsyncClient(base_url=_PREFIX, headers=_HEADERS, timeout=_TIMEOUT)


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET a la API local. Devuelve JSON o un dict de error legible (nunca lanza al cliente MCP)."""
    try:
        r = await _client.get(path, params=params)
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}", "detail": r.text[:300], "path": path}
        return r.json()
    except httpx.HTTPError as exc:
        return {
            "error": "connection_failed",
            "detail": str(exc),
            "hint": f"¿corre la API en {API_BASE}?",
        }


@mcp.tool()
async def info() -> Any:
    """Metadata del servicio: versión, modo (demo/live), venues habilitados y capacidades."""
    return await _get("/info")


@mcp.tool()
async def list_opportunities(status: str | None = None, limit: int = 20) -> Any:
    """Lista oportunidades recientes. `status` opcional: detected, viable, executable,
    captured o discarded."""
    params: dict[str, Any] = {"limit": max(1, min(limit, 200))}
    if status:
        params["status"] = status
    return await _get("/opportunities", params)


@mcp.tool()
async def explain_opportunity(opportunity_id: str) -> Any:
    """Explica una oportunidad: spread ingenuo vs edge neto del motor, costes y razón."""
    return await _get(f"/opportunities/{opportunity_id}/explain")


@mcp.tool()
async def naive_vs_edge() -> Any:
    """Agregado de sesión: bruto que contaría un detector ingenuo vs neto real del motor y fugas."""
    return await _get("/analysis/naive-vs-edge")


@mcp.tool()
async def get_pnl() -> Any:
    """P&L de la sesión: realizado, no realizado, equity y curva de equity."""
    return await _get("/pnl")


@mcp.tool()
async def get_metrics() -> Any:
    """Métricas del embudo y de ejecución (detected→captured, latencias, spreads efectivos)."""
    return await _get("/metrics")


@mcp.tool()
async def get_projection(mode: str = "demo") -> Any:
    """Break-even frontier (tamaño × fee tier). `mode`: demo|live."""
    return await _get("/projection", {"mode": mode})


@mcp.tool()
async def get_forward(n_paths: int = 2000) -> Any:
    """Forward Monte Carlo de P&L: bandas, prob de profit/ruina, Sharpe/PSR/DSR/MinTRL."""
    return await _get("/forward", {"n_paths": max(100, min(n_paths, 20000))})


@mcp.tool()
async def storage_status() -> Any:
    """Uso de la base de datos y estimación de retención (tamaño actual, tasa, ventanas)."""
    return await _get("/storage")


@mcp.tool()
async def quotes() -> Any:
    """Mejores precios normalizados a USD por exchange y estado del peg."""
    return await _get("/quotes")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
