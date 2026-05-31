"""C14 backtest (record & replay) + C16 fallback de demo. FR-014, FR-018.

Graba ticks/snapshots con ts y los reproduce cronológicamente point-in-time por el
MISMO motor/simulador (Sharpe/win rate/drawdown). El fallback conmuta a replay al
caer el feed y marca badge "DEMO DATA".

Implementación: STORY-021 (backtest), STORY-024 (fallback).
"""
from __future__ import annotations

from .recorder import Recorder
from .replay import run_backtest

__all__ = ["Recorder", "run_backtest"]
