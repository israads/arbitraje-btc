"""Diccionario de enums — contrato explícito del pipeline (sin ambigüedad)."""
from __future__ import annotations

from enum import StrEnum


class Strategy(StrEnum):
    spatial = "spatial"
    stat_z = "stat_z"
    # stretch (FR-019): triangular = "triangular"


class OpportunityStatus(StrEnum):
    """Ciclo de vida: detected → viable → executable → captured | discarded."""

    detected = "detected"
    viable = "viable"          # neto > umbral tras fees
    executable = "executable"  # sobrevive a latencia/liquidez
    captured = "captured"      # simulada
    discarded = "discarded"


class DiscardReason(StrEnum):
    not_profitable_fees = "not_profitable_fees"
    thin_book = "thin_book"
    peg_adverse = "peg_adverse"
    slippage_over_limit = "slippage_over_limit"
    breaker_active = "breaker_active"
    stale_venue = "stale_venue"
    insufficient_balance = "insufficient_balance"
    z_below_threshold = "z_below_threshold"


class LegSide(StrEnum):
    buy = "buy"
    sell = "sell"


class ConnectionStatus(StrEnum):
    live = "live"
    reconnecting = "reconnecting"
    stale = "stale"
    replay = "replay"


class BreakerType(StrEnum):
    stale_data = "stale_data"
    volatility = "volatility"
    inventory_skew = "inventory_skew"
    max_drawdown = "max_drawdown"
    kill_switch = "kill_switch"
