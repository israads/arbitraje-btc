# PRD-007: Rendimiento y curvas de profundidad

Estado: Implementado  
Prioridad: P2  
Área: Engine, Proyección, Profiling  
Dependencias: PRD-001 ayuda a medir payloads
Arquitectura: [docs/architecture/007-performance-depth-curves.md](../architecture/007-performance-depth-curves.md)

## Problema

El motor camina libros para evaluar oportunidades y proyecciones. Para BTC y pocos venues es correcto, pero si se agregan más tamaños, más símbolos o más estrategias, recalcular VWAP desde cero se vuelve costo repetido.

## Objetivo

Reducir costo de cálculo de VWAP y proyecciones sin cambiar resultados económicos.

## No objetivos

- No reescribir en Rust antes de perfilar.
- No sacrificar claridad.
- No cambiar fórmulas financieras.

## Requisitos funcionales

### RF-001 Profiling reproducible

Agregar comando o script:

```bash
make profile-engine
```

Debe medir:

- ticks procesados por segundo.
- tiempo p50/p95/p99 de `evaluate`.
- tiempo de `walk_book`.
- tiempo de `projection`.
- serialización SSE/API si aplica.

### RF-002 Curvas acumuladas de profundidad

Crear estructura:

```python
DepthCurve(
    prices: list[float],
    qty_cum: list[float],
    notional_cum: list[float],
    side: "bid" | "ask"
)
```

Debe permitir:

```python
vwap, filled = curve.vwap(q)
```

en O(log n) u O(1) amortizado por tamaño ordenado, en vez de caminar todos los niveles cada vez.

### RF-003 Compatibilidad

`walk_book(levels, q)` sigue existiendo y sus tests pasan. `DepthCurve.vwap(q)` debe reconciliar con `walk_book`.

### RF-004 Uso gradual

Fase 1:

- Usar `DepthCurve` en proyección/capacity, donde hay muchos tamaños.

Fase 2:

- Usar en evaluator si profiling lo justifica.

## Cambios técnicos

Archivos:

- `backend/app/engine/bookmath.py`
- `backend/app/projection/frontier.py`
- `backend/app/projection/capacity.py`

Crear:

- `backend/app/engine/depth_curve.py`
- `backend/tests/test_depth_curve.py`
- `scripts/profile_engine.py` o equivalente.

## Plan de implementación

1. Crear benchmarks simples con books sintéticos.
2. Implementar `DepthCurve`.
3. Probar igualdad contra `walk_book`.
4. Integrar en projection.
5. Medir antes/después.
6. Decidir si conviene integrar en evaluator.

## Pruebas

- `test_depth_curve_matches_walk_book_exact_fill`
- `test_depth_curve_matches_walk_book_partial_fill`
- `test_depth_curve_empty_book`
- `test_depth_curve_unsorted_rejected_or_normalized`
- `test_projection_results_do_not_change_with_depth_curve`

## Criterios de aceptación

- Resultados numéricos iguales dentro de tolerancia.
- Projection/capacity reducen tiempo p95 al menos 30% en books sintéticos grandes.
- No se degrada legibilidad del evaluator.
- No se introduce dependencia compilada.

## Riesgos

- Bugs por parcial dentro de nivel. Mitigación: tests exhaustivos contra `walk_book`.
- Optimización prematura. Mitigación: integrar primero donde hay multiplicación clara de tamaños.
- Diferencias floating point. Mitigación: tolerancias explícitas y tests de invariantes.
