# Plan de acción final — cierre del comité 12-jul-2026 23:59

> Documento único de ejecución. Fusiona y reemplaza como guía operativa a
> `docs/plan-mejora-integral-2026-07-11.md` (evidencia, hallazgos `archivo:línea`, diseño) y
> `docs/plan-cierre-12jul.md` (secuencia, timeboxes, gates). Ambos quedan como referencia.
>
> Revisión final al 11-jul: hallazgos contrastados contra el código y comandos locales. Este
> documento es la fuente operativa; los otros planes conservan evidencia ampliada.

---

## 1. Decisión ejecutiva y reglas del día

El proyecto ya tiene suficiente profundidad funcional. El último día no se usa para ampliar la
superficie, sino para cerrar cuatro garantías:

1. ninguna ejecución puede reconocer P&L sin aplicar todas sus patas al ledger;
2. el despliegue público no puede mostrar controles que fallen o expongan secretos;
3. configuración, runtime y UI deben representar el mismo estado;
4. la evidencia que el jurado necesita (C1-C5) debe estar visible y ser reproducible.

Reglas fijas del día:

- **Primero correctitud, después acceso y despliegue, después evidencia del criterio, y al
  final solo pulido visual de bajo riesgo.**
- No se añaden estrategias, mercados, dependencias mayores ni cambios arquitectónicos.
- No se redeploya antes de cerrar los bloques 1 y 2 (una build incorrecta desplegada duplica
  trabajo).
- El bloque 0b valida infraestructura, pero **no despliega la aplicación** antes de cerrar P0.
- Los últimos 90 minutos son de QA y ensayo; no se programan features.
- La honestidad va antes que la estética: etiquetar origen de datos precede a cualquier rediseño.
- Ningún tag se llama `candidato` hasta construir y probar exclusivamente desde ese commit.

## 2. Estado verificado (11-jul)

| Gate | Resultado |
|---|---|
| Backend tests | 507 passed |
| Cobertura backend | 91.03% |
| Ruff + mypy strict | limpios |
| TypeScript + Next lint + build | limpios |
| First Load JS | **263 kB**; ruta principal 93.4 kB |
| Worktree | cambios tracked y archivos runtime/tests nuevos todavía untracked |
| Server público `159.89.187.165:8090` | **HTTP 000** en `/` y `/health`; la inspección previa documenta que el deploy fue retirado |
| SQLite local | 36 KB; `auto_vacuum=2` verificado; inspección directa aún da `journal_mode=delete` |
| Persistencia Docker | sin volumen para SQLite |
| Autenticación de controles | backend protegido; frontend no envía `X-Control-Token` → toda mutación protegida da 401 |
| Dependencias | `pip-audit`: 15 hallazgos en 4 paquetes; npm: **1 high + 1 moderate** con `next@14.2.35` |

Fortalezas que no deben ponerse en riesgo: fuente única de costes, walk-the-book compartido,
replay point-in-time, doble entrada e invariantes, demo determinista de 7 escenarios, breakers y
watchdog, explicación por oportunidad, frontier/capacity/forward, export de sesión y runbooks.
Matiz: el simulador implementa fills parciales, leg risk y unwind, pero el wiring live no pasa
`sell_book_t1`; el replay/backtest sí. El guion no afirma unwind live sin enseñar el replay.

Mejoras de Claude ya integradas que se conservan y no se reimplementan: supervisión defensiva del
engine/watchdog, yield del hot path, LRU de proyecciones, WAL/poda incremental, token obligatorio
en prod, cap SSE, contenedores no-root, `.dockerignore`, staleness del cliente, error boundaries,
toasts, estados de error, accesibilidad básica, móvil, tarjeta `Tesis de negocio` y nombre honesto
del dry-run. Todas requieren smoke final, no otro ciclo de rediseño.

**Estado de partida: NO-GO para server público.** La base local es verde, pero R0-R5 siguen
abiertos y el commit candidato todavía no existe.

## 3. Riesgos de cierre

| ID | Riesgo | Severidad | Decisión |
|---|---|---:|---|
| R0 | el deploy público no existe | crítica | redeploy desde cero (bloque 7), preflight de infra temprano (bloque 0b) |
| R1 | P&L inconsistente al deshabilitar un venue | crítica | corregir antes de desplegar (bloque 1) |
| R2 | controles web devuelven 401 en producción | alta | visor read-only (bloque 2) |
| R3 | SQLite se pierde al recrear el contenedor | alta | volumen obligatorio (bloque 2) |
| R4 | Docker no instala desde `uv.lock` | alta | build reproducible (bloque 2) |
| R5 | dependencias vulnerables | alta | intentar parches Python; documentar/restringir lo restante (§13) |
| R6 | wallets/rebalanceo no visibles (criterio C3) | alta para comité | panel mínimo (bloque 4) |
| R7 | `order_failure` promete evidencia que no muestra | alta para demo | demostrar u honestar el claim (bloque 5) |
| R8 | `/health` puede reportar `ok` con tasks `finished/cancelled` | alta de deploy | corregir en bloque 2; el healthcheck depende de ello |
| R9 | tesis puede presentar fallback/demo como si fuera live | alta de credibilidad | fuente, ruta y muestra visibles (bloque 6) |
| R10 | validación canónica confundible con datos live | media | badge literal (bloque 6) |
| R11 | archivos runtime nuevos siguen untracked | crítica de release | manifiesto + build desde commit limpio (bloques 0 y 3) |
| R12 | volumen `/data` puede ser root-only para UID 10001 | alta de deploy | crear/chown y probar escritura (bloque 2) |
| R13 | cambios UX amplios sin tests frontend/E2E | media-alta para demo | smoke dirigido desktop/móvil (bloques 3 y 8) |
| R14 | demasiadas tareas para un día | crítica de ejecución | timeboxes + regla de corte (§6) |
| R15 | WAL está configurado en hook, pero no verificado en DB runtime | media de persistencia | comprobar PRAGMAs dentro del contenedor (bloques 2 y 7) |

## 4. Orden de ejecución (timeboxes y gates)

| Bloque | Trabajo | Timebox | Gate de salida |
|---:|---|---:|---|
| 0 | Checkpoint del worktree + manifiesto de archivos + backup | 20 min | rollback y árbol completo disponibles |
| 0b | Preflight de infraestructura, **sin desplegar app** | 20 min | host listo; riesgo de server descubierto temprano |
| 1 | Atomicidad del ledger + venues (P0-1) + tests | 2 h | regresiones específicas verdes |
| 2 | Read-only + volumen/lock + health correcto | 2.5 h | superficie segura y compose validada |
| 2b | Parches Python compatibles o excepción registrada | 45 min | audit decidido sin migración mayor |
| 3 | Suite completa backend + frontend | 45 min | todo verde |
| 4 | Panel Inventario & Rebalanceo + fix `ts=0.0` | 90 min | C3 visible sin DevTools |
| 5 | `esperado → observado` + decisión `order_failure` | 1 h | ningún claim sin evidencia |
| 6 | Origen/muestra + caso canónico + veredicto | 45 min | tesis honesta en primer recorrido |
| 7 | Redeploy + persistencia comprobada + smoke | 1 h 15 min | server candidato operativo |
| 8 | Ensayo + capturas + video + export | 1 h | paquete de evidencia completo |

Total máximo restante: aproximadamente **12 h 10 min**. No incluye migración mayor de Next ni
features nuevas. La regla de corte está en §6.

---

## 5. Especificación por bloque

### Bloque 0 — Snapshot y rollback (20 min)

- Crear rama `entrega-12jul` y un checkpoint de partida; todavía **no** crear el tag candidato.
- Revisar `git status` y construir un manifiesto de archivos. Un `git commit -am` es insuficiente:
  `page.tsx` ya importa `BusinessThesisCard.tsx`, que sigue untracked.
- Añadir explícitamente los archivos runtime/tests requeridos: `.dockerignore`,
  `backend/tests/test_robustness_edges.py`, `frontend/app/error.tsx`,
  `frontend/app/global-error.tsx` y `frontend/components/BusinessThesisCard.tsx`.
- Decidir cuáles docs unificados entran al commit y evitar subir artefactos históricos por accidente.
- Backup local de la DB si contiene datos que se quieran conservar.
- Gate: existe un punto de retorno exacto y el manifiesto no omite dependencias del runtime.

### Bloque 0b — Preflight de infraestructura temprano (20 min)

Desriesga R0 sin violar el gate de correctitud. En este bloque **no se hace rsync, build ni up**:

- comprobar SSH, espacio libre, memoria, Docker y `docker compose version`;
- comprobar que 8090 está permitido y que no colisiona con otro servicio;
- crear/verificar el directorio objetivo y permisos del usuario de despliegue;
- confirmar que no existe un `.env` antiguo y preparar el comando de creación del secreto;
- registrar salida y detenerse. La aplicación se despliega una sola vez, en el bloque 7.

Gotchas conocidos del server (confirmados en despliegues previos):

- `rsync` excluyendo `.git`, `node_modules`, `.venv`, `.next`, `*.db` **y `.env`** — los
  secretos se crean directamente en el server, nunca viajan con el repo.
- `deploy/standalone/.env` se crea directamente en el server con `ARB_CONTROL_TOKEN`
  (`openssl rand -hex 24`); el backend no arranca en prod sin él.
- Puerto interno 3100 para el frontend (Easy Panel DROPea el 3000 entre contenedores).
- `docker compose restart nginx` tras recrear contenedores (nginx resuelve IPs al arrancar).
- `up -d --force-recreate backend` tras rebuild (un `up -d` normal puede dejar el contenedor
  viejo).
- NO tocar Easy Panel ni Swarm; limpiar espacio solo con `docker builder prune -f`.
- El número de venues live se confirma en `/health`; no se promete "7" antes del smoke porque
  geobloqueos y disponibilidad externa pueden cambiar.

### Bloque 1 — P0-1: Atomicidad del ledger y configuración de venues (2 h)

**El defecto financiero invalidante.** Reproducido:

- `backend/app/store/config_store.py:51-85` cambia `enabled` en `Settings`;
- `backend/app/api/v1/router.py:519-551` aplica config y ejecuta `portfolio.reseed()`;
- `backend/app/main.py:282-286` crea los ingestors solo en el arranque (el book del venue
  deshabilitado puede seguir entrando al detector);
- `backend/app/sim/inventory.py:229-232` — `can_afford()` devuelve `True` si un venue no existe
  en el portfolio;
- `backend/app/sim/inventory.py:359-387` — `apply_execution()` ignora patas de venues
  desconocidos pero suma el P&L realizado.

```text
kraken.enabled = false
can_afford = true
execution_pnl = 8.00
portfolio_realized_pnl = 8.00
la pata buy de Binance se aplicó; la pata sell ausente se ignoró
```

La pata de Binance muta balances, la de Kraken se ignora, el P&L se reconoce: ganancia contable
con movimientos físicos incompletos.

**Cierre mínimo seguro (no construir el supervisor de feeds hoy):**

1. `can_afford()` → `False` si falta cualquier venue requerido.
2. `apply_execution()` valida todas las patas **antes** de mutar un solo balance; una ejecución
   inválida es atómica: cero cambios de balances, cero P&L.
3. Cambiar `enabled` en caliente se bloquea o se marca `restart_required`; la UI deshabilita el
   toggle o comunica que requiere reinicio.
4. Las ediciones hot de fees, tamaño y umbrales se mantienen si sus pruebas pasan.

**Tests obligatorios (gate de salida — sin esto no hay redeploy):**

- ejecución con buy venue desconocido no cambia nada;
- ejecución con sell venue desconocido no cambia nada;
- ninguna pata se aplica parcialmente;
- deshabilitar venue vía `PUT /api/v1/config/sim` no genera P&L fantasma;
- una configuración rechazada no deja mutación parcial en `Settings` ni portfolio;
- invariantes de conservación y doble entrada pasan antes y después del cambio de config.

### Bloque 2 — P0-2 auth + P0-3 deploy/health (2.5 h)

#### Auth: opción A — visor público read-only (elegida por timebox)

Evidencia: `backend/app/config.py:245-255` exige token en prod; `ControlPanel.tsx:44-57`,
`ConfigPanel.tsx:93-97`, Strategy Lab, retención, preflight y test order **no** envían
`X-Control-Token` → botones activos que siempre responden 401.

Diseño a aplicar:

- `NEXT_PUBLIC_READ_ONLY=1` es **build-time**, no runtime: declararlo como `ARG`/`ENV` antes de
  `npm run build` en `Dockerfile.frontend` y pasarlo con `build.args` en la compose. Ponerlo solo
  en `environment:` no cambia el bundle ya compilado.
- Exponer una constante central `READ_ONLY` y pasarla a las superficies mutables; no repartir
  comprobaciones ad hoc difíciles de auditar.
- Ocultar o deshabilitar con tooltip "demo pública read-only": kill switch, resume, cambio de
  modo/escenario, guardado de config, poda de retención, preflight y test order.
- **Conservar Strategy Lab** como what-if local, porque demuestra C1: en read-only `Aplicar`
  actualiza los parámetros de projection/capacity/forward mediante GET, pero no hace
  `PATCH /params`; se etiqueta `WHAT-IF LOCAL · NO PERSISTE`. Reset también queda local.
- `Export session` permanece activo: es GET read-only y no expone secretos.
- Badge persistente **`READ-ONLY DEMO`** en el header, textual (nunca solo color).
- La sesión jury se preactiva **antes** de presentar, desde CLI con token
  (`POST /api/v1/demo?mode=jury`). El comando se ejecuta por SSH desde el propio server contra
  `127.0.0.1:8090`; el token no viaja por el HTTP público sin TLS.
- Los toasts distinguen 401 ("requiere token de control") de fallo de red
  (`ControlPanel.tsx:44-58`, `ConfigPanel.tsx:95-110`, `StrategyLabPanel.tsx:49-53`).
- La opción elegida queda escrita en README/guion de entrega.

**Prohibido:** token en `localStorage` o en el bundle (`NEXT_PUBLIC_*`), inyectarlo desde nginx
en un sitio público sin auth, correr producción como `dev`, botones activos que siempre dan 401.

(Opción B — BFF de Next con allowlist + Basic Auth, ~3-4 h — solo si el día sobra; el
BFF/OIDC completo con roles y bitácora es post-entrega.)

#### Deploy files: volumen + lockfile + healthcheck

```yaml
services:
  backend:
    environment:
      ARB_DB_URL: sqlite+aiosqlite:////data/arbitraje.db
    volumes:
      - arb-data:/data

volumes:
  arb-data:
```

- `deploy/Dockerfile`: instalar `uv`, copiar primero `pyproject.toml` + `uv.lock`, ejecutar
  `uv sync --frozen --no-dev --no-install-project`, copiar `backend/` y cerrar con
  `uv sync --frozen --no-dev`; añadir `/app/.venv/bin` al `PATH`. El build falla si lock y
  proyecto divergen y conserva cache de dependencias sin volver a `pip install .`.
- Crear `/data`, asignarlo a UID/GID 10001 y mantener `USER appuser`; verificar dentro del
  contenedor que puede crear DB, `-wal` y `-shm` en el volumen.
- Mantener usuario no privilegiado y `.dockerignore` raíz (ya aplicados el 1-jul).
- Corregir `/health`: cualquier task `failed`, `finished` o `cancelled` fuera de shutdown degrada
  el servicio. Hoy solo `failed` cambia el estado global.
- Healthcheck del backend en compose que inspeccione `status == "ok"`, no únicamente HTTP 200;
  la respuesta degradada actual conserva 200. `depends_on` de nginx/frontend no reemplaza este gate.
- La DB nueva nace con `auto_vacuum=INCREMENTAL` (evita el `VACUUM` one-shot de una DB heredada).

Gate:

- `docker compose config` valida con un `.env` temporal saneado;
- el bundle contiene `READ-ONLY DEMO` y no contiene el token;
- una imagen backend construida desde lock arranca como UID 10001 y escribe en `/data`;
- con el engine vivo, `PRAGMA journal_mode` devuelve `wal` y `PRAGMA auto_vacuum` devuelve `2`;
- una task finalizada produce health degradado y el healthcheck falla;
- superficie anónima no ofrece ninguna mutación, pero Strategy Lab local y export funcionan.

### Bloque 2b — Dependencias vulnerables (45 min)

Ejecutar la decisión de §13 antes de la suite candidata: intentar los cuatro parches Python en un
commit aislado o registrar la excepción si el lock/build no cierran dentro del timebox. Next 16 no
entra. El bloque 3 valida el árbol resultante definitivo.

### Bloque 3 — Suite completa (45 min)

- Consolidar bloques 1-2 y los archivos nuevos en un commit; comprobar que no depende de
  untracked. Ideal: abrir un worktree limpio de ese hash y ejecutar allí.
- Backend: `uv run ruff check .`, `uv run mypy app` y
  `uv run pytest -q --cov=app --cov-fail-under=85`. Base esperada: más de 507 tests por las
  regresiones del bloque 1.
- Frontend: `npm run typecheck`, `npm run lint`, `npm run build`.
- Docker: `docker compose config` y build backend/frontend sin usar capas de un worktree anterior
  cuando se valide reproducibilidad.
- Crear el tag candidato **solo después** de estos gates y anotar su hash.
- Gate: todo verde desde el commit autocontenido. Si falla, se corrige antes de seguir.

### Bloque 4 — Panel Inventario & Rebalanceo (C3) + fix `ts=0.0` (90 min)

El backend ya devuelve la base necesaria, pero **no es solo render**:

- `/pnl` incluye `equity_by_venue`, `skew` y
  `rebalance{count,cost_total_usd,recent}`;
- el tipo TS `Pnl` hoy solo declara `skew`, no `equity_by_venue` ni `rebalance`;
- `GET /balances` devuelve BTC/quote por venue, equity y skew, pero el frontend no lo consume;
- `open_btc`/BTC comprometido existe internamente, pero no está en el contrato API;
- los eventos de rebalanceo no contienen origen/destino: solo `ts`, coste, fee BTC, mark y skew.

**Fix previo obligatorio:** `Rebalancer.run()` registra `ts=0.0`; pasar `time.time()` como epoch
al método puro y probar que el evento conserva un timestamp real. No usar monotonic como fecha UI.

Diseño del panel (valores ilustrativos; componente `InventoryPanel.tsx`, Resumen u Operación):

```text
┌─ INVENTARIO & REBALANCEO ────────────────────────────────────────────────┐
│              BTC total          Quote             Equity simulada        │
│ kraken       1.80 ████████      $84,120           $197,520               │
│ coinbase     0.70 ███           $128,400          $172,500               │
│ gemini       2.10 █████████     $76,930           $209,230               │
│ … (venues habilitados)                                                    │
├──────────────────────────────────────────────────────────────────────────┤
│ Skew 42% ▕████████░░░░▏ límite 50% · estado: NORMAL                      │
│ Rebalanceos: 3 · coste acumulado $40.20 · último: hace 2 min             │
│ ⓘ Reposición fiat por wire queda fuera del alcance de esta simulación   │
└──────────────────────────────────────────────────────────────────────────┘
```

- Añadir tipos TS explícitos y cargar `/balances` al montar, con refresco acotado; reutilizar el
  backstop de `/pnl` para skew/rebalanceo.
- Barras comparables + tabla compacta de eventos con los campos reales: timestamp, skew
  antes→después, `fee_btc`, `cost_usd` y `ref_mark`. No inventar origen/destino.
- Distinguir coste amortizado de decisión vs coste debitado al ledger (dos cifras etiquetadas).
- Estilo del design system: verde `#16D67F`, JetBrains Mono para cifras, tokens `POS`/`NEG`.
- Declarar el límite conocido (el rebalanceo solo mueve BTC, nunca quote —
  `inventory.py:305-323,439-468` — cada trade drena fiat del venue barato): tooltip/nota
  "reposición fiat por wire off-line, fuera de alcance" lo convierte en decisión de diseño
  defendible.

No mostrar `BTC comprometido` salvo que se amplíe y pruebe el contrato con `open_btc`; es stretch,
no requisito del panel mínimo.

Aceptación: el jurado responde "¿dónde está el BTC?" sin DevTools; un rebalanceo determinista
muestra skew antes/después, coste y timestamp real; la UI tolera cero eventos; ninguna cifra se
presenta como saldo real.

### Bloque 5 — Escenarios honestos: `esperado → observado` (60 min)

Contexto verificado: `simulator.py:310-391` implementa fills parciales/leg risk/unwind pero solo
se activan con `sell_book_t1`, que únicamente pasa el backtest (`replay.py:198`); en vivo el
evaluador clampa `q` a la profundidad mínima (`evaluator.py:146`) → `filled_buy == filled_sell`
siempre, `unwound` = 0 toda la sesión. Además `order_failure` declara
`expected_result="preflight_or_test_order_reject"` (`scenarios.py:178-198`) pero el player solo
inyecta books: el jurado nunca ve el rechazo.

Diseño a aplicar:

1. Mostrar para el **escenario activo** dos líneas: `esperado: <expected_result>` y
   `observado: <efecto real>`. En read-only no hay chips accionables, pero sí debe verse el estado
   que el operador activó por CLI.
2. Al cambiar `demo.scenario`, capturar una línea base de `metrics.discard_reasons`; tras una
   ventana corta mostrar el delta atribuible al escenario. No usar el total histórico de sesión
   como si fuera resultado del último click.
3. Para `order_failure`: disparar un harness determinista aislado (mismo preflight/simulador)
   que devuelva la evidencia del rechazo y pintarla junto al badge. Si no cabe en el timebox:
   **retirar o reformular el badge** para que no prometa lo que no ocurre.
4. El unwind se demuestra honesto vía replay/backtest (que sí pasa `sell_book_t1`), narrado como
   tal. **Prohibido hoy:** introducir datos futuros en el pipeline live, cambiar el significado
   de `sell_book_t1`, afirmar un unwind si solo cambió un badge, mostrar `expected_result` sin
   `observed_result`. (El cableado de `leg_failure` vivo confinado al player queda
   post-entrega.)

Aceptación: ningún escenario declara un resultado que la demo no muestre observado.

### Bloque 6 — Narrativa visual mínima (45 min)

Claude ya añadió `Tesis de negocio`, marcó equity como `capital simulado total`, mejoró móvil y
accesibilidad, conservó Resumen al cambiar de tab y renombró testnet a dry-run local. No se vuelve
a diseñar esa superficie. Quedan cuatro correcciones de credibilidad:

| # | Cambio obligatorio | Contrato real |
|---:|---|---|
| 1 | Badge literal **`CASO CANÓNICO`** junto a `$109.75/BTC` | fixture determinista de `/validation`, nunca edge live |
| 2 | Fuente en `Tesis de negocio` | retail/institucional muestran `frontier.mode` y ruta; si mode=`demo`, decir DEMO |
| 3 | Muestra del forward | mostrar `n_trades` empíricos y `n_paths`; etiquetar `recording/replay`, no "live" |
| 4 | Veredicto literal **`OPERAR` / `NO OPERAR`** | reutilizar la decisión, bruto, neto y coste dominante ya disponibles en el drawer |

Además, mantener equity con estilo neutral si domina la captura: es capital estático simulado, no
rentabilidad. El help de `BusinessThesisCard` deja de afirmar genéricamente "datos vivos" porque
projection/capacity pueden caer honestamente a demo.

No formatear `asof_monotonic` como hora: es reloj monotónico del proceso, no epoch. La frescura
visible se toma del estado SSE/feeds; un timestamp humano requeriría ampliar el contrato.

Aceptación:

- ninguna cifra demo parece mercado actual;
- `P(P&L>0)` muestra muestra y trayectorias, no solo porcentaje;
- MXN sigue declarado como expansión sin medición live;
- cada CTA de la tesis abre el panel que demuestra el mismo número;
- el primer recorrido deja visible tesis → veredicto → riesgo sin depender del color.

Stretch únicamente si bloques 1-7 están verdes: mover la tabla de rutas a Correctitud o añadir
scatter gross-vs-net. Se descartan hoy charts nuevos, animaciones, grafos y microconsistencia.

### Bloque 7 — Redeploy (1 h 15 min)

Secuencia (con los gotchas del bloque 0b):

1. Commit/tag candidato ya verificado por el bloque 3.
2. `rsync` desde un checkout limpio del hash candidato (mismas exclusiones; `.env` jamás viaja).
3. Crear/verificar secretos en el server (`deploy/standalone/.env` con `ARB_CONTROL_TOKEN`).
4. `docker compose build` desde el commit candidato.
5. Levantar backend → validar body `/health`: `status=ok` y todas las tasks esperadas `running`.
6. Levantar frontend y nginx → `docker compose restart nginx`.
7. Smoke: SSE fluye; modo jury se activa por SSH con
   `POST /api/v1/demo?mode=jury`; cada escenario que se mostrará produce evidencia; export
   descarga; kill switch con token → 200 y sin token → 401.
8. **Recrear el backend una vez** y comprobar que `app_config` y datos persisten (valida el
   volumen), que UID 10001 sigue escribiendo y que aparecen DB/WAL/SHM sin error de permisos.
9. Guardar comandos y resultados como evidencia.

### Bloque 8 — Ensayo y paquete de evidencia (1 h)

- Recorrer el guion de 90 s (§9) contra el server público, no contra local.
- Ensayar en voz alta las preguntas trampa (§10).
- Generar: capturas de Resumen y Correctitud (regenerar `assets/dashboard.png` desde el commit
  final, con datos deterministas y pie fecha/commit/modo), video local de respaldo de 90 s,
  export de sesión canónica, ejemplo captured + discarded + adverso observado, ledger
  reconciliado, salida de tests/cobertura/audits, prueba de recreación persistente, `/health`
  operativo, comandos de arranque y rollback.
- Probar en el proyector/dispositivo real: badge de simulación visible, texto legible, móvil ok.
- Ejecutar el smoke dirigido de los cambios frontend: Strategy Lab no reconecta SSE, stale se
  recupera, retry funciona, Resumen conserva sparklines, 360 px no solapa y error boundary responde.

---

## 6. Regla de corte

1. **Nunca cortar el bloque 1** (atomicidad).
2. Sin tiempo para auth interactiva → opción A tal cual (read-only + CLI).
3. Sin tiempo para `order_failure` → retirar el claim y demostrar thin book + replay de unwind.
4. Sin tiempo para narrativa completa → solo etiquetas de origen (cambios 1-2 del bloque 6) y
   veredicto literal.
5. Scatter, quick wins stretch, locale, barrido P2 completo y test de contrato del evaluador
   entran solo si los bloques 1-7 cierran antes de tiempo.
6. Todo lo que no quepa (supervisor dinámico de feeds, migración mayor de Next, BFF) pasa a
   post-entrega con excepción documentada. Las actualizaciones Python compatibles sí se evalúan
   en §13, sin desplazar atomicidad ni deploy.

## 7. P2 — Barrido de defectos menores (solo tras bloques 1-7)

| Defecto | Evidencia | Timebox |
|---|---|---:|
| Guion dice 5 escenarios jury; hay 7 (`latency_decay`, `order_failure`); docstring dice "Cinco" | `guion-demo-jurado.md:43`, `scenarios.py:66` | 15 min |
| `hmac.compare_digest` lanza 500 con header no-ASCII → devolver 401 | `security.py:58`, `router.py:95` | 20 min |
| Reset del Strategy Lab no comunica si es local o persistente | `StrategyLabPanel.tsx:59-70` | 20 min |
| Cap SSE tiene carrera entre comprobar `client_count` y registrar `subscribe()` | `router.py` + `stream/hub.py` | 30 min |
| Cliente SSE con 503 del cap queda en "reconnecting" perpetuo | `useStream.ts:547` | 30 min |
| `retryHeavy` cerca del tick de 30 s duplica los 4 fetches pesados | `useStream.ts:694-705` | 30 min |
| Locale numérico mixto (6 `toLocaleString()` sin locale; horas es-MX vs números en-US) | `OpportunitiesTable.tsx:85,125,127`, `FunnelPanel.tsx:74,89,130`, `WinsPanel.tsx:20` | 30 min |
| DB heredada puede no activar `auto_vacuum=2`; verificar migración antes de confiar en incremental | `db.py` + `retention.py` | 20 min |
| `incremental_vacuum` sin límite de páginas puede bloquear más de lo previsto | `retention.py` → trocear páginas | 30 min |
| Log flooding si un bug del engine se repite por book | `engine/__init__.py` → throttle | 30 min |
| Docs con números viejos (481 tests; son 507) | `documentos/ultima_fase_claude.md:24` | 10 min |
| FunnelPanel con % ≈ 0 parece bug (Progress vacío) | `FunnelPanel.tsx:64-83` | 45 min |
| Errores post-primera-carga invisibles (números viejos sin aviso con backend caído) | patrón `BreakEvenFrontier.tsx:49-63` y demás | 1-2 h |

Nota sobre el top fantasma del evaluador (`evaluator.py:165-166` vs `_top_sane` en
`simulator.py:80-91`): verificado que la integridad estructural bloquea `qty<=0` en vivo incluso
en modo `warn` (`integrity/validators.py:40-57`, `checker.py:47-53`) — quedan expuestos `NaN`
(pasa el check) y books fuera del pipeline (replay/demo/tests). Hoy, como mucho, un test de
contrato; unificar con `_top_sane` es post-entrega. No desplaza nada.

## 8. Go / No-Go del server público

**Go** si: el commit candidato es autocontenido y construye limpio; tests de atomicidad y suite
completa verdes; no existe forma de acumular P&L con una pata ausente; modo/origen/muestra visibles;
controles públicos read-only; Strategy Lab local funciona; UID 10001 escribe en `/data`; la DB
persiste al recrear backend; health rechaza tasks finalizadas; cada escenario mostrado tiene
resultado observado; el deploy responde y existe plan B local; la sesión canónica se exportó.

**No-Go** (se presenta local) si: la build depende de untracked o no coincide con el candidato;
el token aparece en navegador/logs/bundle; los venue toggles siguen generando estado incoherente;
`/health` dice `ok` con engine/writer muerto; demo/fallback se presenta como live; ConfigPanel
afirma persistencia sin volumen; `/data` falla por permisos; un escenario no produce lo anunciado;
las auditorías se ocultan en vez de registrar decisión y mitigación.

Es preferible una demo local correcta a un deploy público inconsistente.

## 9. Guion final de 90 segundos

| Tiempo | Mostrar | Mensaje |
|---:|---|---|
| 0-12 s | modo, fuente y `Tesis de negocio` | "No buscamos spreads: medimos cuándo son capturables" |
| 12-28 s | retail vs institucional | "la estructura de costes decide dónde existe negocio" |
| 28-43 s | bruto, neto, coste y veredicto | "el motor explica OPERAR o NO OPERAR" |
| 43-58 s | thin book u order failure observado | "ante poca liquidez o fallo, no inventa ejecución" |
| 58-73 s | inventario/skew/rebalanceo | "el capital simulado está pre-posicionado y controlado" |
| 73-84 s | caso canónico | "es un fixture reconciliado, no mercado live" |
| 84-90 s | export/evidencia | "cada decisión se puede reproducir" |

No mostrar en la ruta principal: los 46 endpoints, todos los paneles, módulos experimentales,
código antes del valor, charts vacíos, controles fallando, números sin modo/fuente/n, auditorías o
planes internos. No afirmar: rentabilidad garantizada, dry-run como testnet real, demo como live,
`P_survive` calibrado sin muestra, Postgres soportado, hot-toggle de venues, readiness para
dinero real.

## 10. Preguntas trampa esperadas (respuesta preparada)

1. *"¿Esto gana dinero?"* → no se promete retorno; se mide **capturabilidad**. La respuesta
   honesta usa la cifra actual del frontier: retail e institucional bajo su fee, ruta y modo;
   corredor MXN sigue como expansión sin cifra live; el forward declara muestra y trayectorias.
2. *"¿Qué es el $109.75?"* → caso canónico del reto, reconciliado por la misma `cost_model` del
   pipeline vivo (fuente única). Declarar el matiz antes de que lo pregunten: es el fixture del
   enunciado, no la config actual (badge `CASO CANÓNICO`).
3. *"¿Qué pasa si un leg falla a mitad?"* → el simulador y el replay modelan partial fill, leg
   risk y unwind; se enseña con el replay, afirmando solo lo observado.
4. *"Enséñame las wallets y un rebalanceo."* → panel Inventario & Rebalanceo (bloque 4), con
   coste y timestamp real.
5. *"¿Quién repone el USD del venue barato?"* → declarado fuera de alcance (wire off-line),
   visible en el propio panel.
6. *"Un retiro BTC tarda 10-60 min; ¿dónde está tu inventario mientras tanto?"* → inventario
   pre-posicionado (defensa escrita en `inventory.py:3-5`, subida a tooltip visible).
7. *"¿Por qué Monte Carlo bootstrap y no paramétrico?"* → `forward.py:1-26`: preserva
   autocorrelación, no impone normalidad; PSR/DSR/MinTRL con referencias.
8. *"¿Estas cifras son live?"* → solo cuando el panel dice `LIVE`; frontier declara su `mode` y
   ruta, el forward proviene de recording/replay y el caso `$109.75` es canónico.
9. *"Maté el proceso del engine, ¿qué pasa?"* → después del bloque 2, `/health` degrada con
   cualquier task fallida/finalizada y Docker lo marca `unhealthy`; el operador/monitor aplica
   el reinicio. Compose por sí solo no reinicia automáticamente solo por estar unhealthy.

## 11. Checklists

### Local (antes del bloque 7)

- [x] Base actual: 507 tests, cobertura 91.03%, ruff/mypy limpios.
- [x] Base actual: typecheck/lint/build frontend limpios, First Load JS 263 kB.
- [ ] Todos los archivos runtime/tests nuevos están dentro del commit; no depende de untracked.
- [ ] Tests nuevos de venue desconocido y ledger atómico pasan.
- [ ] `can_afford=False` cuando falta cualquier venue.
- [ ] Config de venue no se aplica parcialmente; invariantes de conservación pasan.
- [ ] Caso canónico `$109.75` sigue reconciliando (Δ 0.0000).
- [ ] Suite, cobertura y build repetidos desde un checkout limpio del candidato.
- [x] Auditorías ejecutadas; falta aplicar/registrar la decisión de §13.
- [ ] Build Docker usa `uv.lock` y `docker compose config` valida.

### Frontend

- [x] `LIVE/DEMO/REPLAY/STALE` y capital simulado ya implementados.
- [ ] `READ-ONLY DEMO` y caso canónico inequívocos y textuales.
- [ ] Controles ocultos o funcionales según superficie; ningún botón que siempre dé 401.
- [ ] Strategy Lab conserva what-if local sin intentar persistir.
- [ ] Wallets visibles; escenarios con esperado y observado coincidentes.
- [x] Error boundaries y estados loading/error principales añadidos.
- [ ] Tesis muestra mode/ruta; forward muestra `n_trades`/`n_paths`.
- [ ] Desktop y móvil sin solapamientos; legible en proyector.
- [ ] Smoke: Strategy Lab no reconecta SSE; stale recupera; retry y error boundary funcionan.

### Server (tras el bloque 7)

- [ ] Commit desplegado == candidato; secretos creados en server, no transferidos.
- [ ] Imagen backend construida desde lock y corriendo como UID 10001.
- [ ] SQLite en volumen `/data`; UID 10001 crea DB/WAL/SHM.
- [ ] Con backend vivo: `journal_mode=wal`, `auto_vacuum=2`, `synchronous=1`.
- [ ] Recrear backend conserva configuración y datos.
- [ ] `/health` tiene `status=ok` y tasks `running`; healthcheck falla al degradar.
- [ ] SSE fluye y pasa a stale al cortar datos.
- [ ] Visor anónimo no puede mutar estado; operador puede (CLI con token).
- [ ] Export descarga sin secretos; firewall solo expone 8090.
- [ ] El acceso público se puede apagar tras la evaluación.

### Mañana del 12 (pre-demo, 35 min)

- [ ] Suite local rápida verde (5 min).
- [ ] Smoke del server: health, SSE, un escenario, export (10 min).
- [ ] Ensayo del guion + preguntas trampa contra el server público (20 min).
- [ ] Plan B listo: stack local corriendo + video de respaldo + capturas.

## 12. Plan B y rollback

Plan B de demo: backend y frontend locales ya instalados; jury mode determinista preactivado;
export canónico en disco; video de 90 s listo; capturas estáticas para explicar sin servidor.

Rollback: conservar imagen y commit candidato anterior; no migrar ni borrar la DB sin backup;
cambios P0 en commits separados de los visuales; si falla el redeploy, volver al último commit
verde y usar demo local; **no depurar producción durante la presentación**.

## 13. Decisión sobre dependencias vulnerables (45 min de evaluación, sin migraciones)

Estado verificado:

- Python: **15 vulnerabilidades** en `aiohttp 3.13.5`, `cryptography 48.0.0`,
  `pydantic-settings 2.14.1` y `starlette 1.2.0`;
- fixes indicados por el audit: `aiohttp >=3.14.1`, `cryptography >=48.0.1`,
  `pydantic-settings >=2.14.2`, `starlette >=1.3.1`;
- frontend: **1 high + 1 moderate** con `next@14.2.35`; `npm audit` propone Next 16.2.10,
  cambio semver-major;
- el crecimiento actual de `uv.lock` no corrigió esas cuatro versiones.

Decisión:

1. Intentar las cuatro actualizaciones Python compatibles en commit aislado. Se integran solo si
   el lock resuelve, los tests/cobertura pasan y la imagen construye dentro del timebox.
2. No forzar Next 14→16 el día final. Registrar la excepción con impacto, mitigación y fecha de
   migración; el visor público queda read-only, limitado por firewall y se apaga tras la demo.
3. No afirmar que las vulnerabilidades son "inexplotables": nginx/read-only reducen superficie,
   pero no eliminan riesgos de DoS o del runtime de Next.
4. Guardar salidas de `pip-audit` y `npm audit` en el paquete de evidencia.
5. Nunca ejecutar `npm audit fix --force` sin revisar y probar el cambio mayor.

## 14. Trabajo diferido post-entrega

- Supervisor dinámico para enable/disable de venues (P0-1 completo).
- BFF/OIDC con roles `viewer`/`operator` y bitácora de mutaciones.
- Vulnerabilidades que no se hayan podido corregir en §13, migración de Next y audits en CI.
- `/livez` y `/readyz` separados con 503 real + healthchecks Docker encadenados.
- `leg_failure` en vivo confinado al player (`sell_book_t1` con el frame n+1) → unwind
  demostrable en vivo.
- Unificar el evaluador con `_top_sane` + test de contrato.
- Quick wins visuales 5-9 (microconsistencia, tabs, micro-labels) + scatter gross-vs-net.
- Playwright + Vitest; tipos TS generados desde OpenAPI.
- Retención: supervisor siempre activo + política persistida.
- Rate limiting/límites SSE en la frontera correcta (nginx / middleware proxy-aware).
- Arquitectura de datos medallion (Parquet/DuckDB, event envelope, session manifests) para
  calibración e histórico — diseño completo en `plan-mejora-integral-2026-07-11.md` §13.
- Catálogo visual completo (V1-V12: cockpit, scatter, depth sync, heatmap, timeline, lineage…)
  — en `plan-mejora-integral-2026-07-11.md` §11.
- `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, archivo de docs históricos.

## 15. Síntesis

El proyecto no pierde la evaluación por falta de features. Puede perderla por una contradicción
entre lo que afirma y lo que ejecuta: P&L con patas incompletas, controles visibles pero
inutilizables, persistencia efímera, cifras demo llamadas live, commit incompleto o escenarios sin
resultado observado. El cierre correcto:

1. eliminar el defecto contable (bloque 1);
2. elegir una superficie de acceso honesta (bloque 2);
3. desplegar una build persistente y reproducible (bloques 2 y 7);
4. mostrar wallets y un escenario adverso real (bloques 4 y 5);
5. declarar fuente y muestra de cada cifra comercial (bloque 6);
6. presentar tesis → bruto → neto → riesgo → evidencia en 90 segundos (bloques 6 y 8).

El jurado debe recordar tres cosas: el spread bruto miente; el sistema demuestra exactamente por
qué; la decisión puede auditarse y reproducirse. Todo lo demás es stretch.
