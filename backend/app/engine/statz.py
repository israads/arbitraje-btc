"""C5 — Arbitraje estadístico (z-score del spread log entre venues). FR-006, STORY-019.

Segunda estrategia, ortogonal a la detección espacial naive (C5 `SpatialDetector`).
Modela el spread del MISMO activo entre dos venues como un proceso mean-reverting y
opera desviaciones estadísticamente anómalas, en vez de cada micro-cruce de book.

  spread_t = ln(mid_B) - ln(mid_A)        # mid = (best_bid + best_ask) / 2 (YA en USD)
  mean_t   = rolling_W(spread).mean()     # causal: ventana que TERMINA en t (sin look-ahead)
  std_t    = rolling_W(spread).std(ddof=0)
  z_t      = (spread_t - mean_t) / std_t

Sobre los precios NORMALIZADOS (NormalizedBook, peg vivo): el spread es de mercado real,
no de desviación de peg. La ventana es estrictamente CAUSAL (un `deque(maxlen=W)` que sólo
contiene observaciones pasadas y la actual; `center=True` es imposible por construcción).

---
MÁQUINA DE ESTADOS POR PAR (honra los TRES umbrales sin inventario cross-tick).

El simulador (C9) ejecuta un round-trip atómico por oportunidad (compra+venta en el mismo
snapshot), no mantiene una posición abierta a la espera de reversión. Para honrar de forma
honesta los umbrales open/close/stop de mean-reversion SIN un modelo de posición persistente,
cada par lleva un flag `armed` (listo para disparar):

  - `armed` se ARMA cuando |z| < z_close (el spread está cerca de su media: régimen normal).
  - Estando armado y |z| cruza a [z_open, z_stop)  → DISPARA una señal (entrada) y se desarma.
  - Estando armado y |z| >= z_stop                 → STAND-DOWN: la relación se considera ROTA
    (régimen quebrado, justo donde el arbitraje naive se lastima); NO dispara y se desarma.
  - Tras disparar o hacer stand-down, sólo se RE-ARMA cuando |z| vuelve a < z_close.

Así cada blow-out del spread genera UNA señal (no una por tick mientras |z|>z_open), se respeta
el stop como "no abrir en régimen roto", y el close actúa como condición de re-armado. Esto
acota la tasa de disparo y mapea la semántica entrada/salida/stop sobre un modelo de ejecución
sin estado de posición.

---
VALIDACIÓN NETA (FR-006 AC#4 / reusa FR-005): el z-score sólo elige DIRECCIÓN y MOMENTO. Cada
señal disparada se emite como `Opportunity(strategy=stat_z, status=detected)` con buy/sell venue
según el signo de z; el motor la pasa por el MISMO `NetEvaluator` (C6) ANTES de simular. Una
anomalía estadística que además es un cruce ejecutable neto-positivo → `viable` (la mejor clase
de señal); si tras fees/slippage no es ejecutable → `discarded` — honesto: la desviación existe
pero no es capturable. La dirección:

  pair ordenado (a, b) con a < b ; spread = ln(mid_b) - ln(mid_a)
  z > 0  → mid_b caro relativo a mid_a → vender en b, comprar en a  → buy=a, sell=b
  z < 0  → mid_a caro relativo a mid_b → vender en a, comprar en b  → buy=b, sell=a

---
MATICES HONESTOS (decisiones de diseño, no defectos):

  - MUESTREO EVENT-DRIVEN: la ventana W mide "ticks de CUALQUIERA de las dos patas", no
    actualizaciones síncronas del spread. Cada book entrante genera una observación para los
    pares que lo contienen, leyendo el top-of-book más reciente de la contraparte (asíncrono).
    Es el enfoque estándar para z-score entre feeds asíncronos; la pata más activa pondera más
    la ventana. Para feeds líquidos comparables (Binance/Kraken/Coinbase) el sesgo es menor.
  - ARMADO INICIAL: un par se arma al CREARSE (ventana aún por llenar). El primer cómputo con
    ventana completa puede disparar si |z| ya está en banda — la ventana de W observaciones reales
    ES el baseline. Es una señal estadística legítima y, además, acotada: a lo sumo UNA por par y
    siempre filtrada por el neto ejecutable (una anomalía no capturable → discarded).
  - MEMORIA: `_windows`/`_armed` tienen una entrada por par de venues. Acotado a C(N,2) con N =
    venues habilitados (3 en el reto → 3 pares); no crece con el tiempo en este despliegue.
  - DOBLE CONTEO INTENCIONAL: spatial y stat_z son estrategias INDEPENDIENTES; una misma
    dislocación puede generar una opp de cada una (distinto `strategy`/`id`). El embudo cuenta
    ambas a propósito (STORY-022 lo desglosa por estrategia); no se deduplican.
"""
from __future__ import annotations

import math
import time
from collections import deque

import numpy as np

from ..config import Settings
from ..models.enums import OpportunityStatus, Strategy
from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity
from ..risk.watchdog import is_stale

# Pares de venues (clave ordenada lexicográficamente para que el spread sea estable).
_Pair = tuple[str, str]


def _mid(nb: NormalizedBook) -> float | None:
    """Mid normalizado = (best_bid + best_ask) / 2. None si el book no es operable."""
    bid, ask = nb.best_bid, nb.best_ask
    if bid is None or ask is None:
        return None
    mid = (bid + ask) / 2.0
    # Un book corrupto (NaN/inf) o no-positivo no admite ln: lo excluimos del cómputo.
    if not math.isfinite(mid) or mid <= 0.0:
        return None
    return mid


class StatZDetector:
    """Detector de arbitraje estadístico (C5). Mantiene una ventana rolling causal del
    spread log por par de venues y una máquina de estados `armed` por par. Sin red ni
    persistencia: determinista respecto a la secuencia de books que observa."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._windows: dict[_Pair, deque[float]] = {}
        # `armed=True`: el par está listo para disparar (vino de un régimen |z|<z_close o
        # es la primera vez que se llena la ventana). Ver máquina de estados en el módulo.
        self._armed: dict[_Pair, bool] = {}
        self._n = 0

    @staticmethod
    def _key(a: str, b: str) -> _Pair:
        return (a, b) if a < b else (b, a)

    def on_book(
        self, trigger: NormalizedBook, books: dict[str, NormalizedBook],
        *, now: float | None = None,
    ) -> list[Opportunity]:
        """Procesa la llegada de `trigger` (un book normalizado ya almacenado en `books`
        por el detector espacial C5, fuente única de los libros vivos). Genera una nueva
        observación del spread para CADA par que contiene al venue del trigger (su mid
        acaba de cambiar), corre la máquina de estados y devuelve las señales disparadas.

        `books` es el dict de libros vivos por venue (típicamente `SpatialDetector.books`):
        de ahí se leen los mids de la contraparte y su `ts_recv_monotonic` para staleness.

        `now` inyectable para el REPLAY (STORY-021): staleness contra el reloj de los ticks
        grabados (point-in-time). En vivo `now=None` → `time.monotonic()` (sin cambio).
        """
        t_detect = time.monotonic() if now is None else now
        trig_venue = trigger.exchange
        trig_mid = _mid(trigger)
        # Trigger sin mid operable o stale → no aporta observación (igual criterio que el
        # detector espacial: se computa contra `t_detect`, sin depender del watchdog).
        staleness_ms = self.settings.staleness_ms
        if trig_mid is None or is_stale(
            trigger.ts_recv_monotonic, t_detect, staleness_ms
        ):
            return []

        opps: list[Opportunity] = []
        for venue, nb in books.items():
            if venue == trig_venue:
                continue
            other_mid = _mid(nb)
            if other_mid is None or is_stale(
                nb.ts_recv_monotonic, t_detect, staleness_ms
            ):
                continue  # contraparte sin dato operable o stale → par excluido

            a, b = self._key(trig_venue, venue)
            mid_a = trig_mid if a == trig_venue else other_mid
            mid_b = trig_mid if b == trig_venue else other_mid
            spread = math.log(mid_b) - math.log(mid_a)

            window = self._windows.setdefault((a, b), deque(maxlen=self.settings.zscore_window))
            self._armed.setdefault((a, b), True)
            window.append(spread)

            signal = self._evaluate_pair((a, b), spread, trigger, t_detect)
            if signal is not None:
                opps.append(signal)
        return opps

    def _evaluate_pair(
        self,
        pair: _Pair,
        spread: float,
        trigger: NormalizedBook,
        t_detect: float,
    ) -> Opportunity | None:
        """Corre la máquina de estados armed→fire/stand-down→re-arm sobre el z actual del
        par y, si dispara, construye la `Opportunity(stat_z, detected)`. None si no dispara."""
        window = self._windows[pair]
        # Ventana causal incompleta → estimador inestable; no operamos (como pandas rolling(W),
        # que devuelve NaN hasta acumular W observaciones).
        if len(window) < self.settings.zscore_window:
            return None

        arr = np.fromiter(window, dtype=float, count=len(window))
        mean = float(arr.mean())
        std = float(arr.std())  # numpy: ddof=0 por defecto (población) == arquitectura D.2
        # std no finito o ~0 (spread degenerado/constante) → z indefinido: no hay señal.
        if not math.isfinite(std) or std <= 0.0:
            return None

        z = (spread - mean) / std
        if not math.isfinite(z):
            return None
        abs_z = abs(z)

        z_open = self.settings.z_open
        z_close = self.settings.z_close
        z_stop = self.settings.z_stop

        if not self._armed[pair]:
            # Desarmado: sólo se re-arma al volver cerca de la media (régimen normalizado).
            if abs_z < z_close:
                self._armed[pair] = True
            return None

        # Armado:
        if abs_z >= z_stop:
            # Relación rota (régimen quebrado): NO abrir. Se desarma; re-armado vía z_close.
            self._armed[pair] = False
            return None
        if abs_z < z_open:
            return None  # aún no es anómalo; sigue armado esperando el blow-out

        # Dispara: |z| en [z_open, z_stop). Una sola señal por blow-out (se desarma).
        self._armed[pair] = False
        a, b = pair
        if z > 0:        # mid_b caro relativo → vender en b, comprar en a
            buy_venue, sell_venue = a, b
        else:            # mid_a caro relativo → vender en a, comprar en b
            buy_venue, sell_venue = b, a

        self._n += 1
        return Opportunity(
            id=f"statz-{self._n}",
            strategy=Strategy.stat_z,
            symbol=trigger.symbol,
            buy_venue=buy_venue,
            sell_venue=sell_venue,
            q_target=self.settings.default_trade_qty_btc,
            z_score=z,
            status=OpportunityStatus.detected,
            t_recv=trigger.ts_recv_monotonic,
            t_detect=t_detect,
            latency_ms=(t_detect - trigger.ts_recv_monotonic) * 1000.0,
        )
