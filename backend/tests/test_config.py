"""Verifica que la configuración carga los defaults del Apéndice E (C17)."""
from __future__ import annotations

from app.config import Settings


def test_appendix_e_defaults():
    s = Settings()
    # Fees taker por exchange (taker/taker, base).
    assert s.exchanges["binance"].fee_taker == 0.0010
    assert s.exchanges["kraken"].fee_taker == 0.0040
    assert s.exchanges["coinbase"].fee_taker == 0.0060
    # STORY-013: Coinbase habilitado como 3er exchange.
    assert s.exchanges["coinbase"].enabled is True
    # Multi-venue: el set habilitado contiene los venues con WS sostenido verificado
    # (scripts/probe_exchanges.py). okx/bitfinex existen pero quedan deshabilitados.
    enabled = {e.id for e in s.enabled_exchanges}
    expected = {"binance", "kraken", "coinbase", "gemini", "bitstamp",
                "bybit", "bitget", "kucoin", "gateio"}
    assert expected <= enabled
    assert s.exchanges["okx"].enabled is False
    assert s.exchanges["bitfinex"].enabled is False


def test_appendix_e_thresholds():
    s = Settings()
    assert (s.z_open, s.z_close, s.z_stop) == (2.0, 0.5, 3.0)
    assert s.staleness_ms == 750
    assert s.max_slippage == 0.0010
    assert s.peg_tolerance == 0.005
    assert 100 <= s.zscore_window <= 300
    assert 100 <= s.exec_latency_ms <= 200


def test_peg_never_one_to_one():
    """El peg se observa de un par vivo; nunca se asume 1.00 (FR-003)."""
    s = Settings()
    assert "USDT" in s.peg_pairs
    assert s.peg_pairs["USDT"] != "1.00"


def test_execution_defaults_are_safe():
    """PRD-003: ejecución y test orders quedan apagados por defecto."""
    s = Settings()
    assert s.execution_mode == "disabled"
    assert s.enable_test_orders is False
    assert not s.binance_testnet_api_key
    assert not s.binance_testnet_api_secret


def test_integrity_defaults_to_warn_mode():
    """PRD-004: validadores específicos observan primero, sin bloquear por default."""
    s = Settings()
    assert s.integrity_mode == "warn"
