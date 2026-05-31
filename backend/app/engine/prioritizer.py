"""C7 — Priorización y ranking de oportunidades por score (FR-007, STORY-020).

Cuando un tick genera VARIAS oportunidades viables simultáneas (espacial + estadística,
varios pares de venues), el sistema no toma "la primera": las puntúa por un score ajustado
a riesgo y las ejecuta en orden descendente hasta agotar capital/inventario (el gate de
capital vive en `Portfolio.can_afford`, consultado por el motor en el orden que fija aquí).

SCORE (Apéndice D.4):

    score = E[neto] · P(fill) · factor_liquidez − penalización_riesgo

  · E[neto]  = `opp.net_pnl` (USD), el neto real ya calculado por el evaluador C6
               (walk-the-book VWAP, fee único, rebalanceo amortizado). Es la magnitud
               que dimensiona el score; los demás factores lo modulan en [0,1] o lo penalizan.
  · P(fill) ∈ [floor, 1] — probabilidad de llenar a precio esperado, derivada del HEADROOM
               de slippage: `1 − slip_rel/max_slippage`, con `slip_rel = slippage_usd/notional`.
               Una opp que apura el límite de slippage tiene menor P(fill); el `score_pfill_floor`
               evita anularla del todo. Las viables ya cumplen slippage ≤ max por leg (C6).
  · factor_liquidez ∈ (0,1] — `q_efectiva / q_objetivo`: qué fracción del tamaño deseado es
               realmente ejecutable por PROFUNDIDAD (AC#3: el tamaño se dimensiona por
               profundidad, no por capital total — la `q` efectiva la fija C6 como min de
               ambas patas). Más liquidez ejecutable ⇒ mayor score.
  · penalización_riesgo (USD) — proxy de la deriva adversa de precio durante la ventana de
               ejecución (leg risk): `(aversion_bps/1e4) · notional · latencia_seg`. Penaliza
               trades grandes y de mayor latencia. Unidades consistentes (USD) con el 1er término.

AC#2 ("descarta E[neto]≤0") lo aplica AGUAS ARRIBA el evaluador C6 (marca `discarded`
las no rentables); aquí se REFUERZA: una opp con `net_pnl` None/≤0/no-finito recibe score
−inf (queda al final del orden y nunca se prioriza para ejecución).

Determinista y puro: el score se computa SÓLO de los campos de la `Opportunity` (ya rellenos
por C6) + config; no necesita libros ni reloj. No muta el status; sólo escribe `opp.score`.
"""
from __future__ import annotations

import math

from ..config import Settings
from ..models.enums import OpportunityStatus
from ..models.opportunity import Opportunity

__all__ = ["Prioritizer"]

_NEG_INF = float("-inf")


class Prioritizer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def score(self, opp: Opportunity) -> float:
        """Score ajustado a riesgo de `opp`. −inf si no es elegible (E[neto] None/≤0/no-finito,
        refuerzo del filtro de viabilidad de C6). No muta `opp`."""
        net = opp.net_pnl
        if net is None or not math.isfinite(net) or net <= 0.0:
            return _NEG_INF

        q = opp.q_target if (opp.q_target and opp.q_target > 0.0) else 0.0
        # q no finita (NaN→0 arriba), nula o negativa = sin tamaño ejecutable → no elegible
        # (coherente con `can_afford`, que también rechaza q corrupta; evita un score 0.0 que
        # quedaría por delante de las descartadas en el orden).
        if q <= 0.0:
            return _NEG_INF
        vb = opp.vwap_buy
        vwap_buy = vb if (vb and math.isfinite(vb) and vb > 0.0) else 0.0
        vs = opp.vwap_sell
        vwap_sell = vs if (vs and math.isfinite(vs) and vs > 0.0) else 0.0
        notional_buy = q * vwap_buy            # capital comprometido en la pata de compra
        notional_pair = q * (vwap_buy + vwap_sell)  # ambas patas, para el slippage agregado

        # factor_liquidez: fracción del objetivo ejecutable por profundidad (cap 1.0).
        default_q = self.settings.default_trade_qty_btc
        liq = min(1.0, q / default_q) if default_q > 0.0 else 1.0

        # P(fill): headroom de slippage. `opp.slippage` es el impacto AGREGADO (USD) de AMBAS
        # patas (C6), así que se normaliza contra el notional de AMBAS patas → `slip_rel` es el
        # slippage relativo medio por pata, comparable con el `max_slippage` por-pata.
        max_slip = self.settings.max_slippage
        sl = opp.slippage
        slip_usd = sl if (sl is not None and math.isfinite(sl)) else 0.0
        slip_rel = (slip_usd / notional_pair) if notional_pair > 0.0 else 0.0
        p_fill = 1.0 - slip_rel / max_slip if max_slip > 0.0 else 1.0
        p_fill = min(1.0, max(self.settings.score_pfill_floor, p_fill))

        # penalización_riesgo (USD): deriva adversa proxy durante la ventana de latencia, sobre
        # el capital comprometido en la compra (proxy del leg risk de la ventana de ejecución).
        latency_s = max(0.0, self.settings.exec_latency_ms / 1000.0)
        penalty = (self.settings.score_risk_aversion_bps / 10_000.0) * notional_buy * latency_s

        return net * p_fill * liq - penalty

    def rank(self, opps: list[Opportunity]) -> list[Opportunity]:
        """Asigna `score` a las oportunidades VIABLES y devuelve TODAS reordenadas: viables por
        score descendente primero (las no rentables/no viables, con score −inf, al final). El
        orden de detección se preserva en empates (sort estable). El motor procesa en este
        orden, así el capital/inventario va a las de mayor score primero (AC#4)."""
        for o in opps:
            if o.status is OpportunityStatus.viable:
                o.score = self.score(o)

        def key(o: Opportunity) -> float:
            sc = o.score
            if o.status is OpportunityStatus.viable and sc is not None and math.isfinite(sc):
                return sc
            return _NEG_INF

        return sorted(opps, key=key, reverse=True)
