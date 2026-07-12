# Pipeline nocturno 11→12 jul — estado de ejecución

> Fuente de verdad del trabajo autónomo nocturno. Actualizar tras cada fase.
> Decisiones del usuario (confirmadas 11-jul ~21h):
> - Codex CLI en `--sandbox workspace-write` para revisiones.
> - Publicar = commit + push a rama `entrega-12jul` (main intacto).
> - Deploy al server kavasoft: **solo preparación** (bloque 0b + validación local); el deploy real lo hace el usuario mañana.
> - Bypass permissions activo toda la noche.

## Dinámica de revisión (por documento y por tarea de código)

1. Revisión Codex (`codex exec --sandbox workspace-write`) — mejora directa del documento/código.
2. Espera 5 min (`sleep 300` en background).
3. Revisión Claude (yo mismo, con agente si aplica).
4. Espera 5 min.
5. Revisión Codex final.
6. Espera 5 min antes de la siguiente unidad.

## Fases

| Fase | Contenido | Estado |
|---|---|---|
| 0. Checkpoint | rama `entrega-12jul`, manifiesto 45 archivos, backup DB en scratchpad, push | ✅ commit 98d4937 |
| A. PRDs 009-015 | borradores (4 agentes paralelos) → ciclo de revisión por PRD | ✅ 7/7 cerrados |
| B. Arquitectura | docs/architecture/009-cierre-12jul.md consolidada → ciclo Codex/Claude/Codex | ✅ commit d39f4c2 |
| C. Código | 8 partes según arquitectura §4; tracking en task list de la sesión | 🔄 Parte 1 en curso |

> Resuelto 22:2x — `colima start` OK (daemon 29.2.1) + `brew install docker-compose` enlazado como
> plugin CLI (`docker compose` 5.3.1). GATE-COMPOSE ejecutable esta noche; PRD-011/015 desbloqueados.
| D. Integración | suite completa, smoke navegador Chrome, demo, evidencia | ⬜ |

## Mapa PRD → bloques del plan (`docs/plan-accion-final-12jul.md`)

| PRD | Bloques | Título |
|---|---|---|
| 009 | 1 | Atomicidad ledger + venues (P0, NUNCA cortar) |
| 010 | 2 auth | Superficie read-only + auth |
| 011 | 0b, 2 deploy, 2b, 7-prep | Deploy reproducible y persistente (SIN deploy real) |
| 012 | 4 | Panel Inventario & Rebalanceo + fix ts=0.0 |
| 013 | 5 | Escenarios esperado→observado |
| 014 | 6 | Narrativa visual honesta |
| 015 | 0/3/8 + P2 | Release, suite, evidencia |

## Orden de implementación de código (fase C)

009 → 010 → 011 → 012 → 013 → 014 → 015. Tras cada tarea N: verificar que 1..N siguen verdes
(suite backend + typecheck/build frontend). Commit + push por parte terminada.

## Registro fase C

- Parte 1 (PRD-009): ✅ CERRADA — commit 128e8e7. Ciclo Codex(APROBADO)→Claude(tests endurecidos)→Codex(APROBADO). Gate 1 verde: 527 tests, 91.46%, ruff/mypy/frontend limpios.
- Parte 2 (PRD-010): implementada verde (ambos builds, badge en bundle prerender, 9 acciones cubiertas + excepción what-if RF-004). Ciclo de revisión en curso.

## Registro

- 21:0x — Bloque 0 ejecutado: rama, manifiesto (45 archivos, +4852), push. `agents/` excluido vía `.git/info/exclude` (tooling local con node_modules). Backup DB → scratchpad/arbitraje.db.bak-12jul.
- 21:0x — Codex verificado (read-only OK). Chrome MCP verificado (tab group creado).
- 21:0x — 4 agentes paralelos redactando PRDs 009-015.
- 21:1x — Borradores de los 7 PRDs completos (009-015 en docs/prd/). Hallazgos de redacción: bug ts=0.0 vive en rebalancer.py:46; GET /demo ya expone expected_result (fallback.py:161-185); Dockerfile.frontend sin ARG read-only hoy; health.py:88-91 solo degrada con failed.
- 21:1x — Revisiones Codex #1 lanzadas en paralelo para los 7 PRDs (workspace-write, logs en scratchpad/codex-prdNNN-r1.log).
- 21:3x — Codex #1 completado en los 7 PRDs. Revisiones Claude completadas: 009 (gate test 4 dividido en 4a/4b, forma JSON del 409, tests mapeados a test_inventory.py + test_config_api.py nuevo), 010 (lib/config.ts como mecanismo READ_ONLY, matriz de mutaciones completa, comandos literales de gate), 011 (compose canónico = deploy/standalone/, 7+1 tasks esperadas en health, targets §13 confirmados patch/minor), 012 (fix ts vía parámetro epoch, panel va primero en tab Operación, gotcha keepMounted), 014 (contratos verificados, $109.75 vive en EdgeWaterfall.tsx:85-92, veredicto desde engine.trades).
- ⚠️ OPERATIVO: docker CLI 29.5.2 presente pero plugin compose AUSENTE y daemon colima APAGADO. Intentar `colima start` en fase C; si no arranca, los gates Docker quedan documentados como pre-deploy de mañana.
- 22:0x — Ciclos completos cerrados: PRD-014 (APROBADO sin cambios), PRD-010 (CORREGIDO: conteo emisores fetch, gate bash con exit code real), PRD-012 (CORREGIDO: usd number|null, t_recv/t_detect monotónicos sin formato fecha). Decisiones clave fijadas: PRD-013 default = reformular badge order_failure (harness stretch); PRD-015 tag = candidato-12jul, evidencia en docs/evidencia-12jul/<tag>-<sha12>/.
