from __future__ import annotations

import httpx
import pytest

from mcp_server import server


async def test_tools_registered() -> None:
    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}
    assert {
        "info",
        "list_opportunities",
        "explain_opportunity",
        "naive_vs_edge",
        "get_pnl",
        "get_forward",
        "storage_status",
    } <= names


async def test_get_returns_error_dict_on_conn_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_get` nunca lanza: ante un fallo de red devuelve un dict de error legible."""

    class _Boom:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Boom())
    out = await server._get("/info")
    assert out["error"] == "connection_failed"
    assert "hint" in out


async def test_read_only_has_no_mutating_tools() -> None:
    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}
    # Garantía de diseño: el server es de solo lectura.
    for forbidden in ("kill", "resume", "patch", "params", "execute", "control", "test_order"):
        assert not any(forbidden in n for n in names)
