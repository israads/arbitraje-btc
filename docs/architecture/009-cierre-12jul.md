# Arquitectura 009: Cierre 12-jul — consolidada para PRD-009..PRD-015

Fecha: 11 de julio de 2026. Rama: `entrega-12jul`.
Fuente de orden y timeboxes: [docs/plan-accion-final-12jul.md](../plan-accion-final-12jul.md) §4-§6.
PRDs implementados: [009](../prd/009-atomicidad-ledger-venues.md) ·
[010](../prd/010-superficie-readonly-auth.md) · [011](../prd/011-deploy-reproducible-persistente.md) ·
[012](../prd/012-panel-inventario-rebalanceo.md) · [013](../prd/013-escenarios-esperado-observado.md) ·
[014](../prd/014-narrativa-visual-honesta.md) · [015](../prd/015-release-suite-evidencia.md).

**Precedencia operativa.** El orden y los timeboxes base son los del plan. La adaptación posterior
y explícita de PRD-011 y PRD-015 prevalece únicamente sobre el destino de ejecución: esta noche no
se ejecutan los Bloques 0b ni 7, y el Bloque 8 se realiza contra `localhost` desde el tag. Esos dos
bloques se registran `NO EJECUTADO por decisión`, no se simulan ni se cuentan como aprobados. Los
gates locales de correctitud, Compose, persistencia, release y evidencia no se reducen.

## Objetivo arquitectónico

Cerrar cuatro garantías sin ampliar superficie: (1) ninguna ejecución reconoce P&L sin aplicar
todas sus patas al ledger; (2) el deploy público es un visor read-only que nunca emite mutaciones;
(3) configuración, runtime y UI representan el mismo estado; (4) toda cifra y claim de la demo
declara origen, muestra y evidencia observada, y el release es reproducible desde un commit
autocontenido. Restricción global de la noche: **cero contacto con el server público** — todo gate
es local; el Bloque 7 (deploy remoto) queda fuera de alcance.

## 1. Visión de conjunto y dependencias

Los siete PRDs se integran como un DAG lineal. Algunas partes no dependen funcionalmente de la
anterior, pero se serializan porque comparten archivos o porque el gate siguiente acumula todo el
HEAD. Una colisión de archivo no crea una arista de vuelta.

```text
Parte 1       Parte 2       Parte 3        Parte 4
009/B1 ─────▶ 010/B2 ─────▶ 011/B2+2b ───▶ gate preliminar/B3
  │            │              │                 │
  │ nunca      │ READ_ONLY    │ Compose         │ sin tag
  │ cortar     │ condiciona   │ condiciona      ▼
  │            │ UI nueva     │ release       Parte 5       Parte 6       Parte 7
  │            └──────────────┴──────────────▶ 012/B4 ─────▶ 013/B5 ─────▶ 014/B6
  │                                                                       │
  └──────────────── garantía contable acumulada ──────────────────────────┤
                                                                          ▼
                         Parte 8: P2 elegible → re-gate final → tag → evidencia/B8

Fuera de ejecución esta noche: B0b y B7 remotos. No forman atajos ni aristas del DAG local.
```

Dependencias concretas (no solo de orden, sino de contrato):

- **009 → todo.** El gate Go del plan (§8) exige que no exista camino probado que acumule P&L con
  una pata ausente. Ningún bloque posterior tiene valor si la contabilidad puede mentir.
- **009 → 010 en `ConfigPanel.tsx` (coedición, no ciclo).** El manejo de errores debe ramificar por status: `401`
  (requiere token, PRD-010 RF-007) ≠ `409` (`venue_restart_required`, PRD-009 RF-004/RF-005) ≠
  fallo de red. La segunda pasada de 010 preserva el `409` implementado por 009.
- **010 → 011.** El gate Docker de 011 (RF-011) valida que `NEXT_PUBLIC_READ_ONLY=1` estuvo
  presente durante `npm run build` y que el bundle contiene `READ-ONLY DEMO`; ese literal solo
  existe si 010 implementó el badge (RF-006). 011 no puede cerrarse antes que 010.
- **010 → 012/013/014.** Toda superficie nueva de los bloques 4-6 nace bajo la matriz RF-009 de
  010: el `InventoryPanel` (012) es 100 % GET; los chips de escenario (013) quedan solo en la
  superficie de operador y el cambio de escenario se dispara por CLI local (por SSH solo en una
  ventana remota futura); las etiquetas de 014 son render puro. Cualquier `fetch` no-GET nuevo debe
  clasificarse en el inventario antes de aceptar el release.
- **011 → 015.** El gate Compose de 015 (RF-004) exige el compose canónico con volumen `/data`,
  `ARB_DB_URL`, healthcheck y build frozen desde `uv.lock` — todos entregables de 011.
- **013 → 015.** El `jq` del export de evidencia (015 RF-008) exige `demo.scenario_run_id`,
  `demo.scenario_started_at` y `demo.expected_result`: campos que introduce 013 RF-002.
- **015 cierra, sin arista de retorno.** El gate preliminar de la Parte 4 consume 009..011, pero no
  convierte a 015 en dependencia de implementación de esas partes. Ningún tag se llama
  `candidato` hasta probar el HEAD final exclusivamente desde un worktree detached (RF-007).

## 2. Decisiones de arquitectura transversales

### AD-1 — Validate-then-apply en el ledger (PRD-009)

**Contexto.** `apply_execution()` muta balances pata por pata y omite con `continue` las patas
cuyo venue no existe, pero suma igualmente `execution.realized_pnl`
(`backend/app/sim/inventory.py:347-387`). El caller marca `captured` y mide **antes** de aplicar
al ledger, y encola la persistencia justo después — todo incondicional, porque `apply_execution`
devuelve `None` y hoy no puede fallar (`backend/app/main.py:185-203`: captured en 185, métricas en
189, apply en 194, enqueue en 203). Resultado reproducido: P&L contable sin los movimientos
físicos que lo sustentan.

**Decisión.** `apply_execution(execution) -> bool` con tres fases sin `await`: (1) preparar y
validar todas las patas y el leg risk contra `self.venues`; (2) aplicar sobre estado protegido con
snapshot previo de los campos contables (`btc`, `quote`, `open_btc`, `open_cost_basis_usd`,
`realized_pnl`); (3) confirmar o restaurar el snapshot completo ante excepción. `can_afford()` se
endurece: `False` si falta buy o sell venue. Los callers (live, replay, validación) solo cuentan,
miden, publican y persisten con `True`; con `False` la opp se reclasifica a `discarded`
(`insufficient_balance`) y se reconcilia el funnel una vez. El mismo patrón rige el endpoint de
config (RF-007): preparar sobre copias → persistir en transacción → aplicar runtime sin `await`
intermedio.

**Alternativas descartadas.** (a) Solo endurecer `can_afford()`: no protege llamadas directas,
replay ni carreras lógicas. (b) Supervisor dinámico de feeds para hot-toggle real de venues:
correcto pero fuera del timebox (post-entrega, §14 del plan). (c) Excepciones en lugar de `bool`:
obligaría a try/except en tres callers y arriesga capturas parciales silenciosas.

**Consecuencias.** El fingerprint contable cambia por todos los efectos de una ejecución aceptada
o no cambia en absoluto. `enabled` deja de ser editable en caliente (HTTP `409`,
`code=venue_restart_required`); las ediciones hot seguras (fees, balances, tamaño, umbrales) se
conservan con reseed solo si cambian balances iniciales. Dos tests permisivos existentes se
invierten, no se borran. Coste: un caller futuro puede ignorar el `bool` — mitigado con búsqueda
global de callers y tests de no-propagación.

### AD-2 — Flag build-time + constante única en `lib/config.ts` (PRD-010)

**Contexto.** El frontend renderiza controles protegidos que siempre responderían 401 en prod
(riesgo R2). `NEXT_PUBLIC_*` se sustituye por literal en `npm run build`: un flag runtime no
cambia un bundle ya compilado.

**Decisión.** `NEXT_PUBLIC_READ_ONLY` es build-time con redundancia deliberada: `ARG
NEXT_PUBLIC_READ_ONLY=1` (default seguro) + validación `0|1` en
`deploy/standalone/Dockerfile.frontend`, y `build.args: "1"` explícito en el compose. Una única
constante exportada junto a `API_BASE`:
`export const READ_ONLY = process.env.NEXT_PUBLIC_READ_ONLY === '1';` añadida al
`frontend/lib/config.ts` **existente** (el archivo ya existe y exporta `API_BASE`; no crear otro),
consumida por import directo de módulo (mismo patrón que `API_BASE`). En read-only la petición
protegida **no sale del navegador**; el 401 del backend sigue siendo el límite de seguridad, no el
mecanismo de UX. Strategy Lab se conserva como what-if de sesión (retorna tras `onApply` antes del
`PATCH`), export permanece activo, y el badge `READ-ONLY DEMO` va en el header.

**Alternativas descartadas.** (a) React Context/provider: innecesario — la constante es un literal
estable en build-time, no provoca re-renders. (b) Flag en `environment:` del compose: prohibido
como mecanismo, no modifica el bundle. (c) BFF con Basic Auth (opción B) y OIDC: post-entrega por
timebox. (d) nginx inyectando `X-Control-Token`: convertiría a todo visitante anónimo en operador
— prohibición no negociable.

**Consecuencias.** Dev local conserva superficie completa por omisión (no añadir el flag a
`.env.local` ni a `package.json`). Una imagen construida fuera de la ruta oficial puede mostrar
superficie completa: el backend la protege, pero el gate RF-010 (artefacto contiene el literal,
DOM lo sirve, token ausente del bundle, 0 requests protegidos en smoke) la declara NO-GO —
reconstruir, no reiniciar.

### AD-3 — Compose canónico `deploy/standalone` con volumen `arb-data` (PRD-011)

**Contexto.** Coexisten dos composes; el backend escribe SQLite en la capa del contenedor
(recrear = perder datos, R3); el build usa `pip install .` sin lock (R4); `/health` reporta `ok`
con tasks `finished`/`cancelled` (R8).

**Decisión.** `deploy/standalone/docker-compose.yml` es **el compose canónico** del cierre y del
Bloque 7 futuro: volumen nombrado `arb-data:/data`, `ARB_DB_URL:
sqlite+aiosqlite:////data/arbitraje.db` (cuatro barras), `environment` como mapa, healthcheck en
Python stdlib que parsea `status == "ok"` del body (no solo HTTP 200), y nginx con `depends_on:
condition: service_healthy`. `deploy/docker-compose.yml` (backend-solo, uso dev) recibe el mismo
par volumen/URL en el mismo commit para no divergir del Dockerfile compartido, pero queda fuera de
gates. Build backend en dos fases con `uv sync --frozen` (lock primero, proyecto después); imágenes
base fijadas por `tag@sha256:digest`; `/data` con ownership 10001:10001; `/health` degrada ante
**cualquier** task terminal (agregación en `backend/app/api/health.py:91`) — verificado que las
siete tasks del árbol actual son bucles sin salida normal, así que no hay falsos positivos.

**Alternativas descartadas.** (a) Bind mount de directorio: menos portable y con más superficie de
permisos que el volumen nombrado con mountpoint inicializado por Docker. (b) `/livez` + `/readyz`
con 503 real: post-entrega; RF-005 interpreta el body. (c) Migrar a Postgres o Next 16: fuera de
alcance con excepción documentada. (d) Deploy remoto esta noche: excluido por decisión del usuario
— este PRD entrega archivos, runbook y validación local.

**Consecuencias.** Health pasa de señal decorativa a gate de arranque: nginx no avanza sin backend
`healthy`, y el runbook exige body `ok` con el conjunto esperado de tasks (siete más writer con los
defaults actuales; si el `.env` cambia defaults, el conjunto se recalcula y documenta).
Backup/restore se prueba en un volumen local desechable; `down -v` queda prohibido en runbooks.
Precondición dura: daemon Docker + plugin Compose v2 locales. Si Compose no está disponible,
PRD-011 queda `Pendiente`, PRD-015 RF-004 queda `BLOQUEADO` y no existe release aceptado; no se usa
el server como sustituto del gate local.

### AD-4 — Estado de rebalanceo en `useStream` con fetch en `pullLight` (PRD-012)

**Contexto.** El backend ya expone todo lo que C3 necesita (`/pnl` con `rebalance` y skew,
`/balances` por venue), pero nada es visible en UI, y `Tabs` usa `keepMounted={false}`: el panel
se desmonta al cambiar de pestaña.

**Decisión.** El dueño del I/O es `useStream` (montado siempre en la página), no el componente:
`/balances` se pide dentro del `pullLight` existente de 5 s (`useStream.ts:669-683`), sin crear un
segundo intervalo, con máximo un request en vuelo, `AbortController` compartido y
`balancesUpdatedAt`/`retryBalances`. `InventoryPanel.tsx` es presentación pura (patrón
`NaiveVsEdgePanel`): props tipadas, cero fetch, cero copia de estado. Los tipos TS reflejan las
ramas reales del contrato (sin portfolio: `equity_usd` ausente, `skew: {}`, `rebalance` omitido) y
todo render pasa por guards + `Number.isFinite` — ausencia se pinta “—”, nunca 0. Fix previo
obligatorio: `Rebalancer.run()` pasa `time.time()` en lugar de `ts=0.0` (el reloj se lee en la
capa impura; `Portfolio.rebalance()` sigue determinista por parámetro).

**Alternativas descartadas.** (a) Fetch dentro del componente: se desmonta con la pestaña,
duplicaría requests y perdería estado. (b) Intervalo dedicado para `/balances`: viola el
precedente de `naive-vs-edge`/`wins` y multiplica timers. (c) Nuevo endpoint agregado backend:
innecesario, los contratos existen. (d) `time.monotonic()` para el timestamp: no es fecha.

**Consecuencias.** Cadencia acotada y verificable (≤4 requests en 15 s); el panel tolera vacío,
parcial y error con degradación honesta (“DATOS DESACTUALIZADOS” + `updatedAt`). El coste de
decisión (breakdown `rebalance` del explain, magnitud de un `usd` negativo) y el coste debitado
(`rebalance.cost_total_usd`) se muestran en tarjetas separadas y jamás se suman.

### AD-5 — `run_id` en backend + baseline en frontend (PRD-013)

**Contexto.** Los escenarios jury declaran resultados pero nada liga la evidencia a una activación
concreta: `discard_reasons` es acumulado de sesión, `scenario`/`scenario_index` se repiten, y con
500 ms por escenario frente a métricas cada 1 s el delta ni siquiera puede muestrearse.

**Decisión.** El backend aporta solo identidad: `scenario_run_id` (monotónico por proceso,
incrementado en el único punto `_emit_jury_next` cuando `changed`) y `scenario_started_at`
(monotónico, comparable con `opportunity.t_recv`), más cadencia suficiente
(`repeats_per_scenario=45` ⇒ duración ≥ 2×`metrics_emit_ms`+250 ms). Toda la ventana de
observación vive en el frontend, en un único `useRef<ScenarioObservationWindow>` dentro de
`useStream`: baseline copiada del **primer snapshot SSE de métricas posterior** a ver el `run_id`
nuevo, contador directo de eventos `opportunity` con `t_recv >= scenario_started_at`, delta
`latest − baseline`, y estado derivado `pending | observed | absent` con motivo visible. La señal
directa atribuible es la evidencia primaria: un delta de métricas sin evento directo temporalmente
equivalente queda `absent · telemetría insuficiente`, y si ambas fuentes existen pero discrepan
queda `absent · evidencia inconsistente`. Delta negativo ⇒ telemetría reiniciada; baseline
irrecuperable ⇒ `absent · telemetría insuficiente`. `order_failure` se reformula por defecto
(RF-003B: badge `NO EJERCE EJECUCIÓN`); el harness de preflight local es stretch. Unwind solo se
narra vía replay/backtest.

**Alternativas descartadas.** (a) Evidencia calculada en backend: duplicaría estado de sesión de
cliente y no resiste reconexiones SSE mejor que la ventana local. (b) Usar el nombre del escenario
como clave: se repite en cada ciclo. (c) Baseline `{}` o último acumulado conocido: convierte
actividad histórica en delta del escenario vigente — prohibido. (d) Inyectar `sell_book_t1` en
vivo para “demostrar” unwind: viola las cuatro prohibiciones del plan.

**Consecuencias.** Nunca se muestra `esperado` sin `observado`; `pending`/`absent` son estados
honestos que el gate no acepta como éxito. El export de 015 puede exigir `scenario_run_id` en
`demo`. Coste aceptado: tras una reconexión SSE con transición perdida, la UI dice `absent` hasta
el siguiente `run_id` en lugar de fingir continuidad.

### AD-6 — Mapa contrato→etiqueta sin recálculo en frontend (PRD-014)

**Contexto.** Cuatro cifras pueden leerse como lo que no son: el `$109.75` canónico compite con
cifras de mercado, la tesis no declara `frontier.mode`, `P(P&L>0)` no muestra su muestra, y la
decisión del motor no se lee como veredicto literal.

**Decisión.** Cada etiqueta nueva se alimenta de un campo exacto del contrato existente o de una
invariancia documentada del endpoint, sin recálculo ni campo inventado: `CASO CANÓNICO` es un
literal fijo del frontend amparado por la invariancia de `/api/v1/validation` (escenario
determinista con `reconciliation.target=109.75`; **no** existe ni se añade un campo con ese
texto); `LIVE`/`DEMO` viene de `frontier.mode` y `buy→sell` de
`frontier.route` (omitida si `null`); `RECORDING → REPLAY` es invariancia de `/api/v1/forward` (no
un campo de `ForwardProjection`); `n_trades`/`n_paths` se leen tal cual; `OPERAR`/`NO OPERAR` es
tabla de verdad sobre `engine.trades: boolean` únicamente. Reglas transversales: `asof_monotonic`
jamás se formatea como hora; ningún estado depende solo del color (literal visible siempre);
Equity pasa a `accent="neutral"`.

**Alternativas descartadas.** (a) Añadir `mode`/`source` a `ForwardProjection`: amplía contrato
API para un valor constante. (b) Inferir el veredicto del signo de `net_usd` o del color: recálculo
en frontend, fuente de divergencia. (c) Rediseñar la tesis o añadir charts: fuera del timebox de
45 min y del alcance (solo etiquetas).

**Consecuencias.** El mapa contrato→etiqueta del PRD es verificable por búsqueda estática; el
frontend no puede contradecir al motor porque no calcula nada. Si el timebox aprieta, la regla de
corte §6.4 conserva cambios 1-2 + veredicto.

### AD-7 — Tag inmutable tras re-gate acumulado (PRD-015)

**Contexto.** La base local está verde, pero eso no prueba que el HEAD final construya desde un
árbol limpio ni que la evidencia corresponda al mismo código (R11, R13). El Bloque 3 ocurre antes
de los Bloques 4-6: su suite es preliminar por definición.

**Decisión.** Commits incrementales por parte (árbol limpio al cierre de cada una; sin
`git add .`); los gates de release preliminar y final RF-002..RF-004 se ejecutan desde un
**worktree detached** del SHA a verificar (`git status --porcelain` vacío); re-gate completo
(backend, frontend, Compose, smoke preliminar) sobre el HEAD final después de PRD-009..014 y P2;
solo entonces se crea el tag anotado sobre el SHA probado (comando canónico en la Parte 8).
Un tag rechazado no se mueve jamás: el siguiente es `candidato-12jul.2`. El paquete de evidencia
(`docs/evidencia-12jul/<tag>-<sha12>/`) se genera exclusivamente desde el stack local levantado
del tag, con SHA/fecha/modo en cada artefacto y `SHA256SUMS`, y se commitea después del tag.

**Alternativas descartadas.** (a) Tag en el Bloque 3: los Bloques 4-6 y P2 lo invalidarían —
gate preliminar ≠ final. (b) Mover el tag tras un fix: destruye la trazabilidad evidencia↔SHA.
(c) Staging masivo de cierre: reintroduce el riesgo de untracked accidental que motivó R11.
(d) Montar Playwright/Vitest hoy: el smoke frontend es manual y dirigido (RF-009).

**Consecuencias.** P2 solo entra antes del tag y con re-gate inmediato; un `FAIL` del smoke
rechaza el candidato completo (fix → commit → suite → tag nuevo → paquete regenerado). Compose
ausente bloquea RF-004 y por tanto el release: no se degrada el requisito.

## 3. Arquitectura de redundancia

### 3.1 Capas de defensa del ledger (PRD-009)

```text
Config/UI      bloquea hot-toggle de enabled (409 + switch deshabilitado)
    ↓
Gate pre-trade can_afford() exige buy y sell venue en el portfolio
    ↓
Commit ledger  apply_execution() valida TODAS las patas y el leg risk
               antes de mutar; snapshot + rollback ante excepción
    ↓
Callers        solo cuentan/publican/persisten con True; False ⇒ discarded
               + reconciliación única del funnel
    ↓
Tests + logs   regresiones obligatorias + warning estructurado con
               execution_id, opportunity_id, fase y venues ausentes
```

Las capas no se sustituyen: la 1 elimina la fuente conocida de divergencia, la 2 filtra el flujo
normal, la 3 protege llamadas directas/replay/carreras, la 4 impide evidencia aguas abajo que
contradiga el asiento. Invariantes protegidos: doble entrada por pata, conservación de BTC/quote,
`total_pnl = realized + unrealized`, atomicidad del fingerprint contable, correspondencia
evidencia↔asiento y coherencia `Settings = Portfolio.venues = ingestors = UI`. Concurrencia:
`on_opp` es síncrona y RF-002 no contiene `await` (un solo event loop ⇒ ninguna lectura ve estados
intermedios); el endpoint de config prepara sin mutar, commitea y aplica runtime sin `await`
intermedio.

### 3.2 Degradación honesta del frontend

- **Estado de datos:** badges `LIVE/DEMO/REPLAY/STALE` existentes + `READ-ONLY DEMO` persistente
  (010) + `DATOS DESACTUALIZADOS` con `updatedAt` cuando `/balances` falla tras un éxito (012) +
  `esperado/observado` con `pending`/`observed`/`absent` y motivo visible (013). La ausencia de
  dato se muestra como “—” o mensaje, nunca como cero ni como el último éxito disfrazado de vivo.
- **Read-only en profundidad:** default `ARG=1` del Dockerfile (sobrevive a un compose que omita
  el arg) + `build.args` explícito + gate de artefacto/DOM/token/Network (RF-010). Si todo eso
  falla y se despliega una imagen completa por error, la autenticación del backend sigue
  rechazando mutaciones anónimas: la UX es la barrera de honestidad, el token es el límite de
  seguridad.
- **Etiquetas sin recálculo (014):** el frontend no puede afirmar más de lo que el contrato trae;
  texto antes que color en todos los estados nuevos.

### 3.3 Persistencia y health como gate (PRD-011)

- **Datos:** volumen nombrado `arb-data` + WAL/`synchronous=NORMAL`/`auto_vacuum=INCREMENTAL`
  verificados **dentro** del contenedor sobre una DB nueva en `/data/arbitraje.db` + marker y
  conteos persistentes tras `--force-recreate` + backup consistente (API de SQLite) restaurado en
  un segundo volumen, nunca sobre la fuente. La DB y sus datos persisten; `-wal`/`-shm` solo se
  exige observarlos con una conexión viva, porque SQLite puede retirarlos al cerrar la última.
- **Health:** unit tests prueban la semántica del body (toda task terminal ⇒ `degraded`); el
  healthcheck de compose prueba su consumo (exit 1 si body ≠ `ok`); `service_healthy` impide que
  nginx avance; el operador y el timeout de 120 s impiden aceptar un `unhealthy` estable. Un
  contenedor unhealthy detiene el flujo con evidencia — no hay loop de auto-restart que lo oculte.

### 3.4 Fallo por componente

| Componente que falla | Comportamiento exigido | Quién lo garantiza |
|---|---|---|
| Venue ausente en ejecución | `apply_execution=False`, fingerprint intacto, opp `discarded` | 009 RF-001/002/003 |
| Excepción a mitad de mutación del ledger | rollback del snapshot, cero P&L, cero equity point | 009 RF-002 fase 3 |
| Escritura DB del PUT config | no-2xx; `Settings`, portfolio, cache y fila previa intactos | 009 RF-007 |
| Task del engine muere / termina | `/health` `degraded`, healthcheck exit 1, gate detenido | 011 RF-004/005 |
| Contenedor backend recreado | DB, marcador, config y conteos sobreviven en `arb-data`; WAL/SHM son observables con conexión viva | 011 RF-001/003/007/012 |
| Imagen frontend sin flag read-only | backend sigue rechazando (401); gate RF-010 la declara NO-GO | 010 AD-2 |
| `/balances` falla (antes/después de éxito) | `FetchFallback` con retry / snapshot + badge desactualizado | 012 RF-005 |
| Pérdida de SSE / reinicio de telemetría | ventana invalidada, `absent` con motivo; nunca éxito heredado | 013 RF-002 |
| `frontier.mode=demo` o `forward.available=false` | `DEMO` visible; para forward, origen fijo + muestra insuficiente y ningún porcentaje/conteo simulado | 014 RF-002/003 |
| Gate del release falla | secuencia detenida, log en `failed/<sha12>/`, commit nuevo, re-gate total | 015 RF-005 |
| Smoke frontend `FAIL` tras el tag | tag marcado RECHAZADO (no se mueve), candidato `.N` nuevo | 015 RF-007/009 |

## 4. Orden de implementación, archivos y gates acumulados

Regla general: un commit de producto por parte, árbol limpio al cierre, y **gate acumulado**. La
única excepción es la Parte 3: su intento de actualización de dependencias va en un segundo commit
aislado para poder integrarlo o revertirlo íntegro. Tras cerrar la parte N se ejecuta el gate que su
PRD exige sobre el HEAD nuevo; cuando dice “suite completa”, los tests de las partes anteriores ya
están incluidos. El gate preliminar y el final se ejecutan desde worktrees detached distintos. El
preliminar no autoriza tag ni sustituye al final.

**Comandos canónicos de gate** (desde la raíz del repo; la “suite dirigida” se ejecuta primero
para fallar rápido y **nunca** sustituye al comando completo):

- `GATE-BACKEND`: `(cd backend && uv sync --frozen && uv run ruff check . && uv run mypy app && uv run pytest -q --cov=app --cov-fail-under=85)`
- `GATE-FRONTEND`: `(cd frontend && npm ci && npm run typecheck && npm run lint && npm run build)`
- `GATE-FRONTEND-RO` (solo Parte 2 y gates de release):
  `(cd frontend && npm ci && npm run typecheck && npm run lint && npm run build && NEXT_PUBLIC_READ_ONLY=1 npm run build)`
- `GATE-COMPOSE` (solo si Docker + Compose v2 locales):
  `ARB_CONTROL_TOKEN=local-evidence-placeholder docker compose -f deploy/standalone/docker-compose.yml config --quiet`,
  luego `ARB_CONTROL_TOKEN=local-evidence-placeholder docker compose -f deploy/standalone/docker-compose.yml build --no-cache backend frontend`,
  luego `ARB_CONTROL_TOKEN=local-evidence-placeholder docker compose -f deploy/standalone/docker-compose.yml up -d --wait --wait-timeout 120`,
  luego las verificaciones del runbook (PRAGMAs, marker, `--force-recreate`, backup/restore) y
  `ARB_CONTROL_TOKEN=local-evidence-placeholder docker compose -f deploy/standalone/docker-compose.yml down`
  **sin `-v`**.
- Worktree detached (gates preliminar y final): `test -z "$(git status --porcelain)"` →
  `SHA=$(git rev-parse HEAD)` → `WT="../cc-gate-$(git rev-parse --short=12 "$SHA")"` →
  `git worktree add --detach "$WT" "$SHA"` → `test -z "$(git -C "$WT" status --porcelain)"`
  → ejecutar los gates desde la raíz de `"$WT"` → volver al repo principal y ejecutar
  `git worktree remove "$WT"`.

El invariante de incrementalidad es exigible: **cada parte incluye en su mismo commit los tests
que su cambio de comportamiento requiere** (las inversiones de tests permisivos van en la Parte 1,
los tests de health en la Parte 3, el del epoch en la Parte 5, los de `scenario_run_id` en la
Parte 6). Ninguna parte deja la suite en rojo esperando a la siguiente; el único cambio revertible
en bloque es el commit aislado de deps de la Parte 3 (bump íntegro o revert íntegro).

### Correspondencia con §4 del plan

| Bloque del plan | Timebox del plan | Parte/estado esta noche | Regla sin ambigüedad |
|---:|---:|---|---|
| 0 | 20 min | previo, ya cerrado según PRD-015 RF-001 | verificar checkpoint y runtime tracked; no repetir trabajo |
| 0b | 20 min | `NO EJECUTADO por decisión` | PRD-011 solo prepara la checklist; cero SSH/rsync/build remoto |
| 1 | 2 h | Parte 1 | nunca cortar |
| 2 | 2 h 30 min compartidos | Partes 2 y 3 | 010 y el núcleo de 011 comparten el presupuesto; no se suman 2 h 30 min a cada una |
| 2b | 45 min | tramo aislado de Parte 3 | parches Python completos o excepción; Next 16 no entra |
| 3 | 45 min | Parte 4 | gate preliminar desde commit limpio, sin tag |
| 4 | 90 min | Parte 5 | corte de PRD-012 no autorizado: se cierra completo |
| 5 | 60 min | Parte 6 | aplicar el corte mínimo de PRD-013; nada provisional al minuto 60 |
| 6 | 45 min | Parte 7 | orden interno `1→2→4→3`; corte: 1-2 + veredicto |
| 7 | 1 h 15 min | `NO EJECUTADO por decisión` | no se consume ni se declara verde; la demo local es la ruta principal |
| 8 | 1 h | evidencia de Parte 8 | solo paquete/ensayo local desde el tag; no absorbe P2 ni el re-gate |

Las Partes 2 y 3 se ejecutan en ese orden dentro de un único presupuesto de 2 h 30 min: no existe
una cuota independiente por PRD ni se permite declarar uno cerrado si falta el gate conjunto.
P2 conserva los timeboxes individuales de §7 y solo es elegible tras Partes 1-7 y smoke local
preliminar verdes. PRD-015 obliga a repetir el gate después de Bloques 4-6, repetición que el total
original de §4 no presupuestó: reservar otros 45 min de QA y cortar P2 primero si falta tiempo. No
comprimir ese re-gate dentro de la hora del Bloque 8. Esta es la única repetición deliberada y
valida el HEAD posterior a Bloques 4-6/P2.

### Parte 1 — PRD-009 (Bloque 1, 2 h; nunca cortar)

Backend: `backend/app/sim/inventory.py` (can_afford estricto, apply_execution transaccional →
`bool`), `backend/app/main.py` (reordenar captura: aplicar → contar/medir/publicar),
`backend/app/backtest/replay.py`, `backend/app/validate/report.py` (respetar/afirmar el bool),
`backend/app/store/config_store.py` (preparar/aplicar separados; comparación “solo si difiere”),
`backend/app/api/v1/router.py` (409 `venue_restart_required`, 422 venue desconocido, commit
ordenado, reseed condicional). Frontend: `frontend/components/ConfigPanel.tsx` (switch
deshabilitado, textos, rama 409). Tests: `backend/tests/test_inventory.py` (tests 1-3 y 4b;
invertir `test_apply_execution_ignores_unknown_venue_leg`),
`backend/tests/test_prioritizer.py` (invertir `test_can_afford_unknown_venue_not_blocked`),
**nuevo** `backend/tests/test_config_api.py` (4a, 5, 6; limpiar cache de `get_settings`),
`backend/tests/test_config_store.py`.

**Gate 1:** dirigida
`cd backend && uv run pytest tests/test_inventory.py tests/test_prioritizer.py tests/test_config_api.py tests/test_config_store.py tests/test_validation.py -q`
(los seis tests obligatorios pasan y fallaban antes; `test_validation.py` cubre la reconciliación
`$109.75` con Δ 0.0000) → `GATE-BACKEND` completo.

### Parte 2 — PRD-010 (tramo auth del Bloque 2 compartido, 2 h 30 min totales)

`frontend/lib/config.ts` ya existe (exporta `API_BASE`): **añadir** `READ_ONLY`, no crear
archivo. Modificar además:
`frontend/components/ControlPanel.tsx`, `frontend/components/ConfigPanel.tsx` (segunda pasada:
rama read-only + distinción 401/409/red), `frontend/components/StoragePanel.tsx`,
`frontend/components/StrategyLabPanel.tsx` (return tras `onApply`, badge `WHAT-IF LOCAL · NO
PERSISTE`), `frontend/components/OpportunityExplainDrawer.tsx` (bloquear preflight/test-order),
`frontend/app/page.tsx` (badge `READ-ONLY DEMO`). Deploy:
`deploy/standalone/Dockerfile.frontend` (ARG default 1 + validación `0|1` + ENV antes del build),
`deploy/standalone/docker-compose.yml` (`build.args`).

**Gate 2:** `GATE-FRONTEND-RO` (build sin flag = superficie completa, build con
`NEXT_PUBLIC_READ_ONLY=1` = read-only); inventario RF-009 repetido (0 mutaciones fuera de la
matriz); `GATE-BACKEND` completo (re-verifica Gate 1 — esta parte no toca backend, pero
ConfigPanel comparte archivo con 009 y el gate acumulado lo confirma).

### Parte 3 — PRD-011 (núcleo dentro del Bloque 2 compartido + Bloque 2b de 45 min)

`deploy/Dockerfile` (uv frozen dos fases, `/data` 10001:10001, base por digest),
`deploy/standalone/docker-compose.yml` (volumen `arb-data`, `ARB_DB_URL`, healthcheck,
`service_healthy`), `deploy/docker-compose.yml` (mismo par volumen/URL, sin gates),
`deploy/standalone/Dockerfile.frontend` (digest, puerto 3100 único),
`backend/app/api/health.py:91` (agregación de estados terminales) + tests de health
(`finished`/`cancelled`/`failed`/writer muerto/sano), `deploy/README.md` (preflight 0b, backup/
restore, rollback), y en commit **aislado** `backend/pyproject.toml` + `backend/uv.lock`
(RF-009 deps: integrar todo o revertir todo en 45 min; excepción Next documentada, RF-010).

**Gate 3:** dirigida `cd backend && uv run pytest tests/test_health.py -q` →
`cd backend && uv lock --check` → `GATE-BACKEND` completo (re-verifica 1..2); si Docker local está
habilitado: `GATE-COMPOSE` completo más el gate del bundle read-only RF-010 (cierra el gate de
Parte 2 a nivel imagen). Si Compose no está habilitado, PRD-011 queda `Pendiente` y el release de
PRD-015 queda `BLOQUEADO`; se conservan los gates no-Docker y no se avanza a P2/tag/evidencia final.

### Parte 4 — Gate preliminar (Bloque 3, 45 min — PRD-015 RF-001..004)

Sin archivos de producto: worktree detached del HEAD vigente (receta canónica de §4) y dentro de
él `GATE-BACKEND` (RF-002) + `GATE-FRONTEND-RO` (RF-003) + `GATE-COMPOSE` (RF-004). Si Compose no
está disponible, registrar este gate `BLOQUEADO`, no verde; se puede
continuar la implementación de Partes 5-7, pero no P2/release. **Sin tag.** Es la línea base
acumulada 1..3.

### Parte 5 — PRD-012 (Bloque 4, 90 min)

Backend: `backend/app/sim/rebalancer.py` (`import time`; `ts=time.time()` en línea 46),
`backend/tests/test_inventory.py` (`test_rebalance_event_has_wall_clock_epoch_ts`). Frontend:
`frontend/hooks/useStream.ts` (tipos `BalanceItem`/`InventorySkew`/`RebalanceEvent`/
`RebalanceSummary`/`InventorySnapshot`/`BalancesResponse`; ampliar `Pnl`; fetch de `/balances` en
`pullLight`; coste de decisión), **nuevo** `frontend/components/InventoryPanel.tsx`,
`frontend/app/page.tsx` (montar como primer hijo de la pestaña Operación).

**Gate 4:** dirigida `cd backend && uv run pytest tests/test_inventory.py -q` (incluye el test
del epoch nuevo) → `GATE-BACKEND` completo (re-verifica 1..3) → `GATE-FRONTEND` + smoke manual de
los cinco casos (completo, cero eventos, vacío, parcial, caído) + cadencia ≤4 requests/15 s.

### Parte 6 — PRD-013 (Bloque 5, 60 min; corte mínimo definido)

Backend: `backend/app/demo/fallback.py` (`scenario_run_id` + `scenario_started_at` en
`_emit_jury_next` cuando `changed`; exponer en `status()`), `backend/app/demo/scenarios.py`
(contratos `expected_result` completos/retirados; `repeats_per_scenario=45`; RF-003B para
`order_failure`). Frontend: `frontend/hooks/useStream.ts` (ventana `ScenarioObservationWindow` en
`useRef`; `t_recv` en la interfaz `Opportunity`), `frontend/components/ControlPanel.tsx` (elección
concreta para no crear otra superficie: solo renderiza `esperado`/`observado`; no guarda estado ni
recalcula deltas). Actualizar `docs/guion-demo-jurado.md` con RF-003B y unwind replay antes del
gate. Tests:
`test_scenario_run_id_increments_on_transition_and_same_name_reselection`,
`test_repeated_frames_keep_scenario_run_id`,
`test_jury_window_is_longer_than_two_metrics_intervals`, catálogo parametrizado.

**Gate 5:** dirigida `cd backend && uv run pytest tests/test_demo.py -q` (tests nuevos incluidos)
→ `GATE-BACKEND` completo (re-verifica 1..5, incluida la demo determinista de 009/012) →
`GATE-FRONTEND` (esta parte toca `useStream.ts` y `ControlPanel.tsx`) + smoke instrumentado de la
ventana (baseline posterior, señal directa, delta negativo, fuentes inconsistentes y reconexión).
Un delta de métricas aislado no aprueba un claim. Al minuto 60 no queda claim provisional ni
harness parcial.

### Parte 7 — PRD-014 (Bloque 6, 45 min; orden interno 1→2→4→3)

`frontend/components/EdgeWaterfall.tsx` (badge `CASO CANÓNICO`),
`frontend/components/BusinessThesisCard.tsx` (slot metadatos, mode/ruta, muestra forward, help),
`frontend/components/OpportunityExplainDrawer.tsx` (veredicto `OPERAR`/`NO OPERAR`),
`frontend/components/ForwardFanChart.tsx` (`RECORDING → REPLAY`), `frontend/app/page.tsx`
(Equity `accent="neutral"`). Backend: sin cambios.

Al minuto 45, si no cerró todo, conservar únicamente cambios 1, 2 y 4 ya verdes (caso canónico,
modo/ruta y veredicto); retirar cualquier cambio parcial de muestra forward o Equity. No dejar una
variante intermedia que contradiga la regla de corte de PRD-014.

**Gate 6:** `GATE-FRONTEND` + smoke escala de grises y 360 px + búsqueda estática
(`asof_monotonic` fuera de APIs de fecha) + `GATE-BACKEND` completo (re-verifica 1..6; esta parte
no toca backend, el gate acumulado lo confirma).

### Parte 8 — P2 selectivo + re-gate final + evidencia (PRD-015; presupuestos separados)

P2 elegible solo con Partes 1-7, Compose y smoke preliminar local verdes; cada ítem conserva su
timebox de §7 y tiene re-gate inmediato: cifras 481→reales
(`documentos/ultima_fase_claude.md`), 5→7 escenarios (`docs/guion-demo-jurado.md`,
`backend/app/demo/scenarios.py`), headers no-ASCII → 401 (`backend/app/api/security.py`,
`backend/app/api/v1/router.py`), Reset comunica alcance
(`frontend/components/StrategyLabPanel.tsx`), locale numérico (`OpportunitiesTable.tsx`,
`FunnelPanel.tsx`).

**Gate final (RF-007; repetición del Bloque 3, no parte de la hora del Bloque 8):** worktree
detached del HEAD final (receta de §4, distinto del usado en la Parte 4) → `GATE-BACKEND` +
`GATE-FRONTEND-RO` + `GATE-COMPOSE` completos + smoke preliminar →
`git tag -a candidato-12jul -m "Candidato 12-jul: gates verdes desde worktree limpio" "$SHA"`
sobre el SHA probado. **Bloque 8 (1 h):** paquete de evidencia
(`docs/evidencia-12jul/`, capturas con pie fecha/tag/SHA/`JURY · LOCAL`, export validado con `jq`
sin secretos, `validation.json` con `computed=109.75` y `abs(diff)≤0.0001`, audits, video 80-100 s,
smoke RF-009 7/7, `SHA256SUMS`) → commit de evidencia posterior al tag. Este gate ES la
aceptación acumulada: el re-gate previo al tag cubre Partes 1-7 y P2; el smoke y la integridad del
paquete cierran la Parte 8. Un fallo posterior al tag rechaza ese tag y reinicia la secuencia con
un candidato `.N`.

### Colisiones exhaustivas de archivos entre PRDs

La matriz cuenta **archivos que dos o más PRDs autorizan modificar esta noche**. Una lectura para
gate, una referencia `archivo:línea` o la mera comprobación de que un archivo está tracked no se
considera “tocar”. P2 cuenta solo para los cinco ítems elegibles de PRD-015 RF-006; los P2
explícitamente diferidos no entran. Con ese criterio, esta es la intersección completa de las
listas de cambios de PRD-009..015:

| Archivo | PRDs / partes | Regla de integración y orden |
|---|---|---|
| `frontend/components/ConfigPanel.tsx` | 009/P1, 010/P2 | 009 fija 409 y textos de reinicio; 010 preserva 409, distingue 401/red y bloquea antes de emitir en read-only |
| `frontend/components/ControlPanel.tsx` | 010/P2, 013/P6 | 010 bloquea mutaciones pero conserva estado/export; 013 añade render puro de esperado/observado sin rehabilitar chips |
| `frontend/components/StrategyLabPanel.tsx` | 010/P2, 015/P2-4 | primero rama what-if no persistente; después copy de Reset “local/no persiste”; re-gate frontend inmediato |
| `frontend/components/OpportunityExplainDrawer.tsx` | 010/P2, 014/P7 | 010 bloquea preflight/test-order; 014 añade veredicto sin tocar esa guardia |
| `frontend/app/page.tsx` | 010/P2, 012/P5, 014/P7 | badge read-only → montaje de inventario → Equity neutral; conservar los tres cambios |
| `frontend/hooks/useStream.ts` | 012/P5, 013/P6 | 012 toca primero (`/balances` + frescura en `pullLight`); 013 añade después la ventana de escenario reutilizando dueño, refs, abort y cleanup, sin crear otro intervalo ni alterar el fetch de balances |
| `deploy/standalone/Dockerfile.frontend` | 010/P2, 011/P3 | 010 fija ARG/ENV/validación; 011 conserva eso al fijar digest y autoridad única del puerto 3100 |
| `deploy/standalone/docker-compose.yml` | 010/P2, 011/P3 | conservar `build.args=1`; añadir volumen/URL/health/gates sin mover el flag a runtime |
| `backend/tests/test_inventory.py` | 009/P1, 012/P5 | regresiones de atomicidad primero; test de epoch después; nunca revertir los dos tests permisivos ya invertidos |
| `backend/app/api/v1/router.py` | 009/P1, 015/P2-3 | 009 implementa config atómica/409; P2 limita el cambio a manejo no-ASCII del control token y ejecuta suite backend completa |
| `backend/app/demo/scenarios.py` | 013/P6, 015/P2-2 | 013 define siete contratos/cadencia; P2 corrige la docstring/cifra sin cambiar fixtures ni `expected_result` |
| `docs/guion-demo-jurado.md` | 013/P6, 015/P2-2 | 013 registra RF-003B y unwind replay; P2 sincroniza cinco→siete con catálogo/API/tests; una sola edición final coherente |

## 5. Riesgos residuales y mitigaciones

| # | Riesgo residual | Mitigación |
|---:|---|---|
| 1 | Rollback del ledger queda incompleto si se añaden campos contables nuevos | snapshot/restore de los cuatro campos por venue + `realized_pnl`; test compara el fingerprint contable completo definido por 009 |
| 2 | Un caller futuro ignora el `bool` de `apply_execution` | búsqueda global de callers en el gate + tests de no-propagación en live/replay/validación |
| 3 | Docker/Compose v2 no se habilitan esta noche | ejecutar y conservar gates no-Docker, marcar 011 `Pendiente` y 015 RF-004 `BLOQUEADO`; detener antes de P2/tag/evidencia, sin usar el server como sustituto |
| 4 | Imagen frontend construida fuera de la ruta oficial muestra superficie completa | backend sigue rechazando con 401; gate RF-010 (artefacto+DOM+token+Network) la declara NO-GO; rebuild sin cache obligatorio |
| 5 | Parches Python no resuelven (techos de `ccxt`/`fastapi` sobre `aiohttp`/`starlette`) | commit aislado: bump coordinado en el mismo commit o revert íntegro + excepción registrada; nunca lock parcial |
| 6 | Colisión 009/010 en `ConfigPanel`: con token configurado el PUT da 401 antes del 409 | manejo de error ramificado por status en la rama completa; en read-only la petición no se emite |
| 7 | Reconexión SSE pierde la transición de escenario y la demo muestra `absent` ante el jurado | es el comportamiento honesto; esperar una activación con `run_id` nuevo (cada escenario dura ≥2.25 s con defaults; no prometer latencia de ciclo completo) |
| 8 | `keepMounted={false}` desmonta paneles y tienta a duplicar fetches | AD-4: todo I/O y estado en `useStream`; smoke verifica cero requests duplicados al navegar |
| 9 | El smoke o la generación de evidencia descubre un fallo después del tag | tag inmutable: marcar RECHAZADO, fix en commit nuevo, suite completa y candidato `.N`; P2 siempre ocurre antes del tag |
| 10 | Vulnerabilidades de Next 14 permanecen (1 high + 1 moderate) | excepción documentada con impacto/mitigación/fecha (RF-010 de 011, §13 del plan); read-only + firewall + apagado post-demo reducen exposición sin declararla inexplotable |
| 11 | Timebox insuficiente en Bloques 5-6 | reglas de corte precompiladas: 013 tiene corte mínimo definido (identidad+cadencia+dos líneas+RF-003B); 014 conserva cambios 1-2+veredicto; nada de esto viola prohibición alguna |
| 12 | Evidencia generada desde un SHA distinto al del tag | stack de evidencia se levanta desde el worktree del tag; SHA visible en cada artefacto; `git rev-list -n1` comprobado; `SHA256SUMS` |
