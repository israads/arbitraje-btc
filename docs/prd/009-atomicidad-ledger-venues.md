# PRD-009: Atomicidad del ledger y configuración de venues

Estado: Pendiente (Bloque 1 del plan de cierre, P0-1)  
Prioridad: P0 — bloqueante de redeploy  
Área: Backend (sim, store, API), Frontend (ConfigPanel)  
Dependencias: ninguna  
Plan de origen: [docs/plan-accion-final-12jul.md](../plan-accion-final-12jul.md) §5, Bloque 1

## Problema

**Defecto financiero invalidante, reproducido.** El sistema puede reconocer P&L de una
ejecución sin aplicar todas sus patas al ledger. La cadena verificada en el código actual es:

- `backend/app/store/config_store.py:51-64` — `apply_sim_config()` cambia `enabled` mutando
  `Settings` in-place.
- `backend/app/api/v1/router.py:519-551` — `PUT /api/v1/config/sim` aplica la configuración,
  la persiste y ejecuta `portfolio.reseed()`.
- `backend/app/main.py:282-286` — los ingestors se construyen y arrancan una sola vez durante
  el `lifespan`; cambiar `Settings` después no modifica la lista de runners vivos.
- `backend/app/sim/inventory.py:229-232` — `can_afford()` devuelve `True` si falta el venue de
  compra o el de venta en el portfolio.
- `backend/app/sim/inventory.py:347-387` — `apply_execution()` omite con `continue` una pata
  cuyo venue no existe y después suma igualmente `execution.realized_pnl`.

Reproducción mínima:

```text
kraken.enabled = false
can_afford = true
execution_pnl = 8.00
portfolio_realized_pnl = 8.00
la pata buy de Binance se aplicó; la pata sell de Kraken se ignoró
```

La pata de Binance muta balances, la de Kraken se omite y el P&L se reconoce: se crea una
ganancia contable sin los movimientos físicos que la sustentan. Esto contradice la doble
entrada y la conservación declaradas por el módulo
(`backend/app/sim/inventory.py:7-25`). Es el riesgo R1 del plan, de severidad crítica: no
se redeploya sin cerrarlo.

## Objetivo

Cierre mínimo seguro, sin construir el supervisor dinámico de feeds:

1. Una ejecución solo puede reconocer P&L si todas las patas con fill efectivo se aplican a
   venues existentes en el ledger.
2. Rechazar una ejecución es atómico: no cambia balances, posición abierta, P&L, series,
   métricas ni persistencia de ejecuciones.
3. El conjunto de venues activos de `Settings`, portfolio, ingestors y UI no diverge dentro
   de un proceso.
4. Las ediciones hot seguras —fees, balances iniciales, tamaño y umbrales— se conservan.

## No objetivos

- No construir el supervisor dinámico de feeds (arranque/parada de ingestors en caliente);
  queda post-entrega (§14 del plan).
- No cambiar la fórmula económica ni el modelo de P&L (realized/unrealized/equity).
- No añadir estrategias, mercados, estados de ejecución ni motivos de descarte nuevos.
- No endurecer en este bloque el saneo numérico de fills; se conserva el contrato de
  `_leg_amounts()` (`backend/app/sim/inventory.py:339-345`).
- No cambiar el flujo económico de replay/backtest; solo debe respetar el resultado de
  aplicación del ledger y conservar sus tests verdes.

## Usuario

- Jurado que audita la consistencia contable ("¿puede este sistema inventar P&L?").
- Operador que edita la configuración base y necesita saber qué aplica en caliente y qué
  requiere reinicio.
- Desarrollador que usa los invariantes del ledger para razonar sobre el simulador.

## Estado actual

Existe:

- `Portfolio` con doble entrada, separación realized/unrealized, skew y rebalanceo
  (`backend/app/sim/inventory.py:57-517`).
- `can_afford()` como gate de capital/inventario del camino live
  (`backend/app/main.py:143-156`) y del replay
  (`backend/app/backtest/replay.py:182-201`).
- `apply_execution()` que mueve balances físicos por pata, actualiza leg risk y acumula
  `realized_pnl` (`backend/app/sim/inventory.py:347-387`).
- Configuración persistida que se aplica antes de crear portfolio e ingestors al arrancar
  (`backend/app/main.py:61-83`, `backend/app/main.py:282-286`).
- `ConfigPanel.tsx` con toggle editable de `enabled` y texto que promete aplicación inmediata
  (`frontend/components/ConfigPanel.tsx:13-17`,
  `frontend/components/ConfigPanel.tsx:149-161`).

Brecha:

- El gate pre-trade permite venues ausentes.
- El ledger muta antes de saber si puede aplicar la ejecución completa.
- El endpoint puede dejar tres estados híbridos: runtime sin persistir, persistencia sin
  portfolio actualizado, o portfolio distinto de los feeds vivos.
- El caller marca, mide y persiste una ejecución como capturada antes de conocer el resultado
  del ledger (`backend/app/main.py:175-203`).

## Requisitos funcionales

### RF-001 `can_afford()` estricto con venues requeridos

`Portfolio.can_afford()` debe devolver `False` si `buy_venue` o `sell_venue` no están en
`self.venues`. La comprobación ocurre antes de calcular coste o consultar balances. Se elimina
el comportamiento permisivo de `backend/app/sim/inventory.py:229-232` y se actualiza su
docstring, que hoy justifica la permisividad por consistencia con el `apply_execution`
permisivo (`backend/app/sim/inventory.py:213-214`): ambos lados del argumento desaparecen a
la vez.

El camino live conserva `DiscardReason.insufficient_balance`, ya usado en
`backend/app/main.py:148-156`; este bloque no añade un valor nuevo al enum. La oportunidad debe
quedar contabilizada como `discarded`, no como `executable` ni `captured`.

### RF-002 `apply_execution()` transaccional

`Portfolio.apply_execution()` cambia su contrato a `apply_execution(execution) -> bool`:

- `True`: se aplicaron todos los efectos válidos de la ejecución y, si es finito, su P&L se
  acumuló exactamente una vez.
- `False`: la ejecución fue rechazada; el estado del portfolio es idéntico bit a bit en sus
  campos contables al estado de entrada.

La operación tiene tres fases sin `await`:

1. **Preparar y validar.** Calcular una sola vez `_leg_amounts()` para cada pata. Toda pata
   con `qty` saneada mayor que cero debe apuntar a un venue de `self.venues`. Si el bloque de
   leg risk cumple las condiciones que hoy lo hacen aplicable —venue y lado presentes,
   `leg_risk_qty > _DUST` finita y VWAP de entrada positivo y finito—, ese venue también debe
   existir. Una referencia ausente termina aquí con `False`.
2. **Aplicar sobre estado protegido.** Capturar antes de mutar los cuatro campos contables de
   cada venue afectado (`btc`, `quote`, `open_btc`, `open_cost_basis_usd`) y
   `self.realized_pnl`; aplicar balances, posición abierta y P&L en el orden actual.
3. **Confirmar o restaurar.** Si ocurre una excepción durante la mutación, restaurar el
   snapshot completo, registrar el rechazo y devolver `False`. Solo el final exitoso devuelve
   `True`.

Un rechazo por venue ausente debe emitir un log estructurado `warning` con, como mínimo,
`execution_id`, `opportunity_id`, fase (`leg` o `leg_risk`) y venues ausentes. No se crea un
venue implícitamente y no se permite el patrón “omitir la pata y continuar”.

### RF-003 Propagación del resultado del ledger

Los callers deben respetar el booleano de RF-002:

- En live (`on_opp`, `backend/app/main.py:126-204`), reordenar el bloque de captura: hoy
  `captured` se incrementa (`backend/app/main.py:185`) y `metrics.record_execution` se llama
  (`backend/app/main.py:188-189`) **antes** de `apply_execution`
  (`backend/app/main.py:194`). El orden nuevo es: aplicar al portfolio primero y, solo con
  `True`, incrementar `captured` y `unwound`, registrar métricas, sellar equity
  (`record_equity_point`), publicar P&L (`publish_pnl`) y encolar en el writer. Si devuelve
  `False`: la opp llega con `status=captured` (la mutó `simulate`,
  `backend/app/main.py:175`) y debe reclasificarse a `discarded` con el
  `DiscardReason.insufficient_balance` existente **antes** de
  `publisher.publish_opportunity(opp)` (`backend/app/main.py:204`) y de la captura del
  shadow sample (PRD-005), que usan el estado final; reconciliar el funnel exactamente una
  vez con `_move_viable_to_discarded()` (`backend/app/main.py:118-124`). El contador
  `executable` ya incrementado (`backend/app/main.py:171`) **permanece**: la opp sí fue
  sometida a ejecución, misma semántica que el descarte pre-trade del simulador
  (`backend/app/main.py:178-183`).
- En replay/backtest (`backend/app/backtest/replay.py:201-208`), añadir el trade a `trades`
  y el punto a `equity_curve` únicamente si devuelve `True`; con `False`, `continue`.
- En validación canónica (`backend/app/validate/report.py:54`), afirmar explícitamente que
  la aplicación devuelve `True` antes de comprobar invariantes.

Así, una defensa de último recurso del ledger no deja evidencia aguas abajo que contradiga el
estado contable.

### RF-004 `enabled` en caliente: variante A elegida (bloqueo)

Se adopta la variante mínima del Bloque 1: `enabled` **no es editable mediante el endpoint en
caliente**.

- `PUT /api/v1/config/sim` compara cada `enabled` **enviado explícitamente** en el body
  (`ov.enabled is not None`, semántica de `ExchangeOverride`,
  `backend/app/models/config.py:15`) con el valor runtime actual
  (`ctx.settings.exchanges[venue].enabled`). La comprobación va después del `422` de venue
  desconocido (RF-007) y antes del merge/persistencia. Si al menos uno difiere, rechaza
  **todo** el request con HTTP `409`; no persiste, no muta `Settings`, no re-siembra y no
  limpia caches.
- El `detail` del `409` es un objeto con forma exacta
  `{"code": "venue_restart_required", "venues": ["kraken", ...], "message": "..."}` —
  `venues` es la lista ordenada alfabéticamente de los que difieren y `message` indica que
  el cambio debe hacerse en la configuración de despliegue y requiere reiniciar el servicio.
  La UI y PRD-010 dependen de esta forma: no cambiarla sin versionar.
- Un payload completo que repita valores `enabled` sin cambiarlos es válido; esos campos son
  no-op. Esto mantiene compatibilidad temporal con el payload actual de la UI
  (`frontend/components/ConfigPanel.tsx:77-97`).
- `GET /api/v1/config/sim` sigue mostrando el estado runtime. No se introduce
  `restart_required`, porque esta variante nunca almacena un estado pendiente.

La configuración persistida se sigue aplicando durante el arranque antes de construir el
portfolio y los feeds (`backend/app/main.py:61-83`, `backend/app/main.py:282-286`), por lo que
un reinicio produce un único conjunto coherente.

### RF-005 UI coherente con el bloqueo de `enabled`

`ConfigPanel.tsx` debe:

- mostrar el switch de `enabled` deshabilitado;
- acompañarlo con texto o tooltip accesible “Requiere reiniciar el servicio”; no comunicarlo
  solo con color;
- no enviar cambios de `enabled` generados por interacción;
- mostrar el mensaje específico devuelto por el backend si recibe `409` (parsear
  `body.detail.code === 'venue_restart_required'` y `detail.message`), distinto del error
  genérico de red: hoy `save()` colapsa todo fallo en un `throw new Error(status)` con
  notificación genérica (`frontend/components/ConfigPanel.tsx:98-107`);
- reemplazar los textos que hoy afirman que venues y toda la configuración se aplican “al
  instante” (`frontend/components/ConfigPanel.tsx:113-117`,
  `frontend/components/ConfigPanel.tsx:236-245`), incluyendo el Alert que promete que
  guardar **siempre** re-siembra balances y reinicia el P&L: con RF-006 el reseed pasa a ser
  condicional (solo si cambian `initial_btc`/`initial_quote`).

### RF-006 Ediciones hot seguras se conservan

La API mantiene editables `fee_taker`, `initial_btc`, `initial_quote`,
`default_trade_qty_btc`, `min_net_profit_usd`, `max_slippage` y `exec_latency_ms`, dentro de
las validaciones existentes de `SimConfig` (`backend/app/models/config.py:12-28`).

“Cambiar” se define comparando el **valor efectivo tras el merge** contra el valor runtime
actual de `Settings`, no por presencia de la clave en el payload: la UI reenvía siempre el
snapshot completo de todos los venues (`frontend/components/ConfigPanel.tsx:77-92`), así que
presencia ≠ cambio. Hoy `apply_sim_config` añade fees/balances/umbrales a `changed` aunque el
valor sea idéntico (`backend/app/store/config_store.py:65-85`); hay que extender a todos los
campos la comparación “solo si difiere” que ya hace `enabled`
(`backend/app/store/config_store.py:62`), y esa misma lista de diferencias reales decide el
reseed y alimenta la respuesta.

- Cambiar `initial_btc` o `initial_quote` (valor efectivo distinto del runtime) re-siembra el
  portfolio y reinicia inventario, P&L, curva y contadores, como documenta
  `backend/app/sim/inventory.py:185-196`. Reenviar los mismos balances no re-siembra.
- Cambiar únicamente fees, tamaño o umbrales actualiza `Settings` y limpia la cache de
  proyección, pero **no** re-siembra ni borra el P&L de la sesión.
- La respuesta `200` incluye la lista exacta de campos aplicados y el snapshot runtime final.

### RF-007 Configuración sin aplicación parcial

El handler sigue este orden observable:

1. Validar el body con Pydantic/FastAPI.
2. Rechazar claves de venue que no existan en `Settings` con `422` (claves de
   `body.exchanges` contra `ctx.settings.exchanges`).
3. Rechazar cambios explícitos de `enabled` con `409`, comparándolos contra el runtime.
4. Cargar y validar la fila persistida y hacer el merge. El `422` de venue desconocido vive
   en el handler y solo considera las claves del body. `apply_sim_config` conserva su tolerancia
   a venues desconocidos (`backend/app/store/config_store.py:59-60`), porque la ruta de arranque
   debe seguir cargando una config persistida que mencione un venue ya retirado del despliegue
   (`test_config_store.py::test_apply_sim_config_ignores_unknown_venue` sigue válido).
5. Preparar sobre copias profundas la configuración runtime final y, solo si cambian balances
   iniciales, el portfolio re-sembrado. Ninguna preparación muta `ctx`.
6. Persistir el documento combinado en una transacción.
7. Tras el commit, sin ningún `await` intermedio, aplicar los valores ya preparados, sustituir
   el portfolio preparado cuando corresponda y limpiar la cache.
8. Responder `200` únicamente cuando persistencia y runtime representan el mismo resultado.

Un fallo de validación o persistencia deja intactos `Settings`, portfolio, cache y fila previa.
No se conserva el orden actual “mutar → persistir → reseed” de
`backend/app/api/v1/router.py:535-551`, porque permite estado parcial ante una excepción. Si la
implementación introduce una operación falible después del commit, debe restaurar también la
fila previa antes de devolver error; la solución preferida es terminar todo lo falible en la
fase de preparación.

La ruta de arranque debe conservar la capacidad de aplicar `enabled` persistido; el bloqueo
solo rige para el camino hot. Si se prepara un `Portfolio` con una copia de `Settings`, antes de
publicarlo se debe enlazar a la instancia canónica `ctx.settings`, que comparten el resto de los
componentes del motor.

## Arquitectura de redundancia y robustez del ledger

### Invariantes protegidos

1. **Doble entrada por pata.** `VenueBalance.move_physical()` mueve ambos lados del balance:
   compra `−quote(coste+fee), +btc`; venta `+quote(neto−fee), −btc`
   (`backend/app/sim/inventory.py:86-98`).
2. **Conservación.** En una ejecución casada, el BTC agregado se conserva y el quote agregado
   cambia por flujo económico y fees; cualquier excedente de leg risk queda explícito en
   `open_btc`/`open_cost_basis_usd`, no desaparece.
3. **Consistencia P&L↔equity.** `total_pnl = realized + unrealized`; el tramo casado vive una
   vez en realized y la posición abierta se marca una vez como unrealized
   (`backend/app/sim/inventory.py:17-27`).
4. **Atomicidad de ejecución.** El fingerprint contable
   `{venues[*].(btc, quote, open_btc, open_cost_basis_usd), realized_pnl}` cambia por todos los
   efectos de una ejecución aceptada o no cambia en absoluto.
5. **Correspondencia de evidencia.** Una ejecución solo cuenta como `captured`, alimenta
   métricas, equity y persistencia si RF-002 devuelve `True`.
6. **Coherencia de venues.** Durante un proceso,
   `enabled(Settings) = keys(Portfolio.venues) = venues configurados en los ingestors = activos
   que muestra la UI`, cuando `ingest_autostart` está habilitado. Con autostart deshabilitado no
   hay ingestors por diseño, pero Settings, portfolio y UI siguen coincidiendo. El endpoint no
   puede alterar uno de esos conjuntos de forma aislada; la salud de una conexión se reporta
   aparte y no redefine `enabled`.

### Capas de defensa

```text
Config/UI: bloquea hot-toggle
        ↓
Gate pre-trade: can_afford exige ambos venues
        ↓
Commit del ledger: valida todas las patas y leg risk
        ↓
Callers: solo publican/persisten si el commit fue exitoso
        ↓
Tests + log estructurado: detectan regresión y anomalías residuales
```

Las capas no sustituyen unas a otras. RF-001 reduce entradas inválidas en el flujo normal;
RF-002 protege llamadas directas, replay y carreras lógicas; RF-003 evita una “captura” sin
asiento; RF-004 elimina la fuente conocida de divergencia runtime.

### Matriz de fallos parciales

| Fallo | Resultado exigido | Evidencia |
|---|---|---|
| Falta buy venue, sell venue o venue de leg risk efectivo | `apply_execution=False`; fingerprint idéntico | log `warning` + test |
| Excepción al aplicar la segunda pata o leg risk | rollback del snapshot; cero P&L | log con `execution_id` + test con fallo inyectado |
| `realized_pnl` no finito | comportamiento actual: no se acumula; las patas válidas sí se aplican | regresión existente |
| Body/config merge inválido | HTTP `422`; cero cambios runtime/DB | respuesta + test |
| Cambio de `enabled` | HTTP `409`; cero cambios runtime/DB/cache | código y venues en respuesta + test |
| Fallo de escritura DB | respuesta no-2xx; runtime, portfolio, cache y fila previa intactos | test con `save_app_config` fallando |
| Fallo preparando el portfolio | respuesta no-2xx antes de persistir; estado intacto | test con constructor/reseed fallando |
| Caída del proceso después del commit DB | no se devuelve éxito parcial; al reiniciar se carga la config persistida antes de crear runtime | prueba de reinicio |

### Visibilidad y concurrencia

`on_opp` es una función síncrona (`backend/app/main.py:126-204`) y el proceso usa un solo event
loop (`backend/app/main.py:1-6`). RF-002 no contiene `await`: ningún handler, snapshot o evento
SSE del mismo proceso puede intercalarse entre sus mutaciones. El snapshot de rollback cubre
excepciones inesperadas y el caller no publica hasta recibir `True`.

El endpoint de configuración sí hace I/O asíncrono. Por eso prepara sin mutar, espera el commit
y realiza el cambio runtime final sin `await`; así un lector ve el estado anterior completo o el
nuevo completo, nunca una mezcla construida por el handler.

## Cambios técnicos

Backend:

- `backend/app/sim/inventory.py` — endurecer `can_afford()`; hacer transaccional
  `apply_execution()` y devolver `bool`; actualizar docstrings y logging.
- `backend/app/main.py` — consumir el resultado del ledger antes de contar, medir, publicar o
  persistir la ejecución.
- `backend/app/backtest/replay.py` y `backend/app/validate/report.py` — respetar/afirmar el
  resultado booleano sin cambiar el cálculo económico.
- `backend/app/store/config_store.py` — separar preparación/aplicación y no mutar `enabled` en
  el camino hot.
- `backend/app/api/v1/router.py` — bloqueo `409`, validación de venues, commit ordenado y reseed
  solo ante cambios de balances.
- Tests nuevos de regresión descritos en la sección Pruebas.

Frontend:

- `frontend/components/ConfigPanel.tsx` — switch de `enabled` deshabilitado y accesible, textos
  contractuales correctos y tratamiento específico de `409`.

## Plan de implementación

1. Escribir los seis tests obligatorios del gate y los tests unitarios de retorno/rollback.
2. Implementar RF-001 a RF-003 y ejecutar las pruebas de inventory, prioritizer, replay y
   validación.
3. Implementar RF-004, RF-006 y RF-007; cubrir `409`, venue desconocido y fallos inyectados.
4. Ajustar `ConfigPanel.tsx` según RF-005 y verificar las ediciones hot restantes.
5. Ejecutar suite completa backend y smoke dirigido del panel.

Timebox: 2 h (Bloque 1). Regla de corte del plan: **nunca cortar este bloque**.

## Pruebas

Tests obligatorios del plan (gate de salida — sin esto no hay redeploy):

1. Ejecución con buy venue desconocido devuelve `False` y conserva el fingerprint completo.
2. Ejecución con sell venue desconocido devuelve `False` y conserva el fingerprint completo.
3. Ninguna pata se aplica parcialmente: fallo en la segunda pata y fallo inyectado durante la
   mutación restauran todos los campos y no crean punto de equity.
4. Sin P&L fantasma por venue deshabilitado, en dos partes: (a) intentar deshabilitar un venue
   mediante `PUT /api/v1/config/sim` devuelve `409` y no cambia nada (el venue sigue operativo
   y coherente); (b) en el escenario de divergencia que el bloqueo previene —portfolio
   arrancado con ese venue `enabled=false`, no sembrado (la reproducción del Problema)— una
   oportunidad que lo usa da `can_afford() == False` (descartada `insufficient_balance`) y una
   aplicación forzada de su ejecución devuelve `False`: cero P&L, cero `captured`, cero filas.
5. Una configuración rechazada o un fallo de persistencia deja iguales el dump de `Settings`,
   el fingerprint del portfolio, la cache y la fila `app_config` previa.
6. Las invariantes de conservación y doble entrada pasan antes y después de un cambio de config
   hot aceptado.

Ubicación ejecutable de los tests:

- Tests 1–3 y 4b: `backend/tests/test_inventory.py`, reutilizando los helpers existentes
  `_exec`/`_leg`/`_book`/`_settings` (`backend/tests/test_inventory.py:20-60`), que ya
  construyen `Execution` a mano con leg risk derivado. El fallo inyectado del test 3 se hace
  con `monkeypatch` sobre `VenueBalance.move_physical` o `add_open_position` lanzando en la
  segunda pata. Dos tests existentes afirman el comportamiento permisivo y deben invertirse,
  no borrarse: `test_inventory.py::test_apply_execution_ignores_unknown_venue_leg`
  (`backend/tests/test_inventory.py:917-927`) y
  `test_prioritizer.py::test_can_afford_unknown_venue_not_blocked`
  (`backend/tests/test_prioritizer.py:249-253`).
- Tests 4a, 5 y 6 (camino API): archivo nuevo `backend/tests/test_config_api.py` con el
  fixture `client` de `backend/tests/conftest.py:18-23` (ejecuta el lifespan real con DB en
  memoria y `ARB_INGEST_AUTOSTART=false`; `control_token` vacío en dev, así el PUT pasa sin
  header). Como `get_settings()` está cacheado y el endpoint muta la instancia canónica, estos
  tests deben limpiar esa cache antes y después de cada caso (o restaurar un snapshot profundo)
  para que un PUT aceptado no contamine los demás tests. El fallo de persistencia del test 5 se
  inyecta con `monkeypatch` sobre `save_app_config`. Los tests unitarios de merge/aplicación
  siguen en `backend/tests/test_config_store.py`.

Complementarios:

- `can_afford()` devuelve `False` por separado con buy o sell venue ausente.
- Leg risk efectivo en venue ausente rechaza la ejecución completa.
- Un rechazo del ledger reconcilia el funnel una vez y no llega a writer, metrics ni SSE de P&L.
- Un payload con `enabled` sin cambios es `200`; uno con varios cambios es un único `409` cuya
  lista de venues está ordenada.
- Fees/tamaño/umbrales aplican y persisten sin resetear P&L; balances iniciales aplican,
  persisten y sí lo reinician.
- Venue inexistente en el payload devuelve `422` sin aplicar los demás campos válidos.
- Un payload que combina venue inexistente y cambio de `enabled` devuelve `422`, no `409`.
- El caso canónico `$109.75` sigue reconciliando con delta `0.0000`.

## Criterios de aceptación

- Los seis tests obligatorios pasan y fallan contra el comportamiento anterior.
- Para cada rechazo probado, el fingerprint anterior y posterior es exactamente igual y
  `realized_pnl`, longitud de `equity_series`, `captured` y filas de ejecución tienen delta cero.
- No quedan `continue` permisivos para venues ausentes en la ruta de mutación del ledger ni un
  `return True` por venue ausente en `can_afford()`.
- `PUT /api/v1/config/sim` devuelve `409` para cualquier cambio de `enabled`; el body incluye
  `code=venue_restart_required` y todos los venues divergentes, sin cambios observables.
- Un PUT hot aceptado conserva P&L si no cambia balances y reinicia P&L exactamente una vez si
  cambia `initial_btc` o `initial_quote`.
- La UI no permite accionar el switch, comunica textualmente el reinicio y distingue `409` de
  un fallo de red.
- Suite backend verde: `ruff`, `mypy --strict` y `pytest` con cobertura global ≥85%; frontend
  verde: typecheck, lint y build.
- Se mantiene el gate Go del plan (§8): no existe un camino probado que acumule P&L con una
  pata ausente.

## Riesgos

- Endurecer `can_afford()` puede descartar fixtures o replays con venues no sembrados.
  Mitigación: corregir fixtures y afirmar `insufficient_balance`; nunca relajar el gate.
- Cambiar `apply_execution()` a `bool` puede dejar un caller que ignore el rechazo. Mitigación:
  búsqueda global de callers y tests de no-propagación en live, replay y validación.
- El rollback puede quedar incompleto al añadir nuevos campos contables. Mitigación: helper
  único de snapshot/restore y test que compare todos los slots de `VenueBalance`.
- Reordenar persistencia/runtime puede introducir un estado híbrido. Mitigación: preparar todo
  antes del commit, no ejecutar `await` después y probar fallos en cada frontera.
- Deshabilitar el switch elimina una operación que antes parecía disponible. Mitigación: texto
  explícito con el procedimiento de configuración de despliegue + reinicio.
- Interacción con Bloque 2/PRD-010: `ConfigPanel` hoy no envía `X-Control-Token`, así que con
  token configurado el PUT devuelve `401` antes de poder devolver `409`. El manejo de errores
  de RF-005 debe ramificar por status (`401` ≠ `409` ≠ red) para que el trabajo de PRD-010
  sobre auth no pise el mensaje de reinicio ni viceversa.

## Fuera de alcance

- **Supervisor dinámico de feeds** (crear/parar ingestors al cambiar `enabled` en caliente):
  diferido a post-entrega (§14 del plan). Hasta entonces, el endpoint bloquea el cambio.
- Persistir un cambio pendiente de `enabled` y exponer `restart_required` (variante B); no se
  implementan dos contratos simultáneos.
- BFF/OIDC con roles y bitácora de mutaciones (Bloque 2, opción B).
- Cableado de `leg_failure` en vivo (`sell_book_t1` en el player) y unificación del evaluador
  con `_top_sane`.
