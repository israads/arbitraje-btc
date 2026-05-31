"""STORY-015 — Integridad de order book por exchange (C2, FR-020)."""
from __future__ import annotations

import time

from app.integrity.checker import (
    BookIntegrityChecker,
    integrity_reason,
)
from app.models.market import RawOrderBook


def _raw(ex="binance", bids=None, asks=None, seq=None) -> RawOrderBook:
    return RawOrderBook(
        exchange=ex, symbol="BTC/USDT", quote_ccy="USDT",
        bids=bids if bids is not None else [(100.0, 1.0), (99.0, 2.0)],
        asks=asks if asks is not None else [(101.0, 1.0), (102.0, 2.0)],
        ts_recv_monotonic=time.monotonic(), seq=seq,
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


# ---- /health expone integridad ----
def test_health_exposes_integrity(client):
    data = client.get("/health").json()
    assert "integrity" in data
