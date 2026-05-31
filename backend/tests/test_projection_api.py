"""Smoke HTTP de los endpoints de la Projection Suite v2 (router /api/v1).

Verifica el cableado real (TestClient + lifespan): forma de respuesta y modos. Sin red
(ARB_INGEST_AUTOSTART=false en conftest); en autostart-safe la frontier/capacity caen a demo.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.models.market import NormalizedBook


def _seed_live_books(client: TestClient) -> None:
    """Siembra `ctx.latest_norm`, el estado real que usa el dashboard antes del motor."""
    ctx = client.app.state.ctx
    ctx.latest_norm.update({
        "binance": NormalizedBook(
            exchange="binance", symbol="BTC/USD", quote_ccy="USD",
            bids=[(69_990.0, 5.0)], asks=[(70_000.0, 5.0)], ts_recv_monotonic=1.0,
        ),
        "kraken": NormalizedBook(
            exchange="kraken", symbol="BTC/USD", quote_ccy="USD",
            bids=[(70_090.0, 5.0)], asks=[(70_100.0, 5.0)], ts_recv_monotonic=1.0,
        ),
    })


def test_projection_endpoint_demo_shape():
    with TestClient(app) as client:
        r = client.get("/api/v1/projection?mode=demo")
        assert r.status_code == 200
        d = r.json()
        for k in ("mode", "sizes_btc", "fee_tiers", "matrix", "net_usd", "p_survive",
                  "expected_edge", "depth_limited", "dominant_cost", "best", "gross_top_per_btc"):
            assert k in d
        assert d["mode"] == "demo"
        assert d["best"]["by_unit_edge"]["net_per_btc"] > 0


def test_projection_live_falls_back_without_feeds():
    """Sin feeds (tests) el modo live cae a demo de forma honesta, sin error."""
    with TestClient(app) as client:
        r = client.get("/api/v1/projection?mode=live")
        assert r.status_code == 200
        assert r.json()["mode"] == "demo"


def test_projection_rejects_invalid_mode():
    with TestClient(app) as client:
        r = client.get("/api/v1/projection?mode=paper")
        assert r.status_code == 422


def test_projection_live_uses_latest_norm_books():
    """Regresión: `mode=live` debe leer `ctx.latest_norm`/detector.books, no `ctx.books`."""
    with TestClient(app) as client:
        _seed_live_books(client)
        r = client.get("/api/v1/projection?mode=live")
        assert r.status_code == 200
        d = r.json()
        assert d["mode"] == "live"
        assert d["route"] == {"buy": "binance", "sell": "kraken", "symbol": "BTC/USD"}


def test_capacity_endpoint_shape():
    with TestClient(app) as client:
        r = client.get("/api/v1/capacity?mode=demo")
        assert r.status_code == 200
        d = r.json()
        assert "points" in d and len(d["points"]) >= 2
        assert d["q_star_btc"] is not None and d["q_star_btc"] > 0


def test_capacity_rejects_invalid_mode():
    with TestClient(app) as client:
        r = client.get("/api/v1/capacity?mode=paper")
        assert r.status_code == 422


def test_capacity_live_uses_latest_norm_books():
    """Capacity live comparte el mismo cableado de libros vivos que la frontier."""
    with TestClient(app) as client:
        _seed_live_books(client)
        r = client.get("/api/v1/capacity?mode=live")
        assert r.status_code == 200
        d = r.json()
        assert d["mode"] == "live"
        assert d["route"] == {"buy": "binance", "sell": "kraken", "symbol": "BTC/USD"}


def test_forward_endpoint_unavailable_without_trades():
    """Sin grabación/trades el forward responde available=false (autostart-safe), no 500."""
    with TestClient(app) as client:
        r = client.get("/api/v1/forward?n_paths=500")
        assert r.status_code == 200
        assert r.json()["available"] is False
