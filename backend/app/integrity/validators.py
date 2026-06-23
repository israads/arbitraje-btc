"""Validadores de integridad por venue.

Las reglas específicas se aplican sólo cuando `RawOrderBook.meta` trae metadata suficiente.
Si ccxt.pro no expone el dato, el validator cae de forma explícita a la validación genérica.
"""
from __future__ import annotations

import zlib
from decimal import Decimal
from typing import Any, Protocol

from ..models.market import PriceLevel, RawOrderBook
from .models import IntegrityDecision, IntegrityReport


class VenueIntegrityValidator(Protocol):
    name: str

    def check(self, raw: RawOrderBook, report: IntegrityReport) -> IntegrityDecision:
        ...


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def meta_int(meta: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        val = _as_int(meta.get(key))
        if val is not None:
            return val
    return None


def structural_integrity_reason(raw: RawOrderBook, last_seq: int | None) -> str | None:
    """Motivo genérico de rechazo, o None si la estructura es íntegra."""
    bids, asks = raw.bids, raw.asks
    if not bids or not asks:
        return "empty_side"
    for side in (bids, asks):
        for px, qty in side:
            if px <= 0 or qty <= 0:
                return "nonpositive"
    if any(bids[i][0] < bids[i + 1][0] for i in range(len(bids) - 1)):
        return "bids_unsorted"
    if any(asks[i][0] > asks[i + 1][0] for i in range(len(asks) - 1)):
        return "asks_unsorted"
    if bids[0][0] > asks[0][0]:
        return "crossed_book"
    if last_seq is not None and raw.seq is not None and raw.seq < last_seq:
        return "seq_regression"
    return None


class GenericIntegrityValidator:
    name = "generic"

    def check(self, raw: RawOrderBook, report: IntegrityReport) -> IntegrityDecision:
        reason = structural_integrity_reason(raw, report.last_seq)
        return IntegrityDecision(
            accepted=reason is None,
            reason=reason,
            validator=self.name,
            seq=raw.seq,
            severity="error",
        )


class BinanceIntegrityValidator:
    """Valida continuidad `U/u` cuando ccxt.pro expone esos IDs en metadata."""

    name = "binance"

    def __init__(self) -> None:
        self._generic = GenericIntegrityValidator()

    def check(self, raw: RawOrderBook, report: IntegrityReport) -> IntegrityDecision:
        base = self._generic.check(raw, report)
        if not base.accepted:
            return base.model_copy(update={"validator": self.name})

        first = meta_int(raw.meta, "first_update_id", "U")
        final = meta_int(raw.meta, "final_update_id", "u", "lastUpdateId") or raw.seq
        if report.last_seq is not None:
            if final is not None and final < report.last_seq:
                return IntegrityDecision(
                    accepted=False,
                    reason="seq_regression",
                    validator=self.name,
                    seq=final,
                    severity="error",
                )
            if first is not None and first > report.last_seq + 1:
                return IntegrityDecision(
                    accepted=False,
                    reason="sequence_gap",
                    validator=self.name,
                    seq=final,
                    severity="warn",
                )
        return IntegrityDecision(accepted=True, validator=self.name, seq=final)


def _kraken_decimal(value: float) -> str:
    text = format(Decimal(str(value)).normalize(), "f")
    return text.replace(".", "").lstrip("0") or "0"


def kraken_crc32(bids: list[PriceLevel], asks: list[PriceLevel]) -> str:
    """CRC32 Kraken L2 sobre top 10 asks y top 10 bids.

    Kraken calcula el checksum sobre los 10 mejores niveles de ambos lados. Esta función usa
    la representación decimal recibida en el `RawOrderBook`; para producción real conviene
    preservar strings originales si ccxt los expone.
    """
    parts: list[str] = []
    for levels in (asks[:10], bids[:10]):
        for price, qty in levels:
            parts.append(_kraken_decimal(price))
            parts.append(_kraken_decimal(qty))
    return str(zlib.crc32("".join(parts).encode("ascii")) & 0xFFFFFFFF)


class KrakenIntegrityValidator:
    name = "kraken"

    def __init__(self) -> None:
        self._generic = GenericIntegrityValidator()

    def check(self, raw: RawOrderBook, report: IntegrityReport) -> IntegrityDecision:
        base = self._generic.check(raw, report)
        if not base.accepted:
            return base.model_copy(update={"validator": self.name})

        checksum = raw.meta.get("checksum") or raw.meta.get("checksum_crc32")
        valid_flag = raw.meta.get("checksum_valid")
        computed = kraken_crc32(raw.bids, raw.asks) if checksum is not None else None
        if valid_flag is False or (checksum is not None and str(checksum) != computed):
            return IntegrityDecision(
                accepted=False,
                reason="checksum_failure",
                validator=self.name,
                seq=raw.seq,
                checksum=str(checksum) if checksum is not None else computed,
                severity="warn",
            )
        return IntegrityDecision(
            accepted=True,
            validator=self.name,
            seq=raw.seq,
            checksum=str(checksum) if checksum is not None else computed,
        )


class CoinbaseIntegrityValidator:
    name = "coinbase"

    def __init__(self) -> None:
        self._generic = GenericIntegrityValidator()

    def check(self, raw: RawOrderBook, report: IntegrityReport) -> IntegrityDecision:
        base = self._generic.check(raw, report)
        if not base.accepted:
            return base.model_copy(update={"validator": self.name})

        seq = raw.seq or meta_int(raw.meta, "sequence", "sequence_num")
        if raw.meta.get("sequence_gap") is True:
            return IntegrityDecision(
                accepted=False,
                reason="sequence_gap",
                validator=self.name,
                seq=seq,
                severity="warn",
            )
        if report.last_seq is not None and seq is not None and seq > report.last_seq + 1:
            return IntegrityDecision(
                accepted=False,
                reason="sequence_gap",
                validator=self.name,
                seq=seq,
                severity="warn",
            )
        return IntegrityDecision(accepted=True, validator=self.name, seq=seq)


VALIDATORS: dict[str, VenueIntegrityValidator] = {
    "binance": BinanceIntegrityValidator(),
    "kraken": KrakenIntegrityValidator(),
    "coinbase": CoinbaseIntegrityValidator(),
}
