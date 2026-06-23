"""STORY-015 — Integridad de order book por exchange (C2, FR-020)."""
from __future__ import annotations

import time

from app.integrity.checker import (
    BookIntegrityChecker,
    integrity_reason,
)
from app.integrity.validators import kraken_crc32
from app.models.market import RawOrderBook


def _raw(ex="binance", bids=None, asks=None, seq=None, meta=None) -> RawOrderBook:
    return RawOrderBook(
        exchange=ex, symbol="BTC/USDT", quote_ccy="USDT",
        bids=bids if bids is not None else [(100.0, 1.0), (99.0, 2.0)],
        asks=asks if asks is not None else [(101.0, 1.0), (102.0, 2.0)],
        ts_recv_monotonic=time.monotonic(), seq=seq, meta=meta or {},
    )


# ---- integrity_reason (puro) ----
def test_valid_book_ok():
    assert integrity_reason(_raw(), None) is None


def test_empty_side():
    assert integrity_reason(_raw(bids=[]), None) == "empty_side"
    assert integrity_reason(_raw(asks=[]), None) == "empty_side"


def test_nonpositive():
    assert integrity_reason(_raw(bids=[(0.0, 1.0)]), None) == "nonpositive"
    assert integrity_reason(_raw(asks=[(101.0, 0.0)]), None) == "nonpositive"
    assert integrity_reason(_raw(bids=[(-1.0, 1.0)]), None) == "nonpositive"


def test_unsorted():
    assert integrity_reason(_raw(bids=[(99.0, 1.0), (100.0, 1.0)]), None) == "bids_unsorted"
    assert integrity_reason(_raw(asks=[(102.0, 1.0), (101.0, 1.0)]), None) == "asks_unsorted"


def test_crossed_book():
    # mejor bid (102) > mejor ask (101) => cruzado
    assert integrity_reason(_raw(bids=[(102.0, 1.0)], asks=[(101.0, 1.0)]), None) == "crossed_book"


def test_locked_book_tolerated():
    # bid == ask (locked) NO se rechaza (puede ocurrir brevemente)
    assert integrity_reason(_raw(bids=[(101.0, 1.0)], asks=[(101.0, 1.0)]), None) is None


def test_seq_regression():
    assert integrity_reason(_raw(seq=5), last_seq=10) == "seq_regression"
    # seq igual o mayor: ok
    assert integrity_reason(_raw(seq=10), last_seq=10) is None
    assert integrity_reason(_raw(seq=11), last_seq=10) is None
    # seq None tolerado (exchange que no lo provee)
    assert integrity_reason(_raw(seq=None), last_seq=10) is None


# ---- BookIntegrityChecker (estado + estadísticas) ----
def test_checker_accept_and_stats():
    c = BookIntegrityChecker()
    assert c.check(_raw(seq=1)) is True
    assert c.check(_raw(seq=2)) is True
    rep = c.reports()["binance"]
    assert rep["validator"] == "binance"
    assert rep["accepted"] == 2
    assert rep["rejected"] == 0
    assert rep["last_reason"] is None


def test_checker_tracks_last_seq_and_rejects_regression():
    c = BookIntegrityChecker()
    assert c.check(_raw(seq=10)) is True
    assert c.check(_raw(seq=4)) is False  # regresión respecto a 10
    rep = c.reports()["binance"]
    assert rep["accepted"] == 1
    assert rep["rejected"] == 1
    assert rep["last_reason"] == "seq_regression"
    # un libro válido posterior (seq>=10) se vuelve a aceptar
    assert c.check(_raw(seq=11)) is True


def test_checker_rejected_book_does_not_advance_seq():
    c = BookIntegrityChecker()
    c.check(_raw(seq=10))
    c.check(_raw(bids=[], seq=99))  # rechazado por empty_side (no avanza last_seq)
    rep = c.reports()["binance"]
    assert rep["rejected"] == 1
    # last_seq sigue en 10 → un seq=9 se rechazaría, seq=10 se acepta
    assert c.check(_raw(seq=10)) is True


def test_checker_per_venue_isolation():
    c = BookIntegrityChecker()
    c.check(_raw(ex="binance", seq=5))
    c.check(_raw(ex="kraken", seq=1))  # kraken empieza de cero, no afecta binance
    assert c.reports()["binance"]["accepted"] == 1
    assert c.reports()["kraken"]["accepted"] == 1


def test_binance_detects_sequence_gap_in_warn_mode_without_blocking():
    c = BookIntegrityChecker(mode="warn")
    assert c.check(_raw(ex="binance", seq=10, meta={"U": 1, "u": 10})) is True
    assert c.check(_raw(ex="binance", seq=20, meta={"U": 15, "u": 20})) is True
    rep = c.reports()["binance"]
    assert rep["accepted"] == 2
    assert rep["rejected"] == 0
    assert rep["sequence_gaps"] == 1
    assert rep["last_reason"] == "sequence_gap"
    assert rep["last_seq"] == 20


def test_binance_enforce_blocks_sequence_gap():
    c = BookIntegrityChecker(mode="enforce")
    assert c.check(_raw(ex="binance", seq=10, meta={"U": 1, "u": 10})) is True
    assert c.check(_raw(ex="binance", seq=20, meta={"U": 15, "u": 20})) is False
    rep = c.reports()["binance"]
    assert rep["accepted"] == 1
    assert rep["rejected"] == 1
    assert rep["sequence_gaps"] == 1
    assert rep["last_seq"] == 10


def test_binance_accepts_monotonic_updates():
    c = BookIntegrityChecker(mode="enforce")
    assert c.check(_raw(ex="binance", seq=10, meta={"U": 1, "u": 10})) is True
    assert c.check(_raw(ex="binance", seq=11, meta={"U": 11, "u": 11})) is True
    assert c.reports()["binance"]["sequence_gaps"] == 0


def test_kraken_checksum_failure_is_visible_in_warn_mode():
    c = BookIntegrityChecker(mode="warn")
    assert c.check(_raw(ex="kraken", seq=1, meta={"checksum": "bad"})) is True
    rep = c.reports()["kraken"]
    assert rep["accepted"] == 1
    assert rep["rejected"] == 0
    assert rep["checksum_failures"] == 1
    assert rep["last_reason"] == "checksum_failure"


def test_kraken_checksum_passes_when_crc_matches():
    raw = _raw(ex="kraken", seq=1)
    checksum = kraken_crc32(raw.bids, raw.asks)
    c = BookIntegrityChecker(mode="enforce")
    assert c.check(raw.model_copy(update={"meta": {"checksum": checksum}})) is True
    rep = c.reports()["kraken"]
    assert rep["checksum_failures"] == 0
    assert rep["last_checksum"] == checksum


def test_coinbase_sequence_gap_is_visible():
    c = BookIntegrityChecker(mode="warn")
    assert c.check(_raw(ex="coinbase", seq=100)) is True
    assert c.check(_raw(ex="coinbase", seq=105)) is True
    rep = c.reports()["coinbase"]
    assert rep["sequence_gaps"] == 1
    assert rep["last_reason"] == "sequence_gap"


# ---- /health expone integridad ----
def test_health_exposes_integrity(client):
    data = client.get("/health").json()
    assert "integrity" in data


def test_integrity_endpoint_contract(client):
    ctx = client.app.state.ctx
    ctx.integrity.check(_raw(ex="binance", seq=10, meta={"U": 1, "u": 10}))
    data = client.get("/api/v1/integrity").json()
    assert data["binance"]["validator"] == "binance"
    assert data["binance"]["accepted"] == 1
    assert {"rejected", "sequence_gaps", "checksum_failures", "last_valid_at"} <= set(
        data["binance"]
    )


def test_integrity_metrics_include_reports(client):
    ctx = client.app.state.ctx
    ctx.integrity.check(_raw(ex="kraken", seq=1, meta={"checksum": "bad"}))
    data = client.get("/api/v1/metrics").json()
    assert data["integrity"]["kraken"]["checksum_failures"] == 1
