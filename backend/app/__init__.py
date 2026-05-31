"""arbitraje-btc backend — monolito modular asíncrono (1 proceso, 1 event loop).

Pipeline: ingesta (C1) → integridad (C2) → normalización+peg (C3) → bus (C4)
→ motor detección/neto/ranking (C5/C6/C7) → simulador+inventario (C9/C10)
→ {hub SSE (C11)} + {persistencia (C12)}. Transversales: riesgo/breakers (C8),
métricas (C13), backtest (C14), validación (C15), fallback demo (C16), config (C17).
"""

__version__ = "0.1.0"
