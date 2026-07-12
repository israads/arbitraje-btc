# PRD-015: Release desde commit autocontenido + paquete de evidencia

Estado: Propuesto  
Prioridad: P0 (cierre 12-jul, Bloques 3 y 8) + P2 selectivo condicionado  
Área: Release engineering, QA, Documentación  
Dependencias: Bloques 0-2 cerrados; PRD-009..PRD-014 integrados antes del gate final  
Plan: [docs/plan-accion-final-12jul.md](../plan-accion-final-12jul.md) Bloques 0, 3 y 8; §7 P2; §9 guion; §12 Plan B; riesgos R11 y R13  
Timebox: Bloque 3 = 45 min; Bloque 8 = 1 h; cada ítem P2 conserva el timebox de §7.

> Adaptación obligatoria: **esta noche no hay server público**. No se ejecutan Bloques 0b ni 7,
> ni `ssh`, `rsync` o comandos contra la IP pública. El Bloque 8 se ejecuta exclusivamente contra
> el stack local determinista levantado desde el tag candidato. El Plan B de §12 es la ruta
> principal de demo, no una contingencia. Esta restricción no reduce ningún gate de correctitud,
> reproducibilidad o evidencia.

## Problema

La base local está verde, pero eso no demuestra que el release sea autocontenido ni que la
evidencia corresponda al mismo código:

1. **R11:** los archivos runtime ya entraron al checkpoint `98d4937` de la rama `entrega-12jul`.
   Los PRD-009..PRD-015 y los docs de ejecución entran con los commits incrementales del pipeline
   nocturno (un commit por parte). El riesgo restante no es decidir qué incluir al final, sino
   probar que el HEAD final construye desde un worktree detached limpio, sin que ningún archivo
   local suelto participe por accidente.
2. El Bloque 3 del plan ocurre antes de cambios de los Bloques 4-6 y del P2. Por tanto, su suite es
   un gate preliminar: después de cualquier cambio posterior debe repetirse la suite completa y
   solo entonces se crea el tag.
3. **R13:** los cambios UX no tienen tests frontend/E2E; la evidencia exige un smoke manual
   dirigido en desktop y 360 px sobre el build final.
4. Capturas, export, reconciliación, audits y logs deben identificar commit, fecha, modo y comando;
   una salida verde sin esa trazabilidad no es evidencia de release.
5. En la máquina revisada `docker` existe, pero el plugin `docker compose` no está instalado. El
   gate Docker queda bloqueado hasta instalar/habilitar Compose; no se sustituye por una afirmación
   documental ni obliga a desplegar fuera de local.

## Objetivo

Producir un tag candidato inmutable, creado desde un commit autocontenido que pase todos los gates
en un worktree limpio, y un paquete de evidencia íntegro y reproducible generado exclusivamente
desde ese tag contra el stack local en modo jury determinista.

## No objetivos

- No desplegar ni probar contra un server público esta noche.
- No añadir features, estrategias, dependencias mayores ni migrar Next (excepción de §13).
- No montar Playwright/Vitest hoy: el smoke frontend es manual y dirigido (§14).
- No ejecutar P2 mientras exista un gate P0/local en rojo.
- No mover, sobrescribir ni reutilizar un tag que ya haya identificado un candidato rechazado.

## Usuario

- Jurado que recibe el paquete y debe poder reproducir cada afirmación.
- Operador de la demo local y del checklist pre-demo del 12-jul.
- Ingeniero que debe distinguir con rapidez un gate aprobado, fallido o no ejecutado.

## Estado actual (verificado 11-jul-2026, rama `entrega-12jul`, `HEAD=98d493702b46`)

| Área | Estado verificado |
|---|---|
| Suite backend | Ejecutada desde `backend/`: 507 passed, 91.03%, ruff y mypy strict limpios |
| Suite frontend | Ejecutada desde `frontend/`: typecheck/lint/build limpios; First Load JS 263 kB |
| Runtime de R11 | `.dockerignore`, test de robustez, error boundaries y `BusinessThesisCard.tsx` están tracked en `98d4937` |
| Worktree | PRD-009..PRD-015 y `docs/execution/pipeline-nocturno-12jul.md` aún untracked; entran con los commits incrementales del pipeline (un commit por parte), no con staging masivo al final |
| Compose | Existen `deploy/docker-compose.yml` (solo backend) y `deploy/standalone/docker-compose.yml` (backend/frontend/nginx); `docker compose` no está disponible en esta máquina |
| Tag candidato | No existe un tag cuyo nombre contenga `candidat` |
| Evidencia visual | `assets/dashboard.png` no acredita fecha/commit/modo del release final |
| Docs | `documentos/ultima_fase_claude.md:24` conserva la cifra histórica de 481 tests |
| Guion | `docs/guion-demo-jurado.md:43` y `backend/app/demo/scenarios.py:66` dicen cinco escenarios; el código construye siete |
| Auth P2 | `backend/app/api/security.py:58-60` y `backend/app/api/v1/router.py:95-96` comparan strings con `hmac.compare_digest`; un header no-ASCII puede provocar 500 |
| Strategy Lab P2 | Reset aplica defaults localmente en `StrategyLabPanel.tsx:59-70`; el botón `:146-155` no comunica alcance/persistencia |
| Locale P2 | Seis números sin locale: `OpportunitiesTable.tsx:85,125,127` y `FunnelPanel.tsx:74,89,130`; `WinsPanel.tsx:20` sí fija la hora a `es-MX` |
| SSE P2 diferido | 503 queda como reconexión en `useStream.ts:547-548`; `retryHeavy` puede coincidir con el poll en `:513-516,700-705` |

Las líneas anteriores fueron verificadas contra `98d493702b46` y **re-verificadas en esta
revisión** (11-jul, árbol de trabajo): las seis referencias P2 de RF-006 siguen vigentes. Al
cambiar código, la evidencia final debe citar además el símbolo o fragmento, porque el número de
línea puede desplazarse tras los commits del pipeline.

## Requisitos funcionales

### RF-001 HEAD autocontenido en `entrega-12jul` (Bloques 0 y 3)

La rama `entrega-12jul` ya existe con el checkpoint `98d4937` y los PRD-009..PRD-014 se
implementan esta noche con **commits incrementales por parte** sobre esa rama. No hay commit
preliminar separado ni staging masivo de cierre: **el candidato es el HEAD final de la rama tras
el re-gate de RF-007**.

- Cada parte del pipeline cierra con su propio commit, que incluye su PRD/doc de ejecución; al
  cerrar cada parte, `git status --porcelain` queda vacío. Ningún archivo queda “pendiente por
  accidente”. No usar `git add .` ni `git commit -am` como sustituto de la revisión por parte.
- Confirmar con `git ls-files --error-unmatch` que estos runtime siguen tracked (lo están desde
  `98d4937`): `.dockerignore`, `backend/tests/test_robustness_edges.py`, `frontend/app/error.tsx`,
  `frontend/app/global-error.tsx` y `frontend/components/BusinessThesisCard.tsx`.
- Los gates RF-002..RF-004 no se ejecutan desde el árbol de trabajo: se abre un worktree detached
  del HEAD a verificar y ahí `git status --porcelain` debe producir cero líneas.

Ejemplo desde la raíz del repo:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
SHA=$(git rev-parse entrega-12jul)
WT="$(dirname "$REPO_ROOT")/coding_challenge-release-${SHA:0:12}"
git worktree add --detach "$WT" "$SHA"
test -z "$(git -C "$WT" status --porcelain)"
```

### RF-002 Gate backend desde el commit

`backend/pyproject.toml` define pytest, ruff y mypy en el grupo `dev`; los comandos se ejecutan
desde `backend/`, no desde la raíz:

```bash
cd "$WT/backend"
uv sync --frozen
uv run ruff check .
uv run mypy app
uv run pytest -q --cov=app --cov-fail-under=85
```

Salida mínima: ruff sin hallazgos, mypy sin errores, cobertura ≥85% y **más de 507 tests passed**
después de integrar las regresiones obligatorias de atomicidad. No se aceptan tests failed/error;
un warning conocido se registra, no se oculta.

### RF-003 Gate frontend desde el commit

`frontend/package.json` expone exactamente `typecheck`, `lint` y `build`; el lockfile es
`frontend/package-lock.json`:

```bash
cd "$WT/frontend"
npm ci
npm run typecheck
npm run lint
npm run build
```

Cada comando debe terminar con exit code 0. El reporte conserva tamaños de ruta y First Load JS
como observación; un cambio de tamaño no reemplaza el gate funcional.

### RF-004 Gate Compose local y reproducibilidad de imágenes

El stack con los tres servicios está en `deploy/standalone/docker-compose.yml`; el compose de
`deploy/` solo construye backend. Desde la raíz del worktree:

```bash
cd "$WT"
docker compose version
ARB_CONTROL_TOKEN=local-evidence-placeholder \
  docker compose -f deploy/standalone/docker-compose.yml config --quiet
ARB_CONTROL_TOKEN=local-evidence-placeholder \
  docker compose -f deploy/standalone/docker-compose.yml build --no-cache backend frontend
```

- Si `docker compose version` falla, RF-004 queda **NO EJECUTADO/BLOQUEADO** y se detiene el
  release. En el entorno revisado falla actualmente; instalar/habilitar Compose es prerrequisito.
- `config --quiet` debe terminar 0 con un token temporal no secreto; el valor no entra a git ni al
  paquete.
- Tras integrar PRD-011, el backend debe instalar desde `backend/uv.lock` con `uv sync --frozen`,
  y la configuración renderizada debe contener volumen `/data`, `ARB_DB_URL` y healthcheck.
- No usar caché para esta prueba. El stack, si se levanta para un smoke adicional, se accede solo
  por `localhost`; no se copia ni se despliega a otro host.

### RF-005 Política ante gates fallidos

- **Antes del tag:** detener la secuencia en el primer exit code distinto de 0; guardar el log bajo
  `docs/evidencia-12jul/failed/<sha12>/`, corregir en un commit nuevo, crear un worktree del nuevo SHA y repetir
  RF-001..RF-004 completos. No continuar con evidencia ni P2 en rojo.
- **P2 excede timebox o falla:** abandonar únicamente ese ítem, retirar su cambio parcial de forma
  segura, anotar `ABANDONADO` con causa y conservar el último SHA verde.
- **Después del tag:** marcar ese tag `RECHAZADO` en el manifiesto; no moverlo. Cualquier fix exige
  nuevo commit, suite completa y un tag nuevo.
- Un reintento verde no borra el log rojo: ambos quedan con SHA, hora, comando y exit code.

### RF-006 P2 selectivo antes del gate final

Solo es elegible cuando RF-001..RF-004 y el smoke preliminar local están verdes. Para este gate,
“smoke preliminar” significa: backend/frontend arrancan desde el SHA en loopback; `/health`
reporta `status=ok`; activar jury responde 200; `/validation` cumple el `jq` de RF-008; el export
es JSON parseable; y la UI carga Resumen/Correctitud en desktop y 360 px sin error bloqueante. Se
ejecuta antes del tag para evitar “mover” candidatos:

| # | Ítem seleccionado | Evidencia verificada en `98d493702b46` | Timebox | Re-gate inmediato |
|---:|---|---|---:|---|
| 1 | Actualizar cifras históricas 481 → base final real | `documentos/ultima_fase_claude.md:24` y badges si aplican | 10 min | búsqueda global de cifras |
| 2 | Corregir cinco → siete escenarios (`latency_decay`, `order_failure`) | `docs/guion-demo-jurado.md:43`; `backend/app/demo/scenarios.py:66` | 15 min | tests de demo + ruff |
| 3 | Headers no-ASCII devuelven 401, nunca 500, en ambas protecciones | `backend/app/api/security.py:58-60`; `backend/app/api/v1/router.py:95-96` | 20 min | tests auth + backend completo |
| 4 | Reset comunica explícitamente “local/no persiste” | `frontend/components/StrategyLabPanel.tsx:59-70,146-155` | 20 min | typecheck + lint + build |
| 5 | Fijar locale numérico coherente y mantener hora explícita | `OpportunitiesTable.tsx:85,125,127`; `FunnelPanel.tsx:74,89,130`; `WinsPanel.tsx:20` | 30 min | typecheck + lint + build |

Las cinco filas fueron re-verificadas en esta revisión contra el árbol de trabajo: cada
referencia archivo:línea sigue vigente y cada ítem sigue siendo un cambio de <45 min con su
re-gate incluido. El test del ítem 3 cubre `X-API-Key` (middleware, `security.py:58-61`) y
`X-Control-Token` (dependency, `router.py:95-96`) con caracteres no-ASCII y exige 401 en ambos
casos. En locale, `WinsPanel.tsx:20` no es un séptimo `toLocaleString()` suelto: es el contraste
de hora `es-MX` que motivó la inconsistencia.

P2 verificado pero diferido por esta entrega: cap SSE en `router.py:363-367`/`stream/hub.py`;
cliente ante 503 en `useStream.ts:547-548`; y duplicación de pesados entre `retryHeavy` y el poll
en `useStream.ts:513-516,700-705`. Los demás ítems de §7 también quedan post-entrega. Diferido no
significa aprobado: se registra como riesgo conocido.

### RF-007 Re-gate final y tag candidato inmutable

Después de Bloques 4-6, PRD-009..PRD-014 y todo P2 aceptado:

1. El candidato es el HEAD final de `entrega-12jul` tras el último commit del pipeline y el P2
   aceptado. Abrir un worktree detached nuevo de ese HEAD; reasignar `SHA` y `WT`.
2. Repetir RF-002, RF-003 y RF-004 completos, aunque el re-gate inmediato del P2 haya pasado.
3. Ejecutar el smoke preliminar definido en RF-006 sobre el SHA final, sin capturas definitivas.
4. Solo con todo verde crear el tag anotado **`candidato-12jul`**:
   `git tag -a candidato-12jul -m "Candidato 12-jul: gates verdes desde worktree limpio" "$SHA"`.
5. Registrar y comprobar que `git rev-list -n1 candidato-12jul` es exactamente el SHA probado.

Regla del plan ([docs/plan-accion-final-12jul.md](../plan-accion-final-12jul.md):32): **ningún tag
se llama `candidato` hasta construir y probar exclusivamente desde ese commit**; por eso el tag se
crea después de los gates y el smoke sobre el SHA final, nunca antes ni sobre el HEAD intermedio
del Bloque 3. Si P2 o el smoke invalidan el tag, no se mueve: el siguiente candidato se llama
`candidato-12jul.2`, `candidato-12jul.3`, etc., tras corregir y re-gatear.

### RF-008 Paquete de evidencia contra stack local (Bloque 8 + §9 + §12)

El paquete vive en el repo principal bajo `docs/evidencia-12jul/` (no en el worktree del tag, que
permanece limpio) y se commitea **después** del tag como commit de evidencia; el tag no se mueve:

```bash
TAG=candidato-12jul
SHA=$(git rev-list -n1 "$TAG")
EVIDENCE_DIR="$REPO_ROOT/docs/evidencia-12jul/${TAG}-${SHA:0:12}"
mkdir -p "$EVIDENCE_DIR"/{gates,audits,api,captures,smoke}
```

Todo archivo incluye SHA, tag, fecha ISO-8601, zona horaria, modo `jury`, comando y exit code en
`manifest.md`. Los logs de gates se capturan con `set -o pipefail` y `tee` — p. ej.
`uv run pytest -q --cov=app --cov-fail-under=85 2>&1 | tee "$EVIDENCE_DIR/gates/backend-pytest.log"`
— no basta una captura de terminal sin comando.

Audits verificados contra los gestores reales del repo:

```bash
cd "$WT/backend"
uv export --frozen --no-dev --no-emit-project --no-hashes \
  -o "$EVIDENCE_DIR/audits/backend-runtime-requirements.txt"
pip-audit -r "$EVIDENCE_DIR/audits/backend-runtime-requirements.txt" \
  --no-deps --disable-pip --progress-spinner off

cd "$WT/frontend"
npm audit --omit=dev
```

`pip-audit` es una herramienta externa y no está declarada en `backend/pyproject.toml`; su versión
se registra en el manifiesto. Un audit con hallazgos puede salir no-cero: se conserva ese exit code
y se adjunta la decisión de §13 con vulnerabilidad, impacto, mitigación, responsable y fecha. No se
ejecuta `npm audit fix --force`.

Para la evidencia funcional, levantar **desde el worktree del tag** el backend y el build de
frontend solo en loopback. Este bloque deja ambos procesos en background, conserva sus logs y los
detiene al salir del shell:

```bash
export ARB_CONTROL_TOKEN="$(openssl rand -hex 24)"

(
  set -e
  cd "$WT/backend"
  exec env ARB_ENV=prod ARB_CONTROL_TOKEN="$ARB_CONTROL_TOKEN" \
    ARB_DB_URL="sqlite+aiosqlite:///$EVIDENCE_DIR/api/evidence.db" \
    uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
) > "$EVIDENCE_DIR/gates/backend-runtime.log" 2>&1 &
BACKEND_PID=$!

(
  set -e
  cd "$WT/frontend"
  NEXT_PUBLIC_READ_ONLY=1 NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run build
  exec npm run start -- -H 127.0.0.1 -p 3000
) > "$EVIDENCE_DIR/gates/frontend-runtime.log" 2>&1 &
FRONTEND_PID=$!
trap 'kill "$FRONTEND_PID" "$BACKEND_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  curl -fsS http://127.0.0.1:8000/health >/dev/null && break
  sleep 1
done
curl -fsS http://127.0.0.1:8000/health | jq -e '.status == "ok"'

for _ in $(seq 1 120); do
  curl -fsS http://localhost:3000/ >/dev/null && break
  sleep 1
done
curl -fsS http://localhost:3000/ >/dev/null
```

Abrir únicamente `http://localhost:3000`. Preactivar jury y guardar las respuestas:

```bash
curl -fsS -X POST 'http://127.0.0.1:8000/api/v1/demo?mode=jury' \
  -H "X-Control-Token: $ARB_CONTROL_TOKEN" > "$EVIDENCE_DIR/api/jury.json"
curl -fsS 'http://127.0.0.1:8000/api/v1/validation' \
  > "$EVIDENCE_DIR/api/validation.json"
jq -e '.all_passed == true and .reconciliation.diff >= -0.0001 and
  .reconciliation.diff <= 0.0001 and .reconciliation.target == 109.75 and
  .reconciliation.computed == 109.75 and ([.invariants[].passed] | all)' \
  "$EVIDENCE_DIR/api/validation.json"

for _ in $(seq 1 60); do
  curl -fsS 'http://127.0.0.1:8000/api/v1/session/export' \
    > "$EVIDENCE_DIR/api/session-export.tmp.json"
  jq -e '
    ([.opportunities[] | select(.status == "captured")] | length) >= 1 and
    ([.opportunities[] | select(.discard_reason != null)] | length) >= 1 and
    (.demo.mode == "jury") and (.demo.scenario_run_id != null) and
    (.demo.scenario_started_at != null) and (.demo.expected_result != null) and
    (.demo.scenario as $s |
      ["naive_trap", "peg_adverse", "stale_feed", "latency_decay", "thin_book"] |
      index($s) != null)
  ' "$EVIDENCE_DIR/api/session-export.tmp.json" >/dev/null && {
    mv "$EVIDENCE_DIR/api/session-export.tmp.json" \
      "$EVIDENCE_DIR/api/session-export.json"
    break
  }
  sleep 1
done
test -s "$EVIDENCE_DIR/api/session-export.json"
! rg -ni '"(control_token|api_key|secret|password)"[[:space:]]*:' \
  "$EVIDENCE_DIR/api/session-export.json"
```

En el corte mínimo de PRD-013, el estado `observado` se deriva en el cliente y no forma parte de
`SessionExport`; sólo RF-003A stretch añade `demo.observed_result` al backend. Por eso
`smoke/scenario-observation.md` registra, para el mismo `scenario_run_id` adverso del export, las
líneas visibles `esperado`/`observado`, estado y fuente, con referencia a captura o video. No se
inventa ni se exige el campo backend cuando se adopta RF-003B.

No fijar `ARB_INGEST_AUTOSTART=false` para esta sesión: en el wiring actual eso también evita las
tasks `engine` y `demo`, por lo que el POST solo inyectaría un tick sin producir la secuencia. Al
activar `jury`, `on_book` ignora los ticks de feeds externos (`main.py:264-265`) y el player
determinista pasa por el motor local; comprobar esa activación antes de capturar.

Capturas — rutas y comandos literales. Desktop se captura headless; la copia entregable
`assets/dashboard.png` se regenera desde la captura de Resumen y entra en el commit de evidencia:

```bash
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless=new --window-size=1600,1000 --hide-scrollbars \
  --screenshot="$EVIDENCE_DIR/captures/resumen-desktop.png" 'http://localhost:3000/'
cp "$EVIDENCE_DIR/captures/resumen-desktop.png" "$REPO_ROOT/assets/dashboard.png"
```

La captura de Correctitud (`captures/correctitud-desktop.png`) exige cambiar de pestaña: se toma
desde el navegador real de la sesión de smoke, no con `--screenshot` plano.

> **Gotcha conocido de captura headless** (verificado en este repo durante la fase Edge Waterfall;
> nota de sesión `frontend-edge-waterfall`): Chrome headless con `--window-size=390` renderiza con
> un piso de ~500 px CSS, así que una captura “móvil” a 360-390 px **recorta** el render y produce
> falsos overflows. La verificación a 360 px de RF-009 se hace en navegador real con device
> toolbar, midiendo `document.documentElement.scrollWidth <= clientWidth`; el
> `Table.ScrollContainer` reporta scrollWidth mayor por diseño (scroll interno), no es overflow de
> página.

Contenido obligatorio y medible:

1. Capturas de Resumen (`captures/resumen-desktop.png`) y Correctitud
   (`captures/correctitud-desktop.png`); `assets/dashboard.png` regenerado **después del tag** y
   commiteado en el commit de evidencia (el tag no se mueve). Cada imagen muestra pie visible con
   fecha, tag/SHA y `JURY · LOCAL`.
2. Export JSON parseable, sin secretos y con al menos una oportunidad `captured`, una con
   `discard_reason` no nulo y un escenario adverso identificado por `scenario_run_id`, inicio y
   resultado esperado; su observado coherente queda ligado al mismo ID en
   `smoke/scenario-observation.md` y en captura o video.
3. `validation.json` con `all_passed=true`, `target=109.75`, `computed=109.75` y
   `abs(diff) ≤ 0.0001`; todas las invariantes en `passed=true`.
4. Logs completos de backend, frontend y Compose; versiones de Python/uv/Node/npm/Docker/Compose;
   audits y decisión de §13.
5. Video local de **80-100 s** siguiendo §9 y hoja de respuestas de §10 ensayada.
6. Comandos locales de arranque/parada y rollback al último tag verde. Los comandos remotos del
   Bloque 7 pueden documentarse para otro día, pero no se ejecutan ni cuentan como evidencia.
7. `SHA256SUMS` del paquete y manifiesto que enumera cada artefacto; cero archivos obligatorios
   vacíos. Generación:
   `(cd "$EVIDENCE_DIR" && find . -type f ! -name SHA256SUMS -print0 | xargs -0 shasum -a 256 | LC_ALL=C sort -k2 > SHA256SUMS)`.

### RF-009 Smoke dirigido frontend (R13)

Checklist manual sobre el build del tag, en desktop y viewport 360 px. Cada fila de
`smoke/frontend.md` registra `PASS/FAIL`, hora, navegador/versión y evidencia:

- [ ] Strategy Lab no crea un EventSource nuevo al mover/aplicar parámetros.
- [ ] `STALE` aparece tras >10 s sin eventos y vuelve a `LIVE` al reanudarlos.
- [ ] Retry de cada panel con error dispara una petición y recupera o mantiene error explícito.
- [ ] Resumen conserva sparklines al cambiar de tab y volver.
- [ ] A 360 px no existe scroll horizontal involuntario ni solapamiento de texto/botones.
- [ ] Error boundary forzado muestra recuperación y el retry vuelve a renderizar.
- [ ] Badge `JURY · LOCAL`/simulación y texto del guion son legibles en el dispositivo real.

Un solo `FAIL` rechaza el candidato. Se aplica RF-005: fix, commit nuevo, gate completo, tag nuevo
y paquete regenerado; no se parchea la evidencia a mano.

## Plan de implementación

1. Bloque 0 (hecho): rama `entrega-12jul` con checkpoint `98d4937`; runtime crítico ya tracked.
2. Bloque 3: RF-002..RF-004 desde worktree detached del HEAD vigente; gate preliminar, sin tag.
3. Integrar PRD-009..PRD-014/Bloques 4-6 con commits incrementales por parte y ejecutar un smoke
   local preliminar.
4. Ejecutar RF-006 por timebox; re-gate inmediato de cada ítem aceptado.
5. RF-007: HEAD final de la rama, worktree nuevo, suite completa, Compose y smoke preliminar.
6. Crear `candidato-12jul` anotado únicamente sobre el SHA verde (nada se llama candidato antes de
   construir y probar desde ese commit).
7. RF-008 y RF-009 desde ese tag contra `localhost`; generar checksums y cerrar manifiesto.
8. Actualizar checklists Local/Frontend del §11; Server queda `NO EJECUTADO por decisión`.

## Pruebas

- Verificación realizada durante esta revisión: backend 507 passed/91.03%, ruff y mypy limpios;
  frontend typecheck/lint/build limpios y First Load JS 263 kB. Es baseline del worktree, no gate
  de candidato.
- Regresiones de atomicidad de PRD-009: cualquier venue ausente implica cero mutación y cero P&L.
- P2 auth: `X-API-Key` y `X-Control-Token` no-ASCII responden 401, no 500.
- Reproducibilidad: suite completa en el worktree detached limpio del SHA final antes del tag; los
  logs copiados al paquete identifican exactamente el SHA que luego resuelve el tag.
- Integridad del paquete: JSON validado con `jq`, artefactos no vacíos y checksums verificables.

## Criterios de aceptación

- HEAD final de `entrega-12jul` con árbol limpio (commits incrementales por parte, sin untracked
  residual); runtime requerido tracked; worktree detached del candidato con cero líneas en
  `git status --porcelain`.
- Desde el SHA etiquetado: ruff 0 hallazgos, mypy 0 errores, >507 tests passed, cobertura ≥85%,
  typecheck/lint/build exit 0, `docker compose config --quiet` exit 0 y build sin caché exit 0.
- Compose disponible y PRD-011 verificable: build backend desde `uv.lock`, volumen `/data`,
  `ARB_DB_URL` y healthcheck presentes. Mientras Compose falte, no hay release aceptado.
- P2 aceptado re-gateado y luego cubierto otra vez por el gate final; P2 abandonado registrado con
  causa y sin cambios parciales en el SHA.
- Tag anotado `candidato-12jul` (o su sucesor `.N`) apunta exactamente al SHA probado y nunca fue
  movido.
- Toda evidencia proviene del stack local del tag; cero conexiones o despliegues a server público.
- Paquete contiene capturas con fecha/tag/SHA/modo, export sin secretos, captured+discarded+adverso,
  registro esperado/observado ligado por `scenario_run_id`, reconciliación con
  `abs(diff) ≤ 0.0001`, logs/audits, video 80-100 s, smoke 7/7 y checksums.
- Ningún artefacto obligatorio vacío; manifiesto registra comando, exit code y estado
  `PASS/FAIL/NO EJECUTADO` sin ocultar fallos.

## Riesgos

- **Archivos omitidos o arrastre histórico.** Mitigación: commits incrementales por parte con
  `git status --porcelain` vacío al cierre de cada una, `git ls-files` del runtime crítico y
  worktree detached; nunca staging masivo de cierre.
- **Gate preliminar confundido con final.** Mitigación: no crear tag en Bloque 3; re-gate completo
  después de Bloques 4-6 y P2.
- **Compose ausente.** Mitigación: preflight al inicio; detener RF-004 hasta habilitar el plugin.
  No degradar el requisito ni desplegar públicamente para compensarlo.
- **P2 invalida evidencia.** Mitigación: P2 antes del tag; re-gate inmediato y final.
- **Evidencia de otro commit.** Mitigación: stack desde worktree del tag, SHA visible, manifest y
  checksums.
- **Audit no-cero interpretado como error ocultable.** Mitigación: conservar salida/exit code y
  decisión de riesgo de §13; nunca forzar una migración mayor esta noche.
- **Timebox insuficiente.** Prioridad: atomicidad/autocontención/gates/evidencia > P2. El ítem que
  exceda timebox se abandona de forma explícita sin arrastrar al siguiente.
