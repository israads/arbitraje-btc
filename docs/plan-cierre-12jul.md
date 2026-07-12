# Plan de cierre — 12-jul-2026

> Fecha del análisis: 11-jul-2026
>
> Revisión post-cambios de Claude: 11-jul-2026
>
> Cierre del comité: **12-jul-2026 23:59**
>
> Objetivo: entregar una versión estable, honesta, reproducible y fácil de defender.

## 1. Decisión ejecutiva

Claude añadió mejoras reales de robustez, seguridad, accesibilidad y narrativa. Esas mejoras
reducen el trabajo visual pendiente, pero no cambian la prioridad del cierre: el proyecto ya tiene
suficiente profundidad funcional y el último día debe cerrar cuatro garantías:

1. ninguna ejecución puede reconocer P&L sin aplicar todas sus patas al ledger;
2. el despliegue público no puede mostrar controles que fallen o expongan secretos;
3. configuración, runtime y UI deben representar el mismo estado;
4. la evidencia que el jurado necesita debe estar visible y ser reproducible.

La regla del cierre es:

> Primero correctitud, después acceso y despliegue, después evidencia del criterio, y al final
> únicamente pulido visual de bajo riesgo.

No se añadirán nuevas estrategias, mercados, dependencias mayores ni cambios arquitectónicos
amplios durante el día final.

La conclusión de esta revisión es concreta:

> La rama actual es un mejor candidato de demo, pero todavía no es un candidato de despliegue.
> Los cambios de Claude deben conservarse; atomicidad, acceso y persistencia aún bloquean el Go.

## 2. Estado verificado

| Verificación | Resultado |
|---|---|
| Backend tests | **507 passed**, 1 warning deprecado de Starlette/httpx |
| Cobertura backend | **91.03%** |
| Ruff + mypy strict | limpios, 104 archivos analizados |
| TypeScript + Next lint + build | limpios, sin warnings |
| Frontend | 93.4 kB de ruta; **263 kB First Load JS** |
| Worktree | contiene cambios locales todavía no consolidados |
| Server público `159.89.187.165:8090` | `curl` a `/` y `/health`: **HTTP 000**, conexión rechazada |
| SQLite local | reducida de ~14 GB a **36 KB**; WAL + auto-vacuum incremental añadidos |
| Persistencia Docker | sin volumen permanente en la configuración actual |
| Autenticación de controles | backend protegido; frontend sin sesión/token usable |
| Auditoría Python | **15 vulnerabilidades conocidas en 4 paquetes** |
| Auditoría frontend | **1 high + 1 moderate**; fix automático exige salto mayor de Next |

Todos los resultados anteriores se verificaron de nuevo después de los cambios de Claude. El
lockfile de Python sigue fijando `aiohttp 3.13.5`, `cryptography 48.0.0`,
`pydantic-settings 2.14.1` y `starlette 1.2.0`; no debe interpretarse el crecimiento de
`uv.lock` como corrección de vulnerabilidades.

### Fortalezas que no deben ponerse en riesgo

- fuente única de costes;
- walk-the-book compartido;
- replay point-in-time;
- fills parciales, leg risk y unwind;
- doble entrada e invariantes del inventario;
- demo determinista;
- breakers, watchdog y fallback;
- explicación por oportunidad;
- frontier, capacity y forward;
- export de sesión y runbooks.

### Revisión de los cambios de Claude

| Área | Cambio encontrado | Estado real | Decisión de cierre |
|---|---|---|---|
| Motor | excepciones por book ya no matan `run_engine`; yield cada 64 oportunidades | resuelto y probado | conservar |
| Watchdog | excepciones del ciclo se registran y el loop continúa | resuelto y probado | conservar |
| Health | expone estado de tasks y writer | **parcial**: solo `failed` degrada; `finished/cancelled` todavía dan `ok` | corregir |
| Persistencia local | WAL, `synchronous=NORMAL`, `busy_timeout`, incremental vacuum | resuelto localmente | conservar y probar migración |
| Cache | proyecciones con LRU de 64 entradas y TTL | resuelto | conservar |
| Seguridad backend | token obligatorio en prod, `compare_digest`, CORS acotado, cap SSE | resuelto en backend | falta acceso usable desde UI |
| Contenedores | usuarios no root, `.dockerignore`, bind backend a loopback | mejora válida | falta volumen, `/data`, healthcheck y lock |
| UX stream | Strategy Lab ya no reconecta SSE; watchdog `stale` | resuelto por código/build | smoke en navegador |
| UX fallos | toasts, error boundaries y estados de fetch | mejora válida | falta distinguir 401 y probar acciones reales |
| Accesibilidad | `aria-label`, contraste, DEMO móvil, métricas móviles | resuelto por código/build | revisión visual rápida |
| Narrativa | tarjeta `Tesis de negocio`, alcance en README, dry-run honesto | mejora de alto valor | etiquetar fuente y tamaño de muestra |
| Ledger | venue ausente todavía permite ejecutar y reconocer P&L | **no resuelto; reproducido de nuevo** | P0 crítico |
| Config runtime | toggle muta settings/portfolio, pero no el lifecycle de ingestors | **no resuelto** | bloquear toggle hot |
| Frontend auth | ningún mutation fetch envía token ni usa BFF | **no resuelto** | visor read-only o BFF |
| Docker data | ninguna compose monta la DB en volumen persistente | **no resuelto** | P0 |
| Docker build | backend sigue usando `pip install .` | **no resuelto** | P0 |

La sección "Plan de acción priorizado (11 días)" de la auditoría de Claude ya no es el calendario
vigente: fue redactada con fecha 1-jul y ventana de 11 días. Conservamos sus cambios verificados,
pero la ejecución se rige por los timeboxes de este documento para el cierre del 12-jul.

### Integridad del commit candidato

Hay archivos nuevos sin seguimiento que ya son dependencias de los cambios tracked:

- `.dockerignore`;
- `backend/tests/test_robustness_edges.py`;
- `frontend/app/error.tsx`;
- `frontend/app/global-error.tsx`;
- `frontend/components/BusinessThesisCard.tsx`.

`frontend/app/page.tsx` ya importa `BusinessThesisCard`. Por tanto, un `git commit -am` produciría
un candidato incompleto que puede fallar al construir fuera de este worktree. Antes del tag se debe
crear un manifiesto de archivos, añadir explícitamente los nuevos archivos requeridos y ejecutar la
suite desde el commit, no solo desde cambios locales sin consolidar.

### Mejoras de Claude que no deben repetirse

Ya no se debe gastar tiempo de cierre en volver a implementar:

- error boundaries generales;
- estados loading/error para projection, capacity, forward, survival y validation;
- staleness del SSE;
- toasts básicos;
- LRU de proyecciones;
- WAL y poda incremental;
- usuario no privilegiado y `.dockerignore`;
- tarjeta de tesis de negocio;
- renombrado de testnet a dry-run local;
- aria-labels y contraste básico de charts.

## 3. Riesgos de cierre

| ID | Riesgo | Severidad | Decisión |
|---|---|---:|---|
| R1 | P&L inconsistente al deshabilitar un venue | crítica | corregir antes de desplegar |
| R2 | controles web devuelven 401 en producción | alta | elegir superficie pública u operador |
| R3 | SQLite se pierde al recrear el contenedor | alta | volumen obligatorio |
| R4 | Docker no instala desde `uv.lock` | alta | build reproducible |
| R5 | dependencias con vulnerabilidades conocidas | alta | actualizar compatible o aceptar/restringir |
| R6 | wallets/rebalanceo no visibles | alta para comité | panel mínimo |
| R7 | `order_failure` promete evidencia que no muestra | alta para demo | demostrar o retirar claim |
| R8 | `/health` puede reportar `ok` con tasks terminadas | media-alta | corregir o validar explícitamente |
| R9 | tarjeta de tesis puede mostrar fallback/demo como si fueran números vivos | alta para credibilidad | etiquetar fuente y muestra |
| R10 | validación canónica puede confundirse con datos live | media | etiquetar origen |
| R11 | named volume `/data` puede quedar sin permisos para UID 10001 | alta de deploy | crear/chown `/data` en imagen y probar escritura |
| R12 | demasiadas tareas para un solo día | crítica de ejecución | aplicar timeboxes y cortes |
| R13 | commit candidato omite archivos nuevos que el frontend importa | crítica de release | no usar `git commit -am`; verificar árbol limpio/build |
| R14 | cambios UX amplios sin tests frontend/E2E | media-alta para demo | smoke dirigido en desktop/móvil antes de capturas |

## 4. P0 — Bloqueantes antes del redeploy

### P0-1. Atomicidad del ledger y configuración de venues

**Severidad:** crítica

**Timebox:** 2 horas, incluidos tests.

#### Problema reproducido

El endpoint de configuración puede deshabilitar un venue y resembrar el portfolio, pero los
ingestors se construyen una sola vez durante el arranque. Después:

- el book del venue puede seguir entrando al detector;
- el portfolio ya no contiene ese venue;
- `Portfolio.can_afford()` devuelve `True` si falta un venue;
- `Portfolio.apply_execution()` ignora la pata desconocida;
- el P&L realizado sí se acumula.

Reproducción verificada:

```text
kraken.enabled = false
portfolio contiene = [binance, bitget, bitstamp, bybit, coinbase, gateio, gemini, kucoin]
can_afford = true
execution_pnl = 8.00
portfolio_realized_pnl = 8.00
binance recibió la pata buy; la pata sell de kraken fue ignorada
```

Esto permite una ganancia contable con movimientos físicos incompletos. Los nuevos tests de
robustez de Claude no cubren este contrato; que la suite tenga 507 tests verdes no invalida la
reproducción.

#### Cierre mínimo seguro

1. Un venue ausente debe producir `can_afford=False`.
2. `apply_execution()` debe validar todas las patas antes de mutar balances.
3. Una ejecución inválida debe ser atómica: cero cambios de balances y cero P&L.
4. Durante esta entrega, cambiar `enabled` en caliente debe bloquearse o marcarse
   `restart_required`.
5. Las ediciones hot de fees, tamaño y umbrales pueden mantenerse si sus pruebas pasan.
6. La UI debe deshabilitar el toggle de venues o comunicar claramente que requiere reinicio.

No se construirá mañana un supervisor dinámico completo de feeds. Ese lifecycle queda para el
siguiente sprint.

#### Tests obligatorios

- ejecución con buy venue desconocido no cambia nada;
- ejecución con sell venue desconocido no cambia nada;
- ninguna pata se aplica parcialmente;
- deshabilitar venue desde API no genera P&L fantasma;
- configuración rechazada no deja mutación parcial;
- invariantes de conservación siguen pasando.

#### Gate

No hay redeploy si cualquiera de estos tests falla.

### P0-2. Autenticación usable sin exponer el token

**Severidad:** alta

**Timebox:** 90 minutos para decidir e implementar la opción de cierre.

Claude corrigió el lado servidor: el backend exige `ARB_CONTROL_TOKEN` con `ARB_ENV=prod`, usa
comparación constant-time y las compose fallan si falta el secreto. Sin embargo, el navegador no
tiene una sesión de operador y ningún mutation fetch añade `X-Control-Token`. Kill switch, resume,
escenarios, configuración, retención, parámetros y preflight siguen devolviendo 401. Los nuevos
toasts convierten el fallo silencioso en un mensaje, pero no lo hacen funcional.

#### Opciones permitidas

**Opción A — visor público read-only, recomendada si el tiempo es corto**

- ocultar o deshabilitar acciones mutables;
- preactivar la sesión jury antes de presentar;
- mantener exploración, métricas, replay y explicación;
- ejecutar comandos administrativos desde CLI con token;
- etiquetar el modo como `READ-ONLY DEMO`.

Esta es la opción recomendada para el cierre actual: tiene menor superficie, no requiere diseñar
sesiones el último día y evita que el jurado encuentre botones que fallan. Debe aplicarse de forma
centralizada, no ocultando botones sueltos sin revisar todos los mutations.

**Opción B — BFF server-side + acceso restringido**

- route handlers de Next.js con allowlist estricta de acciones;
- `ARB_CONTROL_TOKEN` solo en el entorno del servidor, nunca `NEXT_PUBLIC_*`;
- dashboard completo protegido por Basic Auth, VPN o allowlist temporal;
- navegador llama al BFF y el BFF añade el header;
- desactivar el acceso al terminar la evaluación.

#### Opciones prohibidas

- guardar el token en `localStorage`;
- incluirlo en el bundle del frontend;
- inyectarlo desde nginx para un sitio público sin autenticación;
- ejecutar producción como `dev` para evitar el control;
- mostrar botones activos que siempre responden 401.

#### Gate

- público anónimo: solo lectura;
- operador: acciones funcionales sin exponer secretos;
- 401 debe tener mensaje específico, no "fallo de red";
- la opción elegida queda escrita en el README/guion de entrega.

Inventario de mutations que deben quedar funcionales o fuera del visor público:

- `/params` y `/params/reset`;
- `/config/sim`;
- `/storage/retention`;
- `/execution/preflight` y `/execution/test-order`;
- `/control/kill-switch` y `/control/resume`;
- `/backtest`;
- `/demo` y `/demo/scenario(s)/{name}`.

### P0-3. Despliegue persistente y reproducible

**Severidad:** alta

**Timebox:** 2 horas antes del redeploy.

El redeploy no debe repetir la configuración que perdió el servidor.

#### Cambios obligatorios

1. Montar un volumen en `/data`.
2. Usar `ARB_DB_URL=sqlite+aiosqlite:////data/arbitraje.db`.
3. Instalar backend desde `uv.lock` con `uv sync --frozen --no-dev`.
4. Crear `/data` en la imagen y asignarlo al UID/GID no privilegiado antes de `USER appuser`.
5. Mantener el usuario no privilegiado añadido por Claude.
6. Añadir healthcheck del backend que falle si el body no está operativo.
7. Probar escritura real desde UID 10001 dentro del volumen.
8. Probar recreación del contenedor conservando `app_config` y datos.
9. Mantener el token fuera del rsync y del repositorio.
10. Guardar un backup del volumen antes de cualquier redeploy posterior.

Ejemplo de volumen:

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

La compose standalone solo monta `nginx.conf`; la compose del backend no define ningún volumen.
El hecho de que la DB local mida ahora 36 KB no protege los datos del contenedor. Además, el
Dockerfile sigue ejecutando `pip install .`: el `uv.lock` ampliado por Claude no participa en la
imagen y, por tanto, aún no garantiza reproducibilidad.

#### Secuencia de redeploy

1. Consolidar y etiquetar el commit candidato.
2. Ejecutar tests y build local.
3. Transferir código sin `.git`, `.env`, `.venv`, `node_modules`, `.next` ni DB local.
4. Crear secretos directamente en el servidor.
5. Construir imágenes desde el commit candidato.
6. Levantar backend y validar health.
7. Levantar frontend y nginx.
8. Ejecutar smoke completo.
9. Recrear backend una vez y comprobar persistencia.
10. Guardar comandos y resultados como evidencia.

No se redeploya antes de cerrar P0-1 y P0-2. Desplegar primero solo duplica trabajo y aumenta el
riesgo de enseñar una versión incorrecta.

### P0-4. Decisión explícita sobre dependencias vulnerables

**Severidad:** alta

**Timebox:** 45 minutos de evaluación; no migraciones mayores sin margen.

Hallazgos verificados:

- backend: **15 vulnerabilidades** en `aiohttp 3.13.5`, `cryptography 48.0.0`,
  `pydantic-settings 2.14.1` y `starlette 1.2.0`;
- versiones corregidas indicadas por el audit: `aiohttp >=3.14.1`, `cryptography >=48.0.1`,
  `pydantic-settings >=2.14.2` y `starlette >=1.3.1`;
- frontend: **1 high + 1 moderate** con `next@14.2.35`, incluido PostCSS transitivo;
- `npm audit` propone `next@16.2.10`, un cambio semver-major que no se fuerza el día final.

#### Regla de cierre

- actualizar paquetes Python a versiones corregidas solo si el lock resuelve y los 507 tests
  permanecen verdes;
- aceptar una actualización compatible dentro de la línea actual de frontend si build y smoke
  pasan;
- no forzar una migración Next 14 -> 16 el día final;
- si queda una excepción, documentar paquete, impacto, restricción aplicada y fecha de corrección;
- limitar la exposición pública mediante autenticación/firewall y apagarla después de la demo.

No se debe ocultar un audit fallido ni ejecutar `npm audit fix --force` sin revisar el cambio.

La decisión preferida es intentar primero las cuatro actualizaciones Python compatibles en una
rama/commit aislado. Para Next, si no existe un parche compatible verificado, se documenta la
excepción, se limita la exposición temporal y se agenda la migración; no se mezcla una migración
mayor con el cierre contable y de despliegue.

## 5. P1 — Evidencia directa para el comité

### P1-1. Inventario y rebalanceo visibles

**Criterio:** wallets y rebalanceo

**Timebox:** 90 minutos

**Dependencia:** P0-1 cerrado.

El backend ya expone:

- balances por venue y activo;
- `equity_by_venue`;
- skew y límite;
- BTC abierto/comprometido en el modelo;
- contador, coste y eventos de rebalanceo.

#### Panel mínimo

`Inventario & Rebalanceo` debe mostrar:

- BTC y quote por venue;
- equity por venue;
- skew actual vs límite;
- estado normal/breached;
- cantidad de rebalanceos;
- coste acumulado;
- último evento con timestamp real;
- aviso: reposición fiat/wire queda fuera de alcance.

No añadir sunburst, Sankey complejo ni animaciones. Barras comparables y una tabla compacta son
más seguras y legibles para el cierre.

#### Fix asociado

`Rebalancer.run()` usa `ts=0.0`. Debe registrar un timestamp real y tener una prueba.

#### Aceptación

- el jurado puede responder "dónde está el BTC" sin abrir DevTools;
- un rebalanceo determinista muestra antes/después, coste y timestamp;
- coste amortizado de decisión y coste debitado al ledger se distinguen;
- ninguna cifra se presenta como saldo real.

### P1-2. Escenario adverso observable y honesto

**Criterio:** robustez ante falta de liquidez y fallo de orden

**Timebox:** 60 minutos.

`thin_book` ya puede demostrarse mediante el pipeline. `order_failure` actualmente inyecta books,
pero su `expected_result` habla de un rechazo de preflight/test-order que no ocurre de forma
automática.

#### Cierre recomendado

1. Mostrar junto a cada escenario `esperado` y `observado`.
2. Para `thin_book`, enlazar el contador de `discard_reason` recibido por SSE.
3. Para `order_failure`, ejecutar un harness determinista aislado que use el mismo preflight o
   simulador y devuelva evidencia del rechazo/unwind.
4. Si no cabe en el timebox, renombrar el escenario a lo que realmente demuestra o retirarlo de la
   ruta principal.

#### Prohibido en el cierre

- introducir datos futuros en el pipeline live;
- cambiar el significado de `sell_book_t1` en producción;
- afirmar que ocurrió un unwind si solo cambió un badge;
- mostrar `expected_result` sin un `observed_result` asociado.

El replay/backtest puede demostrar leg risk y unwind de forma honesta. No es necesario convertir
la ruta live en un backtest para impresionar al jurado.

### P1-3. Narrativa visual mínima

**Criterios:** profundidad, interfaz y documentación

**Timebox restante:** 45 minutos.

Claude ya añadió la tarjeta `Tesis de negocio`, marcó equity como `capital simulado total`, hizo
visible DEMO en móvil, conservó el histórico de Resumen y renombró el preflight como dry-run local.
Estas mejoras responden bien a la pregunta "¿dónde sí hay negocio?" y deben conservarse.

Queda una brecha de honestidad: la tarjeta describe sus cifras como vivas, pero los endpoints de
projection pueden caer a datos demo/fallback y la tarjeta no muestra origen ni tamaño de muestra.
Además, el `$109.75/BTC` canónico todavía aparece como badge destacado sin la etiqueta literal
`CASO CANÓNICO`.

Para el cierre se aplican únicamente estos cambios:

1. Mantener equity etiquetada como `Capital simulado` y reducir su protagonismo si domina la captura.
2. Etiquetar `$109.75/BTC` como `CASO CANÓNICO`, no como edge live.
3. Añadir a la tesis `fuente: LIVE/DEMO/REPLAY`, ventana y `n` de observaciones/trades.
4. No usar la frase "números vivos" cuando el backend haya usado fallback.
5. Mostrar un veredicto literal: `OPERAR` o `NO OPERAR` para la oportunidad seleccionada.
6. Hacer visible bruto, neto y coste dominante en la misma zona.
7. Mostrar `esperado -> observado` en escenarios.
8. Mantener controles únicamente en `Operación` o fuera del visor público read-only.

#### Aceptación de la tarjeta de tesis

- retail e institucional provienen de la misma fuente claramente identificada;
- `P(P&L>0)` muestra número de trayectorias y tamaño de muestra empírica, no solo el porcentaje;
- MXN permanece explícitamente como expansión sin cifra live;
- ninguna cifra demo se presenta como mercado actual;
- navegar desde la tarjeta lleva al panel que demuestra exactamente el número mostrado.

#### Mejor visual nuevo si sobra tiempo

Scatter `spread bruto vs edge neto`:

- X: spread bruto por BTC;
- Y: edge neto por BTC;
- color: captured o motivo de descarte;
- tamaño: cantidad ejecutable.

Es el visual que mejor comunica la tesis, pero es stretch. No desplaza P0 ni el panel de wallets.

#### Cambios visuales que se descartan

- hacer `$109.75` el hero principal;
- agrandar KPIs genéricos de P&L;
- añadir charts vacíos;
- más grafos de relaciones;
- animaciones nuevas;
- modificar doce componentes por microconsistencia;
- rediseñar el sistema de tabs.

## 6. P2 — Correcciones pequeñas con alto retorno

Ejecutar solo después de P0 y P1.

| Tarea | Timebox | Aceptación |
|---|---:|---|
| `/health`: `finished/cancelled/failed` degradan fuera de shutdown | 30 min | task muerta no reporta `ok` |
| respuesta readiness 503 separada o healthcheck que inspeccione body | 30 min | Docker detecta degradación |
| `compare_digest` con header no ASCII devuelve 401 | 20 min | nunca 500 |
| migración de DB existente activa realmente `auto_vacuum=2` | 20 min | `PRAGMA auto_vacuum` verificado |
| cap SSE sin carrera de check/subscribe | 30 min | nunca excede el límite concurrente |
| Strategy Lab reset persiste o dice `solo local` | 30 min | UI y backend no divergen |
| estado stale posterior a primera carga | 45 min | números viejos llevan aviso |
| guion y UI coinciden en número de escenarios | 15 min | una sola cifra vigente |
| locale numérico único | 30 min | misma convención en tablas y KPIs |
| comentarios `stub` obsoletos | 15 min | código no contradice estado |

### Hallazgo del top-of-book

El evaluador usa `best_ask/best_bid`, mientras el simulador tiene `_top_sane`. En el flujo live,
la integridad genérica ya rechaza niveles con precio o cantidad no positivos, por lo que no es el
ataque principal del día final. Debe quedar cubierto por un test de contrato y resolverse después
del cierre si se permiten `NormalizedBook` construidos fuera del pipeline de integridad.

No desplaza atomicidad, autenticación, persistencia ni evidencia del comité.

## 7. Orden de ejecución y timeboxes

Claude redujo la deuda de UX y hardening, pero la ruta crítica de correctitud y deploy apenas se
acortó. Este es el trabajo restante, no la suma de todo lo ya realizado.

| Bloque | Trabajo | Tiempo máximo | Gate de salida |
|---:|---|---:|---|
| 0 | snapshot, manifiesto de untracked, commit candidato y backup | 20 min | árbol completo y rollback disponible |
| 1 | P0-1 atomicidad + tests | 2 h | regresiones específicas verdes |
| 2 | visor read-only + volumen `/data` + build desde lock | 2.5 h | auth/superficie y persistencia decididas |
| 3 | suite backend/frontend completa | 45 min | todo verde |
| 4 | P1-1 wallets + timestamp | 1.5 h | criterio C3 visible |
| 5 | P1-2 escenario observado | 1 h | no hay claim engañoso |
| 6 | origen/muestra + caso canónico + veredicto | 30 min | tesis honesta en primer recorrido |
| 7 | redeploy + persistencia + smoke | 1.25 h | server candidato operativo |
| 8 | ensayo, capturas, video y export | 1 h | paquete de evidencia completo |

Total máximo restante: aproximadamente **10 horas 50 minutos**. La cifra no incluye una migración
mayor de Next ni features nuevas. Si hay menos tiempo, se aplican los cortes siguientes.

### Regla de corte

1. Nunca cortar P0-1.
2. Si no cabe auth interactiva, usar visor read-only.
3. Si no cabe order failure, retirar el claim y demostrar thin book + replay de unwind.
4. Si no cabe narrativa completa, conservar solo etiquetas de origen y veredicto bruto/neto.
5. Scatter, microestilos, locale y documentación histórica son stretch.
6. Las últimas 90 minutos se reservan para QA y ensayo; no se programan features.
7. No volver a abrir UX-1..UX-7 salvo que el smoke encuentre una regresión observable.
8. No etiquetar un candidato construido desde un worktree distinto al commit que se desplegará.

## 8. Go / No-Go

### Go

Se puede presentar si:

- el commit candidato contiene todos los archivos nuevos requeridos y construye por sí solo;
- los tests de atomicidad y la suite completa pasan;
- no existe forma de acumular P&L con una pata ausente;
- el modo y origen de datos están visibles;
- los controles públicos son read-only o están autenticados;
- la DB persiste al recrear el backend;
- el proceso no root puede escribir en `/data`;
- `/health` degrada ante tasks `failed`, `finished` o `cancelled` inesperadamente;
- todos los escenarios mostrados tienen resultado observable;
- cada cifra de tesis muestra fuente y tamaño de muestra;
- el deploy responde y existe plan B local;
- la sesión canónica se exportó y puede reproducirse.

### No-Go

No se usa el server público si:

- contiene una build distinta al commit candidato;
- el build solo funciona por archivos untracked ausentes del commit;
- el control token aparece en navegador, logs o bundle;
- venue toggles siguen generando estado incoherente;
- `/health` dice `ok` con engine/writer muerto;
- demo y live no pueden distinguirse;
- ConfigPanel afirma persistencia sin volumen;
- el escenario mostrado no produce el resultado anunciado;
- la tarjeta llama "vivo" a un número proveniente de demo/fallback;
- `npm audit` o `pip-audit` se ocultan en vez de registrar decisión y mitigación.

En un No-Go de servidor se presenta localmente. Es preferible una demo local correcta a un deploy
público inconsistente.

**Estado al terminar esta revisión: NO-GO para redeploy público.** El build local es verde, pero
R1-R5 siguen abiertos y el servidor no acepta conexiones.

## 9. Checklist local

### Correctitud

- [ ] Tests nuevos de venue desconocido y ledger atómico.
- [ ] `can_afford=False` cuando falta cualquier venue.
- [ ] Config de venue no se aplica parcialmente.
- [x] Suite actual e invariantes existentes pasan: 507 tests.
- [x] Caso canónico `$109.75` continúa cubierto por la suite actual.
- [ ] Repetir ambos gates después del fix de atomicidad.

### Calidad

- [x] `uv run ruff check .`.
- [x] `uv run mypy app`.
- [x] `uv run pytest -q`: 507 passed.
- [x] Cobertura de referencia documentada: 91.03%, por encima del gate de 85%.
- [x] `npm run typecheck`.
- [x] `npm run lint`.
- [x] `npm run build`: 263 kB First Load JS.
- [x] Auditorías de dependencias ejecutadas.
- [ ] Actualizaciones compatibles o excepción/mitigación registradas.
- [ ] Repetir suite, cobertura y build sobre el commit candidato final.
- [ ] Verificar `git status` y añadir todos los archivos runtime/tests requeridos.
- [ ] Construir desde un worktree limpio del commit candidato.

### Frontend

- [x] LIVE/DEMO/REPLAY/STALE implementados; falta `READ-ONLY`.
- [x] Capital marcado como simulado.
- [ ] Caso canónico marcado como fixture.
- [ ] Controles ocultos o funcionales según rol.
- [ ] Wallets visibles.
- [ ] Escenario esperado y observado coinciden.
- [x] Error boundaries y estados loading/error principales añadidos.
- [ ] Tesis muestra fuente y tamaño de muestra.
- [ ] Desktop y móvil sin solapamientos.

Smoke mínimo para validar específicamente los cambios de Claude:

- [ ] aplicar Strategy Lab no cambia SSE a `connecting/reconnecting`;
- [ ] cortar eventos lleva el estado a `SIN DATOS` y recuperarlos vuelve a `EN VIVO`;
- [ ] forzar error de projection muestra fallback y `Reintentar` funciona;
- [ ] kill/resume/config/retención no fallan en silencio ni muestran un error genérico para 401;
- [ ] cambiar de tab y volver conserva las sparklines de Resumen;
- [ ] badge DEMO y métricas caben en 360 px sin solaparse;
- [ ] enlaces de `Tesis de negocio` abren el panel y número correctos;
- [ ] error boundary se prueba al menos una vez en entorno local controlado.

## 10. Checklist de server

- [ ] Commit desplegado coincide con candidato.
- [ ] Secretos creados en servidor y no transferidos con el repo.
- [ ] Backend corre como usuario no privilegiado.
- [ ] Imagen backend fue construida desde `uv.lock` congelado.
- [ ] SQLite está en volumen `/data`.
- [ ] UID 10001 puede crear DB, WAL y SHM dentro de `/data`.
- [ ] Recrear backend conserva configuración.
- [ ] `/health` muestra todas las tasks `running` y no acepta finales inesperados.
- [ ] Healthcheck del contenedor detecta un body degradado.
- [ ] SSE entrega eventos y pasa a stale al cortar datos.
- [ ] Visor anónimo no puede mutar estado.
- [ ] Operador autorizado puede activar kill switch.
- [ ] Configuración persiste tras reload y recreación.
- [ ] Export de sesión descarga sin secretos.
- [ ] Firewall expone solo el puerto necesario.
- [ ] Acceso público se puede apagar después de la evaluación.

## 11. Guion final de 90 segundos

| Tiempo | Mostrar | Mensaje |
|---:|---|---|
| 0-12 s | modo, fuente y `Tesis de negocio` | "No buscamos spreads: medimos cuándo son capturables" |
| 12-28 s | retail vs institucional | "el mismo mercado cambia de no-negocio a negocio por estructura de costes" |
| 28-43 s | oportunidad: bruto, neto, coste y veredicto | "el motor explica OPERAR o NO OPERAR" |
| 43-58 s | thin book u order failure observado | "ante poca liquidez o una pata fallida, no inventa ejecución" |
| 58-73 s | wallets/skew/rebalanceo | "el capital simulado está pre-posicionado y controlado" |
| 73-84 s | caso canónico | "esta cifra es un fixture de reconciliación, no mercado live" |
| 84-90 s | export/evidence | "cada decisión se puede reproducir" |

### Qué no mostrar en la ruta principal

- los 46 endpoints;
- todos los paneles;
- módulos experimentales;
- código antes de explicar el valor;
- charts vacíos;
- controles fallando;
- números sin modo, fuente o tamaño de muestra;
- la auditoría interna de Claude;
- planes internos o documentación histórica.

### Qué no afirmar

- rentabilidad garantizada;
- dry-run como testnet real;
- demo como live;
- `P_survive` calibrado sin muestra suficiente;
- Postgres soportado actualmente;
- hot enable/disable de venues;
- readiness para dinero real.

## 12. Preguntas críticas y respuesta corta

### ¿Esto gana dinero?

No se promete retorno. El producto mide capturabilidad y muestra bajo qué fees, tamaño y liquidez
el edge sobrevive.

### ¿Qué es `$109.75/BTC`?

Es el caso canónico del reto usado para reconciliar la fórmula. No es una oportunidad live ni el
resultado de la configuración actual.

### ¿Las cifras de la tesis son live?

Solo cuando la tarjeta lo indique. Cada cifra debe declarar `LIVE`, `DEMO` o `REPLAY`, además de
ventana y muestra. Si el backend usa fallback, se presenta como demo y no como mercado actual.

### ¿Qué ocurre si falla una pata?

El simulador y replay modelan partial fill, leg risk y unwind. La demo solo afirma el resultado que
puede mostrar con evidencia observada.

### ¿Dónde están las wallets?

El inventario está pre-posicionado por venue. El panel muestra balances, skew, BTC comprometido y
coste de rebalanceo.

### ¿Quién repone el fiat?

La reposición fiat por wire queda fuera del alcance de esta simulación y se declara como límite.

### ¿Por qué bootstrap?

Para no imponer una distribución normal/i.i.d. y preservar parte de la dependencia temporal de la
muestra. Los resultados muestran incertidumbre, no una predicción.

### ¿Por qué un monolito?

El estado y la latencia importan más que distribuir prematuramente. El monolito modular evita saltos
de red y mantiene el core determinista y testeable.

## 13. Paquete de evidencia

Antes del cierre deben existir:

- commit/tag candidato;
- salida de tests y cobertura;
- resultado de auditorías y excepciones;
- matriz de vulnerabilidades con versión, mitigación y fecha objetivo;
- captura actualizada de Resumen;
- captura de Correctitud;
- video local de respaldo;
- export de sesión canónica;
- ejemplo captured y discarded;
- ejemplo adverso observado;
- ledger reconciliado;
- configuración saneada;
- prueba de persistencia antes/después de recrear el contenedor;
- salida de `/health` con todas las tasks operativas;
- comandos de arranque y rollback;
- fecha, modo y commit de cada artefacto.

## 14. Plan B y rollback

### Plan B de demo

1. Backend y frontend locales ya instalados.
2. Ingesta real desactivada si la red es inestable.
3. Jury mode determinista preactivado.
4. Export canónico disponible en disco.
5. Video de 90 segundos listo.
6. Capturas estáticas para explicar sin servidor.

### Rollback

- conservar imagen y commit candidato anterior;
- no migrar ni borrar la DB sin backup;
- cambios P0 en commits separados;
- cambios visuales en commit independiente;
- si falla el redeploy, volver al último commit verde y usar demo local;
- no depurar producción durante la presentación.

## 15. Trabajo diferido después del cierre

- supervisor dinámico para enable/disable de venues;
- autenticación OIDC o sesión completa de operador;
- `/livez` y `/readyz` separados;
- actualización mayor de Next;
- Playwright, Vitest y contratos OpenAPI generados;
- heatmap histórico de profundidad;
- scatter gross vs net si no entró como stretch;
- execution timeline completa;
- Parquet/DuckDB para histórico analítico;
- state timeline operativa;
- Postgres solo cuando el volumen lo justifique;
- nuevas estrategias y mercados después de cerrar calibración.

## 16. Síntesis

Claude mejoró correctamente la robustez del runtime, la seguridad por defecto, la resistencia del
frontend y la narrativa de negocio. El proyecto no pierde la evaluación por falta de features.
Puede perderla por una contradicción entre lo que afirma y lo que realmente ejecuta: P&L con patas
incompletas, controles visibles pero inutilizables, persistencia efímera, cifras demo descritas
como vivas o escenarios sin resultado observado.

El cierre correcto consiste en:

1. eliminar el defecto contable;
2. elegir una superficie de acceso honesta;
3. desplegar una build persistente y reproducible;
4. mostrar wallets y un escenario adverso real;
5. declarar fuente y muestra de cada cifra comercial;
6. presentar tesis -> bruto -> neto -> riesgo -> evidencia en 90 segundos.

Las mejoras ya hechas por Claude se conservan y se verifican; no vuelven a competir por tiempo con
estos gates. Todo lo demás es stretch.
