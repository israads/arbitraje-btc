# Depth curve benchmark

PRD-007 agrega `DepthCurve` para evitar caminar el mismo libro muchas veces al barrer tamaños
en projection/capacity. El evaluador vivo sigue usando `walk_book`; la integración inicial está
acotada a proyecciones.

Comando:

```bash
make profile-engine
```

Último smoke local:

```text
ticks_processed_per_s=24606.75
evaluate_p50_ms=0.034208
evaluate_p95_ms=0.076000
evaluate_p99_ms=0.098791
walk_book_p95_ms=0.012833
depth_curve_p95_ms=0.000500
depth_curve_speedup_p95=25.67x
depth_curve_equivalence_max_abs_diff=0.000000000000
projection_demo_p95_ms=0.361292
capacity_demo_p95_ms=0.212875
```

Resultado: `DepthCurve.vwap(q)` reconcilia con `walk_book(levels, q)` y supera el criterio de
30% de mejora p95 en el microbenchmark sintético.
