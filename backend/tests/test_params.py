from __future__ import annotations


def test_params_endpoint_patches_and_resets_runtime_overrides(client):
    initial = client.get("/api/v1/params")
    assert initial.status_code == 200
    assert initial.json()["scope"] == "what_if_and_projection_only"

    patched = client.patch(
        "/api/v1/params",
        json={
            "default_trade_qty_btc": 0.25,
            "fee_bps": 5.0,
            "exec_latency_ms": 250,
            "enabled_exchange_overrides": {"kraken": False},
        },
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["effective"]["default_trade_qty_btc"] == 0.25
    assert body["effective"]["fee_bps"] == 5.0
    assert body["effective"]["exec_latency_ms"] == 250
    assert body["exchanges"]["kraken"]["enabled"] is False

    exported = client.get("/api/v1/session/export").json()
    assert exported["runtime_params"]["effective"]["fee_bps"] == 5.0

    reset = client.post("/api/v1/params/reset")
    assert reset.status_code == 200
    assert reset.json()["overrides"] == {}
