"""Supervivencia del edge por latencia — `P_survive` + Expected Capturable Edge.

Una celda de la frontier dice "si ejecuto AHORA contra este snapshot". Pero entre detectar y
ejecutar pasa `exec_latency_ms`, y el precio se mueve. `P_survive` estima la probabilidad de que
el edge SIGA siendo positivo tras esa ventana, y el Expected Capturable Edge (ECE) pondera el neto
por esa probabilidad menos la pérdida esperada si falla (unwind del leg ya ejecutado).

Modelo (heurístico, interpretable, point-in-time — NO ML):
  El edge sobrevive si un movimiento adverso del precio durante la latencia no lo borra. Modelamos
  ese movimiento como gaussiano con desviación `σ·√(Δt)` (σ = volatilidad en USD/√s; Δt en s).
  La probabilidad de que el colchón `net_per_btc` no se agote es Φ(net_per_btc / (σ·√Δt)):

      P_survive = Φ( net_per_btc / (σ · √(latency_ms/1000)) )

  net_per_btc ≤ 0 ⇒ P_survive < 0.5 (correcto: el edge ya está al límite). σ→0 ⇒ P→1 (sin riesgo).
  Honesto y monótono: más edge ⇒ sobrevive más; más latencia o más volatilidad ⇒ sobrevive menos.

ECE = P_survive · net − (1 − P_survive) · expected_unwind_loss
  expected_unwind_loss ≈ coste de deshacer el intento fallido (fees del round-trip): conservador.
"""
from __future__ import annotations

import math

# σ por defecto (USD por √s) para BTC ~ $70k: una vol diaria del ~2% ≈ 1400 USD/día.
# σ/√s ≈ 1400 / √86400 ≈ 4.76 USD/√s. Redondeado a un valor representativo y configurable.
DEFAULT_SIGMA_USD_PER_SQRT_S = 5.0


def p_survive(
    net_per_btc: float,
    latency_ms: float,
    *,
    sigma_usd_per_sqrt_s: float = DEFAULT_SIGMA_USD_PER_SQRT_S,
) -> float:
    """Probabilidad ∈ [0,1] de que el edge (USD/BTC) sobreviva la ventana de latencia.

    Determinista. `latency_ms ≤ 0` o `sigma ≤ 0` ⇒ sin riesgo de deriva ⇒ 1.0 si el edge es
    positivo, 0.0 si es negativo (límite degenerado coherente con Φ)."""
    if not math.isfinite(net_per_btc):
        return 0.0
    dt_s = max(latency_ms, 0.0) / 1000.0
    scale = sigma_usd_per_sqrt_s * math.sqrt(dt_s)
    if scale <= 0.0:
        return 1.0 if net_per_btc > 0.0 else 0.0
    # Φ(x) = 0.5·(1 + erf(x/√2))
    return 0.5 * (1.0 + math.erf(net_per_btc / (scale * math.sqrt(2.0))))


def expected_capturable_edge(
    net_usd: float,
    net_per_btc: float,
    fees_usd: float,
    latency_ms: float,
    *,
    sigma_usd_per_sqrt_s: float = DEFAULT_SIGMA_USD_PER_SQRT_S,
) -> tuple[float, float]:
    """Devuelve `(p_survive, expected_capturable_edge_usd)` para una celda.

    `expected_unwind_loss` se aproxima al coste de deshacer un intento fallido = `fees_usd`
    (round-trip taker), conservador. ECE = p·net − (1−p)·unwind_loss."""
    p = p_survive(net_per_btc, latency_ms, sigma_usd_per_sqrt_s=sigma_usd_per_sqrt_s)
    expected_unwind_loss = max(fees_usd, 0.0)
    ece = p * net_usd - (1.0 - p) * expected_unwind_loss
    return p, ece
