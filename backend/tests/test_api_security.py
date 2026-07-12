from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.security import ApiGuardMiddleware


def _app(*, api_key: str = "", rate: int = 0) -> FastAPI:
    app = FastAPI()
    if api_key or rate > 0:
        app.add_middleware(ApiGuardMiddleware, api_key=api_key, rate_limit_per_min=rate)

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "1"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"ok": "1"}

    return app


def test_no_protection_passes_through() -> None:
    with TestClient(_app()) as c:
        assert c.get("/api/v1/ping").status_code == 200


def test_api_key_required_when_set() -> None:
    with TestClient(_app(api_key="secret")) as c:
        assert c.get("/api/v1/ping").status_code == 401
        assert c.get("/api/v1/ping", headers={"X-API-Key": "secret"}).status_code == 200
        assert c.get(
            "/api/v1/ping",
            headers={b"X-API-Key": "secrét".encode("latin-1")},
        ).status_code == 401
        # health queda exento de auth
        assert c.get("/health").status_code == 200


def test_rate_limit_blocks_after_quota() -> None:
    with TestClient(_app(rate=3)) as c:
        codes = [c.get("/api/v1/ping").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429 and codes[4] == 429


def test_info_endpoint_shape() -> None:
    from app.main import app

    with TestClient(app) as c:
        r = c.get("/api/v1/info")
        assert r.status_code == 200
        data = r.json()
        assert data["service"] == "arbitraje-btc"
        assert "capabilities" in data and len(data["capabilities"]) > 5
        assert "enabled_venues" in data
