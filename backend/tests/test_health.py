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
    assert body["mode"] == "live_readonly"
    assert body["execution_enabled"] is False
    assert body["test_orders_enabled"] is False
    assert body["control_token_required"] is False


class _StubTask:
    """Duck-type mínimo de asyncio.Task para _task_status: done/cancelled/exception/get_name."""

    def __init__(self, name: str, state: str):
        self._name = name
        self._state = state

    def get_name(self) -> str:
        return self._name

    def done(self) -> bool:
        return self._state != "running"

    def cancelled(self) -> bool:
        return self._state == "cancelled"

    def exception(self) -> BaseException | None:
        return RuntimeError("boom") if self._state == "failed" else None


def _health_with_task(client, state: str) -> dict:
    ctx = client.app.state.ctx
    stub = _StubTask(f"stub_{state}", state)
    ctx.tasks.append(stub)
    try:
        return client.get("/health").json()
    finally:
        ctx.tasks.remove(stub)


def test_health_degrades_on_failed_task(client):
    """RF-004: task con excepción → degraded (caso ya cubierto antes del PRD-011)."""
    body = _health_with_task(client, "failed")
    assert body["status"] == "degraded"
    assert body["tasks"]["stub_failed"] == "failed"


def test_health_degrades_on_finished_task(client):
    """RF-004: una task que retornó (p.ej. feeds con TODOS los runners muertos) ya no
    trabaja — `finished` NO es benigno, degrada mientras el endpoint siga sirviendo."""
    body = _health_with_task(client, "finished")
    assert body["status"] == "degraded"
    assert body["tasks"]["stub_finished"] == "finished"


def test_health_degrades_on_cancelled_task(client):
    """RF-004: cancelación (shutdown en curso) degrada cualquier respuesta aún en vuelo."""
    body = _health_with_task(client, "cancelled")
    assert body["status"] == "degraded"
    assert body["tasks"]["stub_cancelled"] == "cancelled"


def test_health_degrades_on_dead_writer(client):
    """RF-004: writer muerto con tasks sanas → degraded (la persistencia dejó de escribir)."""
    ctx = client.app.state.ctx
    original = ctx.writer.is_alive
    ctx.writer.is_alive = lambda: False  # type: ignore[method-assign]
    try:
        body = client.get("/health").json()
    finally:
        ctx.writer.is_alive = original  # type: ignore[method-assign]
    assert body["status"] == "degraded"
    assert body["tasks"]["writer"] == "failed"


def test_health_ok_with_running_tasks_and_live_writer(client):
    """Caso sano explícito: tasks running + writer vivo → ok, con detalle por nombre."""
    body = _health_with_task(client, "running")
    assert body["status"] == "ok"
    assert body["tasks"]["stub_running"] == "running"
    assert body["tasks"]["writer"] == "running"
    # db_retention corre con el default de 24 h incluso con autostart off (main.py).
    assert body["tasks"]["db_retention"] == "running"


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


def test_prometheus_metrics_endpoint(client):
    """/metrics expone texto Prometheus para scrapers externos (PRD-006)."""
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert "# TYPE arb_opportunities_total counter" in body
    assert 'arb_opportunities_total{status="detected"} 0' in body
    assert "arb_opportunities_detected_total 0" in body
    assert "arb_breaker_halted 0" in body
    assert "arb_execution_enabled 0" in body
    assert "arb_demo_active" in body


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
