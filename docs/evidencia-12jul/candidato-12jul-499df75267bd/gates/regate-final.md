# Re-gate final — candidato-12jul

- **Tag**: `candidato-12jul` → SHA `499df75267bd49ec5fd8f54e01e43ee3f03f30c3` (verificado con `git rev-list -n1 candidato-12jul`)
- **Fecha**: 2026-07-12T18:07-06:00 (America/Mexico_City)
- **Modo**: JURY · LOCAL (stack compose de producción en http://localhost:8090, `ARB_CONTROL_TOKEN=local-evidence-placeholder`)

## Resumen del re-gate (RF-007, ejecutado desde worktree detached del SHA)

| Gate | Resultado |
|---|---|
| Backend pytest + cov | 547 tests passed, cobertura **91.64%** (umbral 85%) |
| ruff | limpio (`All checks passed!`) — re-ejecutado en este paquete: `gates/ruff.log` |
| mypy | limpio, 104 archivos sin issues — re-ejecutado: `gates/mypy.log` |
| Frontend typecheck/lint/build (RO) | verdes; build read-only **sin token en el bundle** (verificado por búsqueda en `.next/`) |
| Compose producción | healthy; SQLite con PRAGMAs `journal_mode=wal` y `synchronous=2`; **persistencia verificada tras restart** del stack |

Los builds frontend NO se repiten en este paquete: quedaron validados en el re-gate sobre el
worktree limpio del SHA `499df75267bd` inmediatamente antes de crear el tag.

## Re-ejecución en este paquete (12-jul, árbol del repo en el mismo SHA)

- `gates/backend-pytest.log`: `uv run pytest -q --cov=app --cov-fail-under=85` — cobertura 91.64%.
  Nota: en la primera pasada, ejecutada en paralelo con el stack compose y Chrome headless,
  `tests/test_persistence.py::test_enqueue_many_does_not_block_event_loop` (assert de wall-clock
  <100 ms) falló por carga de CPU concurrente; la re-ejecución sin carga (log final) queda verde
  con 547 passed. Es sensibilidad de timing del entorno, no regresión de código.
- `gates/ruff.log`: exit 0.
- `gates/mypy.log`: exit 0.

## Versiones

Python 3.9.6 (host; backend corre bajo uv/py del proyecto) · uv 0.10.10 · Node v20.20.0 ·
npm 10.8.2 · Docker 29.5.2 · Docker Compose 5.3.1 · macOS 26.4
