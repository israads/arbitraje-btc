# Smoke read-only — candidato-12jul (JURY · LOCAL)

- Tag `candidato-12jul` · SHA `499df75267bd49ec5fd8f54e01e43ee3f03f30c3`
- Fecha: 2026-07-12T18:07-06:00 · Stack compose producción en http://localhost:8090
- Modo demo: `jury` activo (`api/demo.json`)

## Verificado por el orquestador (sesión de smoke previa, mismo stack/SHA)

| # | Check | Resultado |
|---:|---|---|
| 1 | Kill-switch POST sin token | **401** PASS |
| 2 | Kill-switch POST con token válido | **200** PASS |
| 3 | Kill-switch POST con token no-ASCII (`X-Control-Token` con `ó`/`ñ`) | **401** (nunca 500) PASS |
| 4 | `GET /api/v1/session/export` | **200**, JSON parseable PASS |
| 5 | Badge **READ-ONLY DEMO** visible en el header del dashboard | PASS |
| 6 | Escenario adverso: `esperado` vs `observado` con delta observado en vivo, mismo `scenario_run_id` | PASS |
| 7 | Controles de escritura deshabilitados con tooltip explicativo en modo read-only | PASS |

## Re-ejecutado por curl al ensamblar este paquete (2026-07-12T18:0x-06:00)

| Check | Comando | Esperado | Observado |
|---|---|---|---|
| Kill-switch sin token | `curl -X POST /api/v1/control/kill-switch` | 401 | **401** PASS |
| Kill-switch token no-ASCII | `-H 'X-Control-Token: tóken-ñ'` | 401 | **401** PASS |
| Export | `GET /api/v1/session/export` | 200 | **200** PASS |
| Health | `GET /health` | `status=ok` | **ok** PASS |
| Demo | `GET /api/v1/demo` | `mode=jury` | **jury**, `scenario=peg_adverse`, `scenario_run_id=1521` PASS |
| Validation | `GET /api/v1/validation` | `computed=109.75`, `abs(diff)<=0.0001` | **computed=109.75, diff=0.0** PASS |
| Export sin secretos | búsqueda de token y claves `control_token/api_key/secret/password` | 0 ocurrencias | **0 ocurrencias** PASS |

El check 2 (200 con token válido) no se re-ejecutó al ensamblar para no mutar el estado del
stack vivo; queda cubierto por la verificación del orquestador arriba.
