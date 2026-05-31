"""Smoke del esqueleto: la app arranca (lifespan) y `/health` responde (NFR-008)."""
from __future__ import annotations


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # Multi-venue: contiene los venues clave (lista exacta gestionada en config).
    assert {"binance", "kraken", "coinbase", "gemini", "kucoin"} <= set(body["exchanges"])
    assert body["app"] == "arbitraje-btc"


def test_stream_route_registered(client):
    """El endpoint SSE (C11) está registrado. El test de streaming en vivo
    (publicar/consumir eventos) es de STORY-005, donde se cablea el pipeline."""
    paths = {getattr(r, "path", None) for r in client.app.routes}
    assert "/api/v1/stream" in paths


def test_metrics_endpoint_implemented(client):
    """/metrics ya implementado (C13, STORY-022): embudo + agregados honestos."""
    r = client.get("/api/v1/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["detected"] == 0  # sin tráfico en tests (autostart off)
    assert body["effective_spread"] is None
    assert "by_strategy" in body and "discard_reasons" in body


def test_quotes_snapshot_shape(client):
    """/quotes devuelve snapshot vivo (vacío en tests, sin ingesta)."""
    r = client.get("/api/v1/quotes")
    assert r.status_code == 200
    body = r.json()
    assert body["quotes"] == [] and "peg" in body


def test_opportunities_funnel_shape(client):
    r = client.get("/api/v1/opportunities")
    assert r.status_code == 200
    body = r.json()
    assert body["opportunities"] == []
    assert body["funnel"]["detected"] == 0
