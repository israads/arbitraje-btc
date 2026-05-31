"""Capa 3 — Proyección FORWARD honesta (Monte Carlo + estadística de López de Prado).

Esto NO es un pronóstico de precio. Es la *dispersión* de resultados de P&L consistente con la
muestra histórica de trades, generada con un **stationary bootstrap** (Politis & Romano, 1994)
que preserva (en media) la autocorrelación de la serie sin imponer i.i.d. Sobre la muestra real
se calculan métricas de honestidad estadística:

  * PSR — Probabilistic Sharpe Ratio (Bailey & López de Prado, 2012).
  * DSR — Deflated Sharpe Ratio (Bailey & López de Prado, 2014) vía el *False Strategy Theorem*.
  * MinTRL — Minimum Track Record Length (Bailey & López de Prado, 2012).

Todo en numpy puro + ``math`` (CDF/inversa normales propias). Determinista vía
``np.random.default_rng(seed)``. Sin dependencias nuevas.

Referencias
-----------
* Politis, D.N. & Romano, J.P. (1994). "The Stationary Bootstrap". JASA 89(428), 1303-1313.
* Politis, D.N. & White, H. (2004). "Automatic Block-Length Selection for the Dependent
  Bootstrap". Econometric Reviews 23(1), 53-70.  (de aquí la heurística n^(1/3) para el bloque).
* Bailey, D.H. & López de Prado, M. (2012). "The Sharpe Ratio Efficient Frontier".
  Journal of Risk 15(2), 3-44.  (PSR y MinTRL).
* Bailey, D.H. & López de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for
  Selection Bias, Backtest Overfitting and Non-Normality". JPM 40(5), 94-107.  (DSR / FST).
* Acklam, P.J. (2003). "An algorithm for computing the inverse normal cumulative distribution
  function".  (aproximación racional de Φ⁻¹).
"""
from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

from app.models.projection import ForwardBands, ForwardResult

# Constante de Euler-Mascheroni (γ), usada por el False Strategy Theorem.
_EULER_GAMMA = 0.5772156649015329

# Honestidad: la frase canónica para el campo `notes`.
_HONESTY_NOTE = (
    "Esto NO es un pronóstico: es la dispersión de resultados consistente con la muestra "
    "histórica (stationary bootstrap, Politis-Romano 1994). Si la mediana o el P5 caen por "
    "debajo de 0, el edge no es defendible tras costes."
)


# ----------------------------------------------------------------------------------------
# Funciones estadísticas auxiliares (CDF normal e inversa) — numpy/math puro.
# ----------------------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    """Φ(x): CDF de la normal estándar vía math.erf (exacta hasta precisión de máquina)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Φ⁻¹(p): inversa de la CDF normal estándar.

    Aproximación racional de Acklam (2003): error relativo < 1.15e-9 en todo el dominio
    abierto (0, 1). Se recorta `p` al interior para evitar ±inf.
    """
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf

    # Coeficientes de Acklam.
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)

    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
           ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)


# ----------------------------------------------------------------------------------------
# Construcción principal.
# ----------------------------------------------------------------------------------------

def build_forward_projection(
    pnls: list[float],
    *,
    n_paths: int = 5000,
    n_configs: int = 1,
    horizon: int | None = None,
    ruin_threshold: float | None = None,
    seed: int = 12345,
) -> ForwardResult:
    """Construye la proyección forward a partir de la distribución empírica de P&L por trade.

    Parameters
    ----------
    pnls
        P&L (USD) realizado por trade. Puede venir vacía o con pocos elementos.
    n_paths
        Número de trayectorias Monte Carlo.
    n_configs
        Número K de configuraciones probadas (para el DSR / deflación por selección).
    horizon
        Longitud de cada trayectoria (nº de trades futuros simulados). Default = n_trades.
    ruin_threshold
        Umbral de ruina en USD (magnitud positiva). Si es ``None`` se usa un default
        documentado: ``|sum(pnls)|`` (ver más abajo). Una trayectoria "se arruina" si su
        equity acumulada toca ``-ruin_threshold`` en algún paso.
    seed
        Semilla del RNG (determinismo total).

    Returns
    -------
    ForwardResult
        Si la muestra es insuficiente (``n < 2`` o ``std == 0``) devuelve
        ``available=False`` sin lanzar excepción.
    """
    sample: npt.NDArray[np.float64] = np.asarray(pnls, dtype=np.float64)
    n_trades = int(sample.size)

    # 1) Guard: muestra insuficiente o degenerada (sin dispersión).
    if n_trades < 2 or float(np.std(sample, ddof=0)) == 0.0:
        return ForwardResult(
            available=False,
            n_trades=n_trades,
            notes=(
                "Muestra insuficiente para una proyección honesta (se requieren >=2 trades con "
                "dispersión no nula). " + _HONESTY_NOTE
            ),
        )

    rng = np.random.default_rng(seed)
    horizon_n = int(horizon) if horizon is not None else n_trades
    horizon_n = max(1, horizon_n)
    n_paths = max(1, int(n_paths))

    # 2) Stationary bootstrap (Politis-Romano 1994).
    # Longitud media de bloque por la heurística n^(1/3) (Politis-White 2004), acotada [2, n].
    block_mean = float(np.clip(round(n_trades ** (1.0 / 3.0)), 2, n_trades))
    p_restart = 1.0 / block_mean

    # Construcción vectorizada de la matriz de índices (n_paths, horizon).
    # En cada paso: con prob p_restart se elige un índice aleatorio nuevo; si no, se avanza
    # el bloque (índice anterior + 1, circular).
    idx = np.empty((n_paths, horizon_n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n_trades, size=n_paths)
    if horizon_n > 1:
        restarts = rng.random((n_paths, horizon_n - 1)) < p_restart
        fresh = rng.integers(0, n_trades, size=(n_paths, horizon_n - 1))
        for t in range(1, horizon_n):
            cont = (idx[:, t - 1] + 1) % n_trades
            r = restarts[:, t - 1]
            idx[:, t] = np.where(r, fresh[:, t - 1], cont)

    draws: npt.NDArray[np.float64] = sample[idx]            # (n_paths, horizon)
    equity: npt.NDArray[np.float64] = np.cumsum(draws, axis=1)  # equity acumulada desde 0

    # 3) Bandas (fan chart): percentiles transversales por paso.
    pct = np.percentile(equity, [5, 25, 50, 75, 95], axis=0)  # (5, horizon)

    # Submuestreo de pasos si el horizonte es grande (no inflar payload).
    if horizon_n > 200:
        step_idx = np.unique(np.linspace(0, horizon_n - 1, 150, dtype=np.int64))
    else:
        step_idx = np.arange(horizon_n, dtype=np.int64)

    bands = ForwardBands(
        step=[int(s) + 1 for s in step_idx],               # pasos 1..horizon
        p5=[float(v) for v in pct[0, step_idx]],
        p25=[float(v) for v in pct[1, step_idx]],
        p50=[float(v) for v in pct[2, step_idx]],
        p75=[float(v) for v in pct[3, step_idx]],
        p95=[float(v) for v in pct[4, step_idx]],
    )

    # 4) Terminal: distribución del P&L final (última columna).
    terminal: npt.NDArray[np.float64] = equity[:, -1]
    t_p5, t_p50, t_p95 = (float(v) for v in np.percentile(terminal, [5, 50, 95]))
    hist_counts, hist_edges = np.histogram(terminal, bins=20)

    # 5) Max drawdown por trayectoria (pico->valle de la equity, arrancando en 0).
    # Prefijo 0 para incluir el caso "nunca por encima del inicio".
    equity0: npt.NDArray[np.float64] = np.concatenate(
        [np.zeros((n_paths, 1), dtype=np.float64), equity], axis=1
    )
    running_max: npt.NDArray[np.float64] = np.maximum.accumulate(equity0, axis=1)
    drawdown: npt.NDArray[np.float64] = running_max - equity0   # >= 0 (magnitud de la caída)
    max_dd: npt.NDArray[np.float64] = drawdown.max(axis=1)      # por trayectoria, USD positivos
    dd_p50, dd_p95 = (float(v) for v in np.percentile(max_dd, [50, 95]))

    # 6) Probabilidades.
    prob_profit = float(np.mean(terminal > 0.0))
    # prob_ruin: una trayectoria se arruina si su mínimo acumulado cae por debajo de
    # -ruin_threshold. Default documentado: ruin_threshold = |sum(pnls)| (la "ganancia
    # histórica acumulada"); perder esa magnitud es una definición de ruina defendible y
    # simple. Si la suma histórica es ~0 se usa block_mean*std como piso para no degenerar.
    if ruin_threshold is None:
        default_thr = abs(float(np.sum(sample)))
        floor = block_mean * float(np.std(sample, ddof=1))
        thr = max(default_thr, floor)
    else:
        thr = abs(float(ruin_threshold))
    min_equity: npt.NDArray[np.float64] = equity.min(axis=1)
    prob_ruin = float(np.mean(min_equity < -thr))

    # 7) Honestidad estadística sobre la MUESTRA REAL (no las simulaciones).
    mean = float(np.mean(sample))
    std = float(np.std(sample, ddof=1))               # std muestral (n-1)
    sharpe = mean / std if std > 0.0 else None         # SR por trade, NO anualizado

    psr: float | None = None
    dsr: float | None = None
    min_trl: float | None = None

    if sharpe is not None:
        sr = sharpe
        n = n_trades
        # Momentos estandarizados de la muestra.
        z = (sample - mean) / std
        gamma3 = float(np.mean(z ** 3))               # skewness
        gamma4 = float(np.mean(z ** 4))               # kurtosis CRUDA (= exceso + 3)

        # Denominador común de PSR/DSR/MinTRL (varianza del estimador de SR, Mertens/BLdP):
        #   1 - γ3·SR + ((γ4 - 1)/4)·SR²
        denom_var = 1.0 - gamma3 * sr + ((gamma4 - 1.0) / 4.0) * (sr * sr)
        denom_var = max(denom_var, 1e-12)             # blindaje numérico
        denom = math.sqrt(denom_var)

        # PSR(SR*=0): Φ[ (SR - 0)·√(n-1) / denom ].
        psr = _norm_cdf((sr - 0.0) * math.sqrt(n - 1) / denom)

        # DSR: igual que PSR pero con SR0 = E[max SR] del False Strategy Theorem.
        if n_configs <= 1:
            dsr = psr                                  # sin selección múltiple, DSR = PSR
        else:
            big_n = float(n_configs)
            # V = varianza de los Sharpe entre trials. Sin los trials reales, se usa la
            # varianza del estimador de SR ≈ (1 + 0.5·SR²)/(n-1) (aproximación estándar).
            v_sr = (1.0 + 0.5 * sr * sr) / (n - 1)
            sqrt_v = math.sqrt(max(v_sr, 0.0))
            # SR0 = √V · [(1-γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e))].
            sr0 = sqrt_v * (
                (1.0 - _EULER_GAMMA) * _norm_ppf(1.0 - 1.0 / big_n)
                + _EULER_GAMMA * _norm_ppf(1.0 - 1.0 / (big_n * math.e))
            )
            dsr = _norm_cdf((sr - sr0) * math.sqrt(n - 1) / denom)

        # MinTRL: nº mínimo de trades para que SR sea significativo (>0) a 95%.
        # MinTRL = 1 + denom_var · (Z_α / (SR - SR0))²,  SR0 = 0.  None si SR <= 0.
        if sr > 0.0:
            z_alpha = _norm_ppf(0.95)                  # ≈ 1.645
            min_trl = 1.0 + denom_var * (z_alpha / sr) ** 2
        else:
            min_trl = None                            # edge no alcanzable

    return ForwardResult(
        available=True,
        n_trades=n_trades,
        n_paths=n_paths,
        block_mean=block_mean,
        bands=bands,
        terminal_p5=t_p5,
        terminal_p50=t_p50,
        terminal_p95=t_p95,
        terminal_hist=[int(c) for c in hist_counts],
        terminal_hist_edges=[float(e) for e in hist_edges],
        max_dd_p50=dd_p50,
        max_dd_p95=dd_p95,
        prob_profit=prob_profit,
        prob_ruin=prob_ruin,
        sharpe_per_trade=sharpe,
        psr=psr,
        dsr=dsr,
        min_trl=min_trl,
        n_configs=int(n_configs),
        notes=_HONESTY_NOTE,
    )
