# PRD-013: Escenarios honestos — `esperado → observado`

Estado: Propuesto  
Prioridad: P0 (cierre 12-jul, Bloque 5)  
Área: Backend (identidad de ventana y harness opcional), Frontend  
Dependencias: ninguna funcional; coordina narrativa con PRD-012 y Bloque 6  
Plan: [docs/plan-accion-final-12jul.md](../plan-accion-final-12jul.md) §5, Bloque 5

## Problema

Los escenarios jury declaran o sugieren resultados, pero la demo no acredita que esos resultados
**ocurrieron durante la activación visible**. Hay dos contradicciones verificadas:

1. `order_failure` declara `preflight_or_test_order_reject`
   (`backend/app/demo/scenarios.py:178-198`), pero el player sólo construye frames de books
   (`backend/app/demo/scenarios.py:239-252`) y el fallback sólo aplica peg e inyecta esos books
   (`backend/app/demo/fallback.py:218-241`). No se invoca preflight ni test-order.
2. El simulador soporta fill parcial, leg risk y unwind
   (`backend/app/sim/simulator.py:231-391`), pero el unwind requiere una relectura explícita
   `sell_book_t1` (`backend/app/sim/simulator.py:133-160` y
   `backend/app/sim/simulator.py:196-230`). Replay/backtest sí la inyecta
   (`backend/app/backtest/replay.py:196-200`). En vivo, el evaluador reduce ambas patas a la misma
   cantidad ejecutable (`backend/app/engine/evaluator.py:142-159`) y el simulador reutiliza el
   snapshot inicial cuando `sell_book_t1` es `None` (`backend/app/sim/simulator.py:157-190`); por
   tanto, el wiring live actual no demuestra unwind.

Además, hoy sólo tres de los siete escenarios tienen `expected_result` explícito:
`latency_decay`, `thin_book` y `order_failure` (`backend/app/demo/scenarios.py:151`,
`backend/app/demo/scenarios.py:176`, `backend/app/demo/scenarios.py:196`). El panel ya pinta
`esperado`, pero no pinta `observado`. Un badge o una descripción no son evidencia.

## Objetivo

Para cada activación de un escenario jury, la UI muestra siempre dos líneas:

- `esperado: <contrato del escenario>`.
- `observado: <efecto medido en esta activación, ausencia de efecto o falta de telemetría>`.

La evidencia queda ligada a una activación concreta, no al total histórico de la sesión. Si no se
puede observar un resultado, se dice literalmente y el claim se retira o reformula.

## No objetivos (las cuatro prohibiciones del plan)

- **No introducir datos futuros en el pipeline live**: `sell_book_t1` sigue siendo exclusivo de
  replay/backtest y pruebas deterministas.
- **No cambiar el significado de `sell_book_t1` ni el clamp del evaluador.**
- **No afirmar un unwind si sólo cambió un badge**: se demuestra mediante replay/backtest y se
  etiqueta como tal.
- **No mostrar `expected_result` sin `observed_result`**: ante evidencia ausente, inconsistente o
  vencida se muestra ese estado; nunca se infiere éxito.

El cableado live de `leg_failure` confinado al player queda post-entrega.

## Usuario

- Jurado que ve un escenario activado por el operador y necesita distinguir claim de evidencia.
- Operador que debe reproducir y defender cada resultado sin depender de DevTools.

## Estado actual

Contrato verificado:

- `DemoFallback.status()` expone en jury `scenario`, `scenario_description`, `scenario_kind`,
  `expected_result`, `scenario_index` y `n_scenarios`
  (`backend/app/demo/fallback.py:161-185`). No expone una identidad de activación ni evidencia.
- `MetricsCollector` incrementa `discard_reasons` cuando una oportunidad trae motivo
  (`backend/app/metrics/collector.py:84-100`) y lo expone como acumulado de sesión
  (`backend/app/metrics/collector.py:202-204`, `backend/app/metrics/collector.py:232-244`; tipo del
  cliente en `frontend/hooks/useStream.ts:106-116`). El total no se puede presentar como resultado
  del escenario vigente.
- El player repite cada escenario diez ticks (`backend/app/demo/scenarios.py:209-216` y
  `backend/app/demo/scenarios.py:239-251`). Con los defaults actuales son 500 ms por escenario
  (`backend/app/config.py:195`), mientras el push SSE de métricas está limitado a una muestra por
  segundo (`backend/app/config.py:214`, `backend/app/stream/pump.py:59-68`). Por tanto, el delta no
  es aceptable hasta garantizar una muestra posterior a la línea base dentro de la activación.
- Los eventos `opportunity` contienen el estado final y `discard_reason`; sirven como evidencia
  directa de baja latencia. El acumulado de métricas sirve como respaldo ante pérdida de un evento
  SSE, no como sustituto silencioso de la atribución temporal.

## Contrato observable por escenario

El catálogo debe declarar un `expected_result` verificable para cada escenario o declarar
literalmente que no existe claim. La implementación se valida contra esta tabla; si el fixture real
produce otra salida, se corrige el fixture o se reformula el claim, nunca se maquilla en la UI.

| Escenario | `esperado` mínimo | Evidencia primaria | Respaldo |
|---|---|---|---|
| `good_edge` | `captured` | evento `opportunity.status=captured` | delta `captured > 0` |
| `naive_trap` | `not_profitable_fees` | `opportunity.discard_reason` | delta homónimo en `discard_reasons` |
| `peg_adverse` | `peg_adverse` | `opportunity.discard_reason` | delta homónimo en `discard_reasons` |
| `stale_feed` | `stale_data_excluded` | estado de feed/breaker stale | ningún trade y señal stale; ausencia de oportunidad por sí sola no prueba el claim |
| `latency_decay` | `slippage_over_limit` | `opportunity.discard_reason` | delta homónimo en `discard_reasons` |
| `thin_book` | `thin_book` | `opportunity.discard_reason` | delta homónimo en `discard_reasons` |
| `order_failure` | reject local real **o claim retirado** | RF-003A o RF-003B | nunca se deduce de books ni de `discard_reasons` |

## Requisitos funcionales

### Corte mínimo del timebox (60 min, regla de corte §6 del plan)

Este bloque tiene 60 minutos. Lo **mínimo** que debe quedar verde es:

1. Backend: `scenario_run_id` + `scenario_started_at` en `status()` y subir la duración por
   escenario a 45 repeticiones (RF-002 identidad + cadencia).
2. Frontend: al ver un `run_id` nuevo, armar la baseline con el primer snapshot SSE de métricas
   recibido después de abrir la ventana, contar
   eventos `opportunity` con `t_recv >= scenario_started_at` y pintar siempre las dos líneas con
   tres estados: `pending` / `observed` / `absent`; la insuficiencia, inconsistencia y reinicio de
   telemetría son motivos visibles de `absent`, no estados adicionales
   (RF-001 + RF-002 núcleo).
3. `order_failure`: RF-003B (reformular el badge) como decisión por defecto.
4. Contratos `expected_result` completos o retirados para los siete escenarios.

Es **stretch** (sólo si el mínimo cierra antes de tiempo): la elevación a “verificado” cuando
coinciden las dos fuentes, el fetch de
`GET /metrics` iniciado al abrir la ventana para obtener una baseline tardía, la exigencia de
transición stale posterior en
`stale_feed` (mínimo: mostrar el estado feed/breaker vigente con su timestamp), y el harness
RF-003A. En el mínimo, un delta negativo simplemente resetea la baseline y muestra
`absent · telemetría reiniciada`; una baseline irrecuperable muestra
`absent · telemetría insuficiente` hasta el siguiente `run_id`. Nada del corte mínimo viola las
cuatro prohibiciones: nunca se muestra `esperado` sin
`observado` y `pending`/`absent` son estados honestos, no éxito.

### RF-001 Dos líneas para toda activación jury

En la superficie donde se ve el badge jury:

1. Mostrar siempre `esperado` y `observado`; no esconder una línea por valor `null`.
2. Si el catálogo aún no declara resultado: estado `absent`,
   `esperado: sin resultado verificable declarado` y
   `observado: no aplica; no existe claim`. Esto es deuda visible, no aceptación del escenario.
3. Mientras no exista una muestra aplicable suficiente: estado `pending` y
   `observado: esperando evidencia (0 muestras posteriores)`.
4. Cuando ya existe una muestra aplicable suficiente pero no coincide: estado `absent` y
   `observado: sin efecto atribuido en esta activación`.
5. Ante telemetría reiniciada, datos insuficientes al evaluar el gate o fuentes contradictorias:
   estado `absent` y `observado: telemetría reiniciada`, `telemetría insuficiente` o
   `evidencia inconsistente`; no conservar el éxito de la activación anterior.
6. En la superficie pública read-only (PRD-010) no se muestran controles mutables: los chips de
   escenario de `frontend/components/ControlPanel.tsx:159-173` hacen `POST /demo/scenario/{name}`
   y quedan sólo en la superficie de operador. El cambio de escenario se dispara por CLI/SSH con
   token de control; las dos líneas se derivan exclusivamente de `GET /demo`, del backstop read-only
   `GET /control/status` (`backend/app/api/v1/router.py:882`) y de los eventos SSE (`demo`,
   `metrics`, `opportunity`, `breaker`), sin necesitar mutación alguna desde el navegador.

### RF-002 Identidad, línea base y delta de `discard_reasons`

#### Identidad de activación

Backend añade `scenario_run_id: int` y `scenario_started_at: float` (reloj monotónico del backend)
al estado jury. El ID empieza en 0 y aumenta monotónicamente una vez al entrar en cada escenario,
también al volver a seleccionar el mismo nombre; `scenario_started_at` toma el `now` del primer
frame. Los frames repetidos conservan ambos valores. `mode != jury`, proceso nuevo o
`demo.active=false` invalidan la ventana; el cliente nunca usa sólo `scenario`/`scenario_index` como
clave porque ambos se repiten.

El punto de incremento es único e inequívoco: `DemoFallback._emit_jury_next` cuando `changed` es
verdadero (`backend/app/demo/fallback.py:225-241`). Ese único punto cubre los dos disparadores
reales de cambio de escenario: el avance automático del player cada N repeticiones
(`backend/app/demo/scenarios.py:239-252`) y la selección explícita vía
`POST /demo/scenario/{name}` o CLI, porque `select_jury_scenario` deja `_jury_frame = None`
(`backend/app/demo/fallback.py:110-120`) y el siguiente frame computa `changed=True`. El contador
es monotónico por proceso y no se reinicia al salir y volver a entrar en jury. El estado de
identidad vive sólo en backend; la baseline y el delta viven sólo en frontend (siguiente sección).

El `run_id` llega al cliente por dos transportes y la ventana debe abrirse con el primer valor
nuevo que vea, venga por donde venga: el evento SSE `demo` se emite **sólo al cambiar**
(`backend/app/stream/pump.py:82-85`), y el polling backstop de `GET /demo`
(`frontend/hooks/useStream.ts:673`, `backend/app/api/v1/router.py:1059`) puede entregar el mismo
estado antes o después del evento. Ambos pasan por `status()`, así que exponen valores idénticos.

#### Estado y ciclo de vida en cliente

El estado vive en un único `useRef<ScenarioObservationWindow>` dentro de
`frontend/hooks/useStream.ts`, junto al manejo de eventos `demo`, `metrics`, `opportunity` y
`breaker`; no se duplica en `ControlPanel`. La UI recibe un objeto derivado e inmutable:

```text
ScenarioObservationWindow
  runId, scenario, expectedReason, backendStartedAt
  baselineReasons: Record<string, number> | null
  latestReasons: Record<string, number>
  directReasons, directReasonsSinceBaseline: Record<string, number>
  baselineCaptured, latestCaptured
  postBaselineMetricSamples, directSamples
  status: pending | observed | absent
  detail: awaiting_evidence | no_claim | no_effect | telemetry_restarted
          | telemetry_insufficient | evidence_inconsistent
```

En el corte mínimo el estado toma `pending | observed | absent`; `detail` explica por qué sin
crear estados paralelos. La elevación de `observed` a “verificado” llega con el etiquetado stretch.
Nota de
implementación: el payload SSE `opportunity` ya incluye `t_recv` porque el backend publica
`opp.model_dump(mode="json")` (`backend/app/stream/pump.py:54-57`,
`backend/app/models/opportunity.py:29`); sólo falta añadir el campo a la interfaz `Opportunity` de
`frontend/hooks/useStream.ts:23-40`. `t_recv` y `scenario_started_at` comparten el mismo
`time.monotonic` del proceso backend, así que son directamente comparables.

Al recibir un `scenario_run_id` nuevo (por evento `demo` o por el poll de `GET /demo`):

1. Dejar la baseline en `null` y armarla copiando —no referenciando— el primer snapshot SSE de
   métricas recibido **después** de abrir la ventana. Sólo los snapshots SSE observados en ese orden
   sirven en el corte mínimo: una respuesta de `GET /metrics` iniciada antes de conocer el nuevo ID
   puede ser anterior y no se reutiliza. Claves ausentes dentro del snapshot válido valen 0; copiar
   también `metrics.captured` para `good_edge`. Mientras no llega baseline, la ventana permanece
   `pending`; si el gate se evalúa sin ella, queda `absent · telemetría insuficiente`. Iniciar un
   `GET /metrics` al abrirla para acelerar esa primera muestra es stretch.
   Nunca se usa `{}` ni el último acumulado conocido como baseline: cualquiera de ambos convertiría
   actividad histórica o del escenario anterior en delta del escenario vigente. Al fijar la
   baseline se vacía `directReasonsSinceBaseline`, contador de comparación; `directReasons` conserva
   la evidencia primaria recibida desde el inicio de la activación.
2. Vaciar `directReasons`, contadores de muestras y cualquier resultado anterior.
3. Contar sólo eventos `opportunity` recibidos mientras ese `run_id` siga activo y con
   `opportunity.t_recv >= scenario_started_at`. Este corte monotónico evita atribuir al escenario
   nuevo books anteriores que seguían en la cola del motor. Si la baseline ya está fijada, sumar el
   evento también a `directReasonsSinceBaseline`.
4. Por cada snapshot de métricas posterior, calcular para la unión de claves
   `delta[r] = latest[r] - baseline[r]`. Un delta negativo indica reinicio/resync: se invalida la
   ventana, se toma la muestra como nueva baseline y se marca
   `absent · telemetría reiniciada`, nunca un número negativo. Sólo
   `directReasonsSinceBaseline` se compara con ese delta; los directos
   anteriores a la baseline no son fuentes temporalmente equivalentes.
5. Para `stale_feed`, en el mínimo copiar el estado feed/breaker vigente y mostrar su timestamp sin
   afirmar que la activación causó ese estado. Exigir una transición stale posterior a
   `scenario_started_at` y atribuirla a la activación es stretch; un breaker que ya estaba activo no
   prueba esa causalidad.
6. Finalizar como `observed` sólo con la señal esperada y al menos una muestra atribuible de la
   fuente aplicable. Un `delta=0` no es éxito. `stale_feed` usa una muestra de feed/breaker y
   RF-003A usa el resultado del harness; ninguno exige artificialmente una oportunidad o un
   snapshot de métricas que su propio comportamiento evita.

La ventana se borra al salir de jury, desactivarse demo, desmontarse el hook o cambiar de
`scenario_run_id`. Tras reconexión SSE, el cliente obtiene `GET /demo`; si perdió una transición y
no puede establecer una baseline posterior segura del `run_id` vigente, marca
`absent · telemetría insuficiente` y espera el siguiente ID. El `GET /metrics` de resync es stretch y sólo puede fijar una baseline nueva
para actividad posterior a su respuesta; no reconstruye la baseline perdida ni reutiliza una vieja.

#### Cadencia mínima

Debe cumplirse:

```text
duración_escenario = repeats_per_scenario × demo_replay_interval_ms
duración_escenario >= 2 × metrics_emit_ms + 250 ms
```

Con los defaults actuales (`demo_replay_interval_ms=50`, `metrics_emit_ms=1000`;
`backend/app/config.py:195` y `backend/app/config.py:214`), el mínimo es 45 repeticiones (2.25 s).
Hoy `repeats_per_scenario=10` es un default del constructor del player
(`backend/app/demo/scenarios.py:209-216`) y `DemoFallback` lo crea sin argumentos
(`backend/app/demo/fallback.py:66`); el cambio mínimo es pasar 45 ahí como constante, sin
introducir una setting nueva. El test de configuración falla si la desigualdad no se cumple. Así
existen al menos una oportunidad para fijar la baseline y otra muestra posterior en escenarios que
producen oportunidades; el contador directo SSE sigue dando respuesta inmediata. `stale_feed` y
RF-003 no usan el delta como fuente de aceptación.

#### Resolución mínima y elevación stretch

- Si llega el evento directo con la razón esperada: `observed · fuente SSE`. Si además coincide el
  delta acumulado, el mínimo conserva `observed`; sólo el stretch añade la etiqueta “verificado”.
- Si sólo llega un delta calculado desde la baseline posterior segura: `absent · telemetría
  insuficiente (delta en métricas)`; los acumulados no llevan timestamp de cada incremento y una cola anterior puede
  vaciarse después de abrir la ventana. Un acumulado contra una baseline vieja o desconocida nunca
  cuenta.
- Si las dos fuentes temporalmente equivalentes (`directReasonsSinceBaseline` y delta) están
  disponibles y discrepan: `absent · evidencia inconsistente` también en el mínimo; nunca se
  conserva éxito. Mientras no haya muestra aplicable suficiente, permanece `pending`; el gate no
  acepta ese estado.
- Estas reglas aplican a claims respaldados por métricas; no invalidan la señal independiente de
  feed/breaker ni el harness. La ausencia de datos no se convierte en cero.

### RF-003 `order_failure`: dos salidas aceptables y excluyentes

**Decisión por defecto: RF-003B (reformular el badge).** Es la salida segura para el timebox y
cumple la regla de corte §6.3 del plan (retirar el claim; `thin_book` demuestra el rechazo
pre-trade y el replay demuestra unwind). RF-003A es stretch: sólo sustituye a RF-003B si el corte
mínimo del bloque cierra antes de tiempo y el harness queda completamente verde. La decisión final
se registra en este PRD y en el guion antes del gate del Bloque 5.

#### RF-003A — Harness determinista aislado (stretch)

El harness **reutiliza código existente, no duplica simulación**: llama exactamente al mismo
`BinanceTestnetAdapter.preflight()` que ya sirve `POST /execution/preflight`
(`backend/app/api/v1/router.py:909-939`), pero sin pasar por ese endpoint (que exige token de
control y registra `record_preflight` en el collector — el harness no debe contaminar las métricas
de ejecución del operador). El preflight es 100 % local: los filtros `_BTCUSDT` son estáticos y en
`dry_run` el check de credenciales pasa sin secretos (`backend/app/execution/binance.py:34-39` y
`backend/app/execution/binance.py:148-167`).

El harness ejecuta **una sola vez por `scenario_run_id`** el preflight local real del adapter de
Binance, sin pasar por el pipeline live ni por un endpoint mutante:

- clona settings y fuerza `execution_mode="dry_run"`; no lee credenciales;
- crea `PreflightRequest(venue="binance", side="buy", symbol="BTCUSDT",
  quantity_btc=0.000001, order_type="market", reference_price=63000)`;
- llama directamente a `BinanceTestnetAdapter.preflight()`; el fixture es válido para Pydantic pero
  queda bajo `min_qty`, se redondea a cero y falla de forma determinista `min_qty`, `lot_size` y
  `min_notional` (`backend/app/execution/binance.py:72-117` y
  `backend/app/execution/binance.py:140-227`);
- el `reason` público es el primer check fallido según el orden estable del adapter (`min_qty`), no
  un texto elegido por la UI;
- no llama `test_order`, no toca red, portfolio, ledger, books, `discard_reasons` ni contadores de
  ejecución; tampoco expone secretos;
- publica en el estado demo sólo un resultado saneado ligado al ID vigente:

```json
{
  "scenario_run_id": 42,
  "observed_result": {
    "status": "observed",
    "source": "local_preflight_dry_run",
    "accepted": false,
    "reason": "min_qty",
    "network_used": false
  }
}
```

Mientras corre: `observado: preflight local pendiente`. Si termina después de cambiar de
`scenario_run_id`, se descarta su resultado. La UI dice `rechazo de preflight local dry-run`; queda
prohibido llamarlo rechazo del exchange o test-order real.

#### RF-003B — Reformulación honesta (decisión por defecto)

Se aplica de entrada, junto con el resto de contratos del catálogo; sólo se revierte si RF-003A
termina completamente verde dentro del bloque. Nunca se deja un harness parcial. Se elimina
`preflight_or_test_order_reject` y se usa exactamente:

- badge: `NO EJERCE EJECUCIÓN`;
- `esperado: sin claim de ejecución; sólo books deterministas`;
- estado `absent`; `observado: preflight/test-order no ejecutado`.

También es aceptable retirar `order_failure` del ciclo y del guion. En ambos casos, `thin_book`
demuestra el rechazo pre-trade y el replay demuestra unwind, conforme a la regla de corte del plan.

### RF-004 Unwind narrado vía replay

Todo `unwound`, leg risk o cambio por latencia se presenta como `replay/backtest`. La evidencia debe
incluir al menos una ejecución con `unwound=true` producida al pasar `sell_book_t1`; nunca se atribuye
al pipeline live ni a `order_failure`.

## Cambios técnicos

Backend obligatorio:

- `backend/app/demo/fallback.py`: incrementar `scenario_run_id` en `_emit_jury_next` cuando
  `changed`, sellar `scenario_started_at` y exponer ambos en `status()`. El contador es monotónico
  por proceso (no se reinicia al salir de jury; la ventana del cliente sí se invalida). No
  persistirlo entre procesos.
- `backend/app/demo/scenarios.py` + `backend/app/demo/fallback.py:66`: completar/reformular el
  contrato esperado del catálogo y subir `repeats_per_scenario` a 45 para cumplir RF-002.

Backend sólo con RF-003A (stretch):

- Añadir un servicio pequeño y testeable para el harness; `DemoFallback` conserva únicamente el
  resultado saneado de la activación vigente y lo expone desde `status()`.
- Sin cambios en `backend/app/engine/evaluator.py`, `backend/app/sim/simulator.py` ni
  `backend/app/backtest/replay.py`.

Frontend:

- `frontend/hooks/useStream.ts`: ser dueño único de identidad, baseline, deltas, contadores directos,
  señal de breaker, manejo de reconexión y estado derivado. El fetch explícito de resync queda en
  stretch.
- `ControlPanel` o superficie dedicada: sólo renderizar `esperado` / `observado`, fuente y estado;
  no recalcular deltas.

## Plan de implementación

1. Añadir `scenario_run_id`, completar contratos esperados (incluida la reformulación RF-003B de
   `order_failure`) y hacer medible la cadencia.
2. Implementar la ventana mínima: baseline + delta simple + contador directo por `t_recv`.
3. Renderizar siempre `esperado` / `observado` con
   `pending`/`observed`/`absent` y un motivo visible para cada `absent`.
4. Sólo si 1-3 cierran antes del minuto 40: abordar stretch (etiqueta “verificado”, fetch de
   resync, transición stale posterior y RF-003A).
   Al minuto 60 no queda claim provisional ni harness parcial.
5. Etiquetar unwind como replay en UI y guion.
6. Recorrer el ciclo jury completo y guardar evidencia de cada activación.

## Pruebas

Backend obligatorio:

- `test_scenario_run_id_increments_on_transition_and_same_name_reselection`.
- `test_repeated_frames_keep_scenario_run_id`.
- `test_jury_window_is_longer_than_two_metrics_intervals`.
- Test parametrizado del catálogo activo: cada fixture produce su señal declarada o declara
  explícitamente que no tiene claim. Son siete casos si RF-003B reformula `order_failure` y seis si
  lo retira.

Backend con RF-003A (sólo stretch):

- `test_order_failure_harness_rejects_min_qty_without_network` — dos ejecuciones producen el mismo
  resultado saneado y `accepted=false`.
- `test_order_failure_harness_runs_once_per_run_id`.
- `test_stale_harness_result_is_not_published_after_scenario_change`.
- `test_demo_status_contains_observed_result_without_secrets`.

Frontend mínimo (smoke instrumentado; el repositorio no tiene runner unitario frontend):

- Un nuevo `run_id` deja baseline `null`, delta/directos en cero y estado `pending`; el primer
  snapshot SSE posterior fija la baseline y no cuenta como delta.
- Clave ausente se trata como 0; snapshot ausente se trata como “sin muestra”, no como 0.
- Contador decreciente, reconexión sin baseline y discrepancia de fuentes no producen éxito.
- Salir de jury, desactivar demo o cambiar de ID borra la evidencia anterior.

Frontend stretch:

- La misma razón recibida por evento y métricas produce `observed` verificado.

## Criterios de aceptación

- Todos los escenarios del catálogo recorren al menos una activación y muestran simultáneamente
  ambas líneas. Son siete si `order_failure` se implementa/reformula y seis si RF-003B lo retira;
  API, `n_scenarios`, tests y guion deben coincidir con la decisión.
- 100 % de los escenarios con claim tienen una señal observada de la tabla en su mismo
  `scenario_run_id`; 0 claims dependen sólo de descripción, color o total histórico.
- Cada escenario respaldado por métricas recibe al menos una muestra posterior a la baseline; su
  gate falla con 0 muestras, delta negativo o fuentes contradictorias. `stale_feed` exige una
  muestra feed/breaker (transición posterior sólo en
  stretch) y RF-003A, si se implementó, exige la respuesta del harness para el mismo `run_id`.
- La UI y el objeto derivado sólo usan `pending`, `observed` y `absent`; insuficiencia,
  inconsistencia y reinicio aparecen como detalle de `absent`. Ningún `pending` o `absent` satisface
  un claim en el gate.
- `order_failure` cumple completamente RF-003B (por defecto) o RF-003A (stretch); no existe un
  estado intermedio aceptable.
- Sólo si RF-003A se implementó: su evidencia contiene `accepted=false`, `reason=min_qty`,
  `source=local_preflight_dry_run` y `network_used=false`, sin secretos.
- Todo unwind mostrado incluye fuente `replay/backtest` y una ejecución real con `unwound=true`.
- Los tests del gate confirman que el pipeline live no recibe `sell_book_t1` y que su semántica no
  cambió.

## Riesgos

- **Atribución cruzada por cadencia:** mitigada con `scenario_run_id`, duración mínima y muestras
  posteriores; no se usa el nombre como identidad.
- **Pérdida o retraso SSE:** mitigado en el mínimo con contador directo, baseline posterior segura,
  delta acumulado y degradación por discrepancia; el resync explícito es stretch.
- **Reinicio del backend:** un contador menor invalida la baseline y evita deltas falsos.
- **Harness confundido con exchange real:** copy literal `local_preflight_dry_run` y
  `network_used=false`; nunca se llama test-order real.
- **Timebox excedido:** RF-003B retira el claim sin violar el PRD.
- **Tentación de fabricar unwind live:** bloqueada por las cuatro prohibiciones y por RF-004.
