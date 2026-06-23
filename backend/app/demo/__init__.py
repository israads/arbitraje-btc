"""C16 — Fallback a replay para demo (FR-018, STORY-024).

Si los feeds reales caen (o por orden manual), reproduce los `NormalizedBook` GRABADOS
(C14) por el MISMO pipeline para que el dashboard siga vivo durante la demo, con badge
"DEMO DATA"; vuelve a vivo al recuperarse el feed real.
"""
from __future__ import annotations

from .fallback import DemoFallback
from .scenarios import JuryFrame, JuryScenario, JuryScenarioPlayer, PegUpdate

__all__ = ["DemoFallback", "JuryFrame", "JuryScenario", "JuryScenarioPlayer", "PegUpdate"]
