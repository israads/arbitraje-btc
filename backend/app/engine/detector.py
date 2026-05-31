"""C5 — Detección espacial naive (FR-004).

Mantiene el último book normalizado por venue y detecta cruces `Ask_A < Bid_B`
(precios YA en USD). Emite `Opportunity(status=detected)` con top-of-book como
estimación (el VWAP real por niveles llega en STORY-008). Sella `t_detect` y la
latencia respecto al tick que disparó la detección. Excluye venues sin dato.
"""
from __future__ import annotations

import time

from ..config import Settings
from ..models.enums import OpportunityStatus, Strategy
from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity
from ..risk.watchdog import is_stale


class SpatialDetector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._books: dict[str, NormalizedBook] = {}
        self._n = 0

    @property
    def books(self) -> dict[str, NormalizedBook]:
        """Último book normalizado por venue (acceso de sólo lectura para el
        evaluador C6). No exponer para mutar: el detector es dueño del estado."""
        return self._books

    def on_book(self, nb: NormalizedBook, *, now: float | None = None) -> list[Opportunity]:
        self._books[nb.exchange] = nb
        return self._detect(trigger=nb, now=now)

    def _detect(self, trigger: NormalizedBook, now: float | None = None) -> list[Opportunity]:
        # `now` inyectable para el REPLAY (STORY-021): la staleness se mide contra el reloj de
        # los ticks GRABADOS (point-in-time), no el reloj de pared (que en replay es muy
        # posterior y marcaría todo stale). En vivo `now=None` → `time.monotonic()` (sin cambio).
        t_detect = time.monotonic() if now is None else now
        # STORY-014: excluye venues stale (libro congelado > staleness_ms). Race-free:
        # se computa contra `t_detect`, sin depender de la cadencia del watchdog.
        staleness_ms = self.settings.staleness_ms
        venues = [
            v for v, b in self._books.items()
            if b.best_ask is not None and b.best_bid is not None
            and not is_stale(b.ts_recv_monotonic, t_detect, staleness_ms)
        ]
        opps: list[Opportunity] = []
        for a in venues:
            for b in venues:
                if a == b:
                    continue
                ask_a = self._books[a].best_ask
                bid_b = self._books[b].best_bid
                if ask_a is not None and bid_b is not None and ask_a < bid_b:
                    self._n += 1
                    opps.append(
                        Opportunity(
                            id=f"opp-{self._n}",
                            strategy=Strategy.spatial,
                            symbol=trigger.symbol,
                            buy_venue=a,
                            sell_venue=b,
                            q_target=self.settings.default_trade_qty_btc,
                            vwap_buy=ask_a,    # top-of-book; VWAP real en STORY-008
                            vwap_sell=bid_b,
                            status=OpportunityStatus.detected,
                            t_recv=trigger.ts_recv_monotonic,
                            t_detect=t_detect,
                            latency_ms=(t_detect - trigger.ts_recv_monotonic) * 1000.0,
                        )
                    )
        return opps
