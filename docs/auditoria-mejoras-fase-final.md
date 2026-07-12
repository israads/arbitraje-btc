# Auditoría integral y plan de mejoras — Fase final

> Fecha: 2026-07-01 · Ventana restante: **11 días** (cierre del comité: domingo 12-jul-2026 23:59)
>
> Metodología: auditoría en cuatro frentes paralelos (frontend/UX, backend/procesos, seguridad,
> contexto del concurso), con evidencia `archivo:línea`. Cada hallazgo trae mitigación concreta y
> está mapeado al criterio del comité que impacta.

## Criterios del comité (el marco de priorización)

Según `documentos/ultima_fase_claude.md:57-64`, el jurado evalúa:

| # | Criterio | Peso declarado |
|---|---|---|
| C1 | Profundidad y parametrización | "El factor que más diferenciará los proyectos" |
| C2 | Robustez ante escenarios adversos (falla de orden, falta de liquidez) | Alto |
| C3 | Gestión de wallets y rebalanceo | Alto |
| C4 | Calidad de interfaz/visualización | Alto |
| C5 | Documentación y código | Base |

La métrica norte del producto (`docs/prd/README.md:99-104`): **porcentaje de decisiones explicables
y reproducibles sobre datos íntegros**, entendibles por el jurado en < 90 segundos.

**Estado actual**: el grueso del roadmap táctico P1-P5 ya está cerrado (Strategy Lab, what-if,
Naive-vs-Edge, retención BD, escenarios por nombre, MCP, tour guiado — ver `docs/CONTEXTO.md`).
Esta auditoría encuentra que las mejoras de mayor retorno restantes son de **robustez visible,
honestidad del indicador y pulido de demo**, no de features nuevas.

---

## 1. Experiencia de usuario (UX) e interfaz (UI)

### Fortalezas confirmadas (defendibles ante el jurado)

- **Pipeline de render ejemplar**: buffer en refs + `requestAnimationFrame` con dirty-flags por
  slice (`frontend/hooks/useStream.ts:453-584`). Un tick de quote a 10/s no re-renderiza tablas ni
  métricas ajenas. Híbrido SSE-push + polling backstop con `AbortController` StrictMode-safe.
- **Charts dependency-free en SVG** y `LiveLineChart` incremental (`series.update()`, no `setData`).
- **`ProbabilityLattice` (Galton board)**: `IntersectionObserver` para no quemar CPU fuera de
  viewport, `prefers-reduced-motion` con render estático, `aria-label` descriptivo
  (`ProbabilityLattice.tsx:196-218,276-278`). Es el patrón de referencia a replicar.
- **Capa pedagógica** (InfoHint + GuideDrawer + GuidedTour con navegación por teclado): exactamente
  lo que necesita un jurado sin contexto.
- Narrativa de pestañas deliberada (Resumen → Correctitud → Proyección → Operación), tipografía
  auto-hospedada sin FOUT, `tabular-nums`, flash tick-up/down, estados vacíos en casi todos los paneles.

### Debilidades y mejoras (por impacto)

#### UX-1 · Aplicar parámetros del Strategy Lab reconecta el stream SSE — ALTO
El `useEffect` de `useStream` depende de los 6 parámetros de estrategia
(`frontend/hooks/useStream.ts:628-635`); al aplicarlos, el cleanup cierra el `EventSource` y lo
reabre: el status parpadea a `connecting`/`reconnecting` y se re-piden snapshots deterministas
(incluida `validation`, que nunca cambia). **Es un bug de UX visible justo durante la demo del
what-if**, la feature estrella de C1.

**Fix**: dividir en dos effects — SSE en uno sin dependencias de params; los `pullHeavy()`
(projection/capacity/forward/survival) en otro que sí dependa de ellos.

#### UX-2 · No hay detección de staleness: "EN VIVO" puede mentir — ALTO
`ConnStatus` define `stale` ("SIN DATOS") y `replay` (`app/page.tsx:53-54`) pero `setStatus` solo
emite `connecting`/`live`/`reconnecting` (`useStream.ts:483-486`). Si el backend deja de emitir con
el socket abierto, el header dice "EN VIVO" indefinidamente. En un producto cuya tesis es la
honestidad, el indicador de conexión no puede mentir.

**Fix**: watchdog client-side — timestamp del último evento SSE → `stale` tras N segundos.
Convierte un estado decorativo en uno honesto. Coste: bajo.

#### UX-3 · Acciones críticas fallan en silencio — ALTO
`<Notifications>` está montado (`app/layout.tsx:8,43`) pero jamás se usa. Kill switch/Resume
(`ControlPanel.tsx:43-53`, catch vacío), Export session (`ControlPanel.tsx:72-76`, `return` mudo si
`!res.ok`), guardar config (`ConfigPanel.tsx:103`) y aplicar Strategy Lab
(`StrategyLabPanel.tsx:48`) no dan feedback de error ni de éxito. Si el jurado pulsa "Export" y
falla, no ve nada.

**Fix**: toasts de éxito/error en las 5 acciones. Coste: muy bajo, visibilidad: muy alta.

#### UX-4 · Sin error boundary ni estado de error de datos — ALTO
No existe `error.tsx`/`global-error.tsx`. Todos los fetch hacen `.catch(() => undefined)`: un 500
persistente deja paneles en "Cargando…" para siempre (`EdgeWaterfall.tsx:38-41`), y un chart que
lance con datos malformados tira la página completa (pantalla blanca).

**Fix**: `app/global-error.tsx` + distinguir "cargando" / "sin datos" / "falló" en cada panel.

#### UX-5 · Accesibilidad de charts inconsistente — MEDIO
`CapacityCurve.tsx:75` y `ForwardFanChart.tsx:100` tienen `role="img"` **sin `aria-label`**;
`EdgeWaterfall` y `NaiveVsEdgePanel` son `<Box>` puros, invisibles a lectores de pantalla. Ejes SVG
a `rgba(255,255,255,0.4)` en 9px fallan WCAG AA (`CapacityCurve.tsx:93-95`).

**Fix**: replicar el patrón de `ProbabilityLattice` (aria-label con resumen numérico) y subir el
contraste de ejes de `0.4` a `~0.62`. La palabra "accesible" está en el enunciado del challenge —
esto es evidencia directa para C4.

#### UX-6 · Responsive: métricas y badge DEMO desaparecen en móvil — MEDIO
`HeaderStats` es `visibleFrom="md"` (`page.tsx:119`) y el badge **DEMO DATA** es `visibleFrom="xs"`
(`page.tsx:243`): en móvil pequeño el indicador de datos simulados desaparece del header. Un jurado
que abra en móvil puede confundir datos demo con live — riesgo directo a la narrativa de honestidad.

**Fix**: badge DEMO visible en `base`; métricas de header en fila colapsable.

#### UX-7 · `keepMounted={false}` pierde histórico de sparklines — MEDIO
Al cambiar de pestaña (`page.tsx:306`) los `LiveLineChart` de Resumen pierden todo su histórico y
el Galton board reinicia. **Fix**: `keepMounted` selectivo para los charts en vivo.

#### UX-8 · Consistencia de idioma/locale — BAJO
`lang="es"` con títulos en inglés ("Strategy Lab", "Kill switch") y locale mixto: números `en-US`,
horas `es-MX` (`WinsPanel.tsx:20`). Defendible como jerga quant, pero decidirlo explícitamente
(glosario en la Guía que justifique los anglicismos) y unificar el locale numérico.

---

## 2. Modelo de negocio

### Lo que ya está bien planteado

La narrativa de negocio de la segunda fase (`docs/respuesta-segunda-fase.md`) es el activo más
diferenciador del proyecto porque es **contraintuitiva y honesta**: entre exchanges grandes, BTC es
demasiado eficiente (un gap de +$97 se vuelve negativo tras peg y fees). El negocio no está en
velocidad sino en **estructura de costes y fricción**:

1. **Fees institucionales**: el mismo trade que pierde en retail deja ~$35 netos/BTC con comisiones
   negociadas. El Break-even Frontier ya lo demuestra visualmente.
2. **Corredor mexicano** (Bitso/MXN, MXNB, primas regionales): cobrar por mover capital y asumir
   settlement, no por ser el más rápido. Módulo regional-MXN ya existe (opt-in).
3. **Mid-caps líquidos** (SOL, XRP, DOGE…): mejor ratio liquidez/ineficiencia que BTC.
4. **Metodología transferible**: pairs trading (z-score), premium/descuento de ETFs, acciones SIC
   (el error "USDT=1 USD" ≡ asumir FX fijo).

### Mejoras recomendadas

#### BN-1 · Hacer visible el modelo de negocio EN el dashboard — ALTO
Hoy la historia de negocio vive en docs que el jurado quizá no lea. El dashboard ya tiene las
piezas (frontier por fee tier, capacity curve, panel MXN opt-in) pero no las conecta en una
narrativa "dónde SÍ hay negocio". Propuesta de bajo coste: una tarjeta/sección "Tesis de negocio"
en la pestaña Resumen con los 3 números que la cuentan: *retail: −$X/BTC · institucional: +$35/BTC ·
corredor MXN: prima Y bps*, cada uno linkeando al panel que lo demuestra. Convierte C1+C4 en
argumento comercial.

#### BN-2 · Responder "¿esto gana dinero?" con una pantalla, no un párrafo — ALTO
Es la pregunta garantizada del jurado (`documentos/ultima_fase_codex.md:684-731`). La respuesta
correcta ya está definida (honestidad: medimos capturabilidad, no prometemos retorno). El
WinsPanel + Forward Fan Chart la responden, pero conviene un elemento explícito: "P(P&L>0) = X%,
drawdown esperado Y, bajo fees Z" — la respuesta ensayada del guion, renderizada.

#### BN-3 · Cerrar la brecha alcance-negocio con honestidad explícita — MEDIO
El core implementado es cross-exchange BTC spot; MXN/triangular/funding son opt-in sin UI dedicada
(deliberado). En vez de construir UI nueva a 11 días del cierre, documentar la decisión: "el core
demuestra la metodología; los módulos opt-in demuestran que la arquitectura la extiende sin mezclar
riesgos". Ya hay endpoints y tests — es un párrafo en README + una respuesta ensayada.

#### BN-4 · Testnet honesto (decisión pendiente crítica) — ALTO
El adapter Binance actual es offline/determinista pero la UI dice "Binance Spot Testnet"
(`documentos/ultima_fase_*.md`, P6). A 11 días, la recomendación de los propios planes es la
correcta: **renombrar a "dry-run local (determinista)"** salvo que sobre tiempo para HMAC real
contra Binance Spot Testnet. Un jurado técnico que detecte la discrepancia daña el activo más
valioso del proyecto: la credibilidad de su honestidad.

---

## 3. Ejecución de procesos (arquitectura de runtime)

### Fortalezas confirmadas

- **Backpressure coherente en las 3 fronteras**: `BoundedQueue` drop-oldest (`app/bus/queue.py:19-26`),
  colas SSE por-cliente acotadas (`app/stream/hub.py:20-31`), cola de persistencia que descarta sin
  bloquear el hot path (`app/store/writer.py:80,152-157`). Dato fresco > completitud: política
  correcta para trading.
- **Resiliencia de ingesta**: backoff exponencial con reset, clasificación de errores permanentes
  por venue, `gather(return_exceptions=True)` aísla venues (`app/ingest/exchange_ingestor.py:42-99`).
- **Proyecciones pesadas fuera del event loop**: `run_in_threadpool` + cache TTL + semáforo
  (`app/api/v1/router.py:44-58`); forward Monte Carlo vectorizado en numpy.
- **BatchWriter robusto**: flush con `asyncio.shield`, fallback por-registro ante lote corrupto
  (`writer.py:224-295`).
- Núcleo del motor puro y determinista (sin red ni reloj), saneamiento NaN/inf sistemático.

### Riesgos y mejoras (por impacto)

#### PR-1 · Muerte silenciosa de tasks: el motor no está supervisado — ALTO
Las tasks del pipeline se crean con `create_task` y solo se esperan en shutdown
(`app/main.py:286-313`). `run_engine` **no tiene try/except en su bucle por-oportunidad**
(`app/engine/__init__.py`): una excepción no prevista mata la task del motor **en silencio** y la
detección se detiene el resto de la sesión. `Watchdog.run` tiene el mismo patrón
(`app/risk/watchdog.py:56-67`), a diferencia de breaker/demo/writer que sí protegen su bucle.
Agravante: `/health` no comprueba liveness de ninguna task (`BatchWriter.is_alive()` existe en
`writer.py:168-171` pero no se expone).

**Fix** (coste bajo, impacto máximo en C2): try/except en los bucles de `run_engine` y
`Watchdog.run` (re-lanzar `CancelledError`, loguear y continuar); exponer `task.done()` de cada
task nombrada en `/health`. Esto además se convierte en **evidencia demostrable de robustez**: el
health check que muestra el estado de cada subsistema es exactamente lo que C2 pide.

#### PR-2 · La retención no recupera disco: `arbitraje.db` sigue en 14 GB — ALTO
`db_vacuum_on_prune=False` por defecto (`app/config.py:239`) y `prune_old_rows` solo hace `DELETE`
(`app/store/retention.py:162-168`). En SQLite, `DELETE` no reduce el archivo. **Verificado: el
archivo sigue ocupando 14 GB** aunque la retención acote el crecimiento lógico (el propio código lo
sabe: `live_bytes` excluye freelist, `retention.py:114-119`).

**Fix**: un `VACUUM` puntual para revertir el archivo actual; después `PRAGMA
auto_vacuum=INCREMENTAL` + `incremental_vacuum` periódico (no bloquea como el VACUUM completo).
Documentar que en operación real `db_vacuum_on_prune` debe estar activo.

#### PR-3 · SQLite sin WAL ni PRAGMAs — MEDIO
`make_engine` (`app/store/db.py:119-128`) no configura `journal_mode=WAL` ni
`synchronous=NORMAL`: lectores REST y writer se bloquean mutuamente y cada transacción hace fsync
completo. **Fix**: PRAGMAs en `init_db` vía connect event. Dos líneas, mejora medible.

#### PR-4 · Hot path por-tick sin yields — MEDIO (defensivo)
`run_engine` procesa todas las opps de un tick como bloque síncrono sin un solo `await`
(detección → simulate → equity → metrics → publish → persist). Con 3 venues es rápido, pero un
burst de cruces (mercado convulso, justo cuando importa) congela el loop durante todo el lote,
retrasando ingesta y SSE. **Fix**: `await asyncio.sleep(0)` cada K oportunidades o tope de opps
por tick.

#### PR-5 · Desconexión SSE detectada con retardo — BAJO
`request.is_disconnected()` se comprueba después de `await q.get()` (`router.py:334-338`): con cola
vacía, la limpieza espera al siguiente evento o al ping. Menor; documentar o ajustar timeout de ping.

---

## 4. Optimización de código y rendimiento

### Estado

La calidad base es alta y verificable: 498 tests, cobertura >92%, ruff limpio, mypy `--strict`
limpio, docstrings que explican el *porqué* (no doble-conteo del embudo, semántica de unwind,
causalidad del z-score). La separación pura/impura hace el núcleo altamente testeable. **No hay
deuda estructural que justifique refactors a 11 días del cierre.** Lo accionable:

#### CO-1 · `_PROJECTION_CACHE` sin cota: fuga de memoria real — ALTO
Dict global (`router.py:40`) cuyas claves incluyen parámetros libres del cliente (`latency_ms`,
`fee_bps`, `n_paths`, `n_configs`). Solo hay TTL de frescura; **las entradas viejas nunca se
eliminan**. Variar query params genera claves ilimitadas con valores grandes (`ForwardResult`) →
crecimiento de memoria no acotado; vector de DoS trivial.

**Fix**: LRU acotado (`OrderedDict` con tope + purga de expiradas al escribir). Coste: ~20 líneas.

#### CO-2 · Código muerto de estrategias — MEDIO
`strategies/{spatial,stat_z}.py` son adapters sin consumidor; `strategies/funding.py` devuelve
siempre `[]` (planes `ultima_fase_*.md`, H3). Un revisor de código lo encontrará. **Fix**: wirear o
borrar antes del cierre; si se conservan, docstring que declare su estado.

#### CO-3 · Sincronizar README/badges con la realidad — BAJO (pero es C5 directo)
Badges dicen 484 tests / 92.45%; CONTEXTO.md dice 498. Verificar el número real y actualizar
README, badges y guion. Inconsistencias numéricas son lo primero que un comité detecta.

#### CO-4 · numpy en bucle por-par del z-score — BAJO (vigilar)
`statz.on_book` recalcula `mean/std` sobre ventana de 200 por par y book (`statz.py:177-179`).
Trivial a 3 venues; se vuelve relevante si crecen venues/estrategias. Anotar como límite conocido.

---

## 5. Medidas de seguridad

Contexto: simulación sin dinero real (`execution_mode="disabled"` por defecto) — pero el deploy
standalone está **expuesto públicamente**, donde estos hallazgos sí importan.

### Positivo confirmado

Sin secretos en git ni en CI; Next.js lockeado en 14.2.35 (post CVE-2025-29927); respuestas de API
con listas blancas que excluyen tokens/credenciales (`router.py:97-136`); rate limiter bien
diseñado (peer IP real, cota de IPs); validación Pydantic con bounds en todo (limits [1,1000],
`n_paths ≤ 20000`); SQLAlchemy con binding — sin inyección SQL; logging sin datos sensibles.

### Hallazgos (por severidad)

#### SG-1 · Control plane sin auth por defecto en el deploy expuesto — ALTA
`control_token: str = ""` (`app/config.py:114`) + `require_control_token` que deja pasar todo con
token vacío (`router.py:61-70`). En `deploy/standalone/docker-compose.yml:17` el token es
`${ARB_CONTROL_TOKEN:-}` → **vacío si no se define**, sobre un stack público. Cualquiera en
Internet puede disparar kill-switch, forzar demo, purgar la BD (`PATCH /storage/retention`) o
alterar la config en caliente (`PUT /config/sim` re-siembra el portfolio).

**Fix**: fallar el arranque si `env=="prod"` y token vacío; quitar el default vacío de la compose
standalone (variable requerida o secreto generado). Verificar el token en el server desplegado.

#### SG-2 · SSE `/stream` sin auth ni tope de conexiones (DoS) — MEDIA
`/api/v1/stream` está exento del `ApiGuardMiddleware` (`app/api/security.py:20-23`) y `StreamHub`
no limita clientes (`hub.py:15-44`): N conexiones = N colas de 500 sin cota, con
`timeout-keep-alive 300` y `proxy_read_timeout 3600s`. **Fix**: cap de conexiones concurrentes en
`subscribe()` (+ límite por IP) y rate-limit al establecimiento del stream.

#### SG-3 · Backend publicado directo sin proxy/TLS — MEDIA
`deploy/docker-compose.yml:11-12` publica `8000:8000` al host sin nginx/TLS (la compose standalone
sí lo hace bien). **Fix**: no publicar 8000 en prod; bindear a 127.0.0.1 o pasar por nginx.

#### SG-4 · Contenedores como root + sin `.dockerignore` — MEDIA
Dockerfiles sin `USER`; `COPY backend/ /app/` sin `.dockerignore` puede hornear `arbitraje.db`
(14 GB), `.coverage` o un `.env` con claves testnet en la imagen. **Fix**: usuario no privilegiado +
`.dockerignore` (`*.db`, `.env*`, `.coverage`, `__pycache__`, `.venv`).

#### SG-5 · Sin cabeceras de seguridad HTTP — MEDIA
Ni `headers()` en Next ni `add_header` en nginx: faltan HSTS, `X-Frame-Options`,
`X-Content-Type-Options`, CSP básica. **Fix**: bloque `add_header` en nginx del standalone.

#### SG-6 · CORS con `allow_credentials=True` innecesario — MEDIA
`main.py:370-376`. La auth es por header, no cookies. **Fix**: `allow_credentials=False` y acotar
métodos/headers.

#### SG-7 · Menores — BAJA
Comparación de tokens variable-time (`security.py:56`, `router.py:69` → usar
`hmac.compare_digest`); `/metrics` y `/docs` sin auth en público; IP de infraestructura hardcodeada
en la compose; tests de auth no cubren todos los endpoints mutables (añadir test parametrizado
sobre todo endpoint con `Depends(require_control_token)`).

---

## Estado de ejecución (1-jul-2026)

**Ejecutado y verificado** (507 tests verdes, ruff + mypy --strict limpios; frontend lint + build):

- **PR-1** ✅ try/except en `run_engine` y `Watchdog.run`; `/health` expone `tasks` (liveness
  por subsistema, incl. writer) y degrada `status` a `degraded` si alguna murió. Tests nuevos
  en `tests/test_robustness_edges.py`.
- **PR-2** ✅ `arbitraje.db` local: 14 GB → 37 KB (poda según política + `VACUUM` único);
  `auto_vacuum=INCREMENTAL` activo. La poda periódica ahora ejecuta `incremental_vacuum`
  (libera disco sin el bloqueo del VACUUM completo).
- **PR-3** ✅ PRAGMAs por conexión en `store/db.py`: WAL, `synchronous=NORMAL`, `busy_timeout`.
- **PR-4** ✅ `run_engine` cede el event loop cada 64 opps dentro de un tick.
- **CO-1** ✅ `_PROJECTION_CACHE` es LRU acotado (64 entradas + purga por TTL al escribir).
- **CO-2** ✅ docstrings de estado en `strategies/{spatial,stat_z,funding}.py` (contrato
  PRD-008 deliberado, no código muerto accidental).
- **CO-3** ✅ README/CONTEXTO sincronizados: 507 tests, cobertura 91.03%.
- **SG-1** ✅ `Settings` FALLA el arranque con `env=prod` y token vacío; compose standalone
  exige `ARB_CONTROL_TOKEN` (sin default vacío). Test exhaustivo por introspección: todo
  endpoint con `require_control_token` rechaza 401 sin/con token erróneo.
  ⚠️ Pendiente: el server público (159.89.187.165:8090) no responde — verificar al redeploy.
- **SG-2** ✅ cap de clientes SSE (`sse_max_clients=64`, 503 al exceder).
- **SG-3** ✅ `deploy/docker-compose.yml` bindea 127.0.0.1:8000.
- **SG-4** ✅ `.dockerignore` raíz (excluye `*.db`, `.env*`, caches) + `USER` no-root en ambos
  Dockerfiles.
- **SG-5** ✅ cabeceras X-Frame-Options/nosniff/Referrer-Policy en ambos nginx.conf.
- **SG-6** ✅ CORS sin credenciales y con métodos/headers acotados.
- **SG-7** ✅ `hmac.compare_digest` en token de control y API key.
- **UX-1..UX-7** ✅ (ver detalle por archivo en el repo): SSE ya no se reconecta al aplicar
  Strategy Lab; watchdog de staleness real (`stale` → "SIN DATOS"); toasts en las 5 acciones
  críticas; `error.tsx`/`global-error.tsx` + estados cargando/sin datos/error (`FetchFallback`);
  aria-labels dinámicos y contraste 0.62 en ejes; badge DEMO y métricas visibles en móvil;
  `keepMounted` selectivo en Resumen.
- **BN-4** ✅ UI renombrada: "Preflight de ejecución — Dry-run local (determinista, sin red)".

**Pendiente**: BN-1/BN-2 (tarjeta "Tesis de negocio", en curso), BN-3 (párrafo en README),
UX-8 (glosario/locale — decisión de producto), item 15 (ensayo del guion), verificación del
token en el server desplegado al redeploy.

## Plan de acción priorizado (11 días)

Criterio de orden: (impacto en criterios del comité × visibilidad en demo) / esfuerzo.

### Semana 1 (1-6 jul) — Robustez y honestidad visibles

| # | Acción | Área | Criterio | Esfuerzo |
|---|---|---|---|---|
| 1 | try/except en `run_engine` + `Watchdog.run`; liveness de tasks en `/health` | PR-1 | C2 | 0.5 d |
| 2 | Token de control obligatorio en prod + fix compose standalone (verificar server) | SG-1 | C5 | 0.5 d |
| 3 | Separar SSE de params del Strategy Lab (dos effects) | UX-1 | C1, C4 | 0.5 d |
| 4 | Watchdog de staleness client-side (estado `stale` real) | UX-2 | C4 | 0.5 d |
| 5 | Toasts en kill-switch/resume/export/config/params | UX-3 | C4 | 0.5 d |
| 6 | `VACUUM` del archivo 14 GB + auto_vacuum incremental + WAL PRAGMAs | PR-2, PR-3 | C2 | 0.5 d |
| 7 | LRU acotado en `_PROJECTION_CACHE` | CO-1 | C2 | 0.5 d |
| 8 | Decisión testnet: renombrar a "dry-run local" (o HMAC real si sobra tiempo) | BN-4 | C2, C5 | 0.5 d |

### Semana 2 (7-11 jul) — Pulido de demo y cierre

| # | Acción | Área | Criterio | Esfuerzo |
|---|---|---|---|---|
| 9 | Error boundary + estados de error diferenciados en paneles | UX-4 | C4 | 1 d |
| 10 | Tarjeta "Tesis de negocio" en Resumen (retail vs institucional vs MXN) | BN-1, BN-2 | C1 | 1 d |
| 11 | Accesibilidad: aria-labels en charts + contraste de ejes | UX-5 | C4 | 0.5 d |
| 12 | Cap de conexiones SSE + cabeceras de seguridad en nginx + `.dockerignore` + `USER` | SG-2,4,5 | C5 | 1 d |
| 13 | Badge DEMO visible en móvil + `keepMounted` selectivo | UX-6,7 | C4 | 0.5 d |
| 14 | Limpiar código muerto de estrategias; sincronizar README/badges/tests | CO-2,3 | C5 | 0.5 d |
| 15 | Ensayo del guion con las preguntas esperadas del jurado | — | Todos | 0.5 d |

### Regla de corte

Si algo se retrasa, **sacrificar de abajo hacia arriba dentro de cada semana**, nunca los ítems
1-8: robustez del motor, seguridad del deploy público y honestidad de los indicadores son lo que
un jurado técnico verifica primero, y las tres cosas fallan hoy de formas detectables en minutos
(matar el proceso del engine, curl al kill-switch sin token, desconectar el backend y ver
"EN VIVO").

## Síntesis

El proyecto ya compite en el cuartil alto: motor honesto con fuente única de cálculo, frontend con
ingeniería real de rendimiento, documentación excepcional y una narrativa de negocio contraintuitiva
que ningún bot de spread bruto puede contar. Las debilidades encontradas comparten un patrón: **la
robustez existe en el diseño pero no siempre en el borde** (tasks sin supervisar, indicador EN VIVO
sin watchdog, acciones sin feedback, token opcional en el deploy público). Cerrar ese borde es
barato, verificable y ataca exactamente los dos criterios que el comité declaró decisivos:
parametrización profunda que no parpadea y robustez adversa que se puede demostrar en vivo.
