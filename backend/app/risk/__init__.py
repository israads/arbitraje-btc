"""C8 — Gestión de riesgo: watchdog de staleness + circuit breakers + kill switch.

Watchdog marca venue stale (`now_monotonic − ts_recv > umbral`) y lo excluye;
breakers de volatilidad, inventario sesgado y drawdown; kill switch manual. El
motor/simulador consultan el estado antes de operar. FR-002, FR-012.

Implementación: STORY-014 (watchdog), STORY-018 (breakers + kill switch).
"""
