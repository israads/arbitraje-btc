# PRD-010: Superficie pública read-only (auth opción A)

Estado: Pendiente  
Prioridad: P0  
Área: Frontend, Deploy, Operación  
Dependencias: ninguna (bloquea a PRD-011 en el gate de deploy)  
Fuente: `docs/plan-accion-final-12jul.md:187-220` (Bloque 2, auth opción A), riesgo R2

## Problema

El backend tiene dos controles correctos e independientes:

- `backend/app/config.py:245-255` (`_require_control_token_in_prod`) impide arrancar con
  `ARB_ENV=prod` y `ARB_CONTROL_TOKEN` vacío.
- `backend/app/api/v1/router.py:86-97` valida `X-Control-Token`, y las rutas del plano de control
  declaran `Depends(require_control_token)`.

El frontend público, en cambio, renderiza acciones protegidas pero nunca envía ese header:

- `frontend/components/ControlPanel.tsx:44-58` — `post()` llama sin headers a kill switch, resume,
  cambio de modo y escenario; el `catch` no distingue 401 de fallo de red.
- `frontend/components/ConfigPanel.tsx:73-109` — `PUT /api/v1/config/sim` solo envía
  `Content-Type`; el `catch` tampoco distingue 401.
- `frontend/components/StoragePanel.tsx:94-113` — `PATCH /api/v1/storage/retention` no envía
  token y falla silenciosamente.
- `frontend/components/StrategyLabPanel.tsx:32-57` — `Aplicar` actualiza estado local y después
  ejecuta `PATCH /api/v1/params` sin token; el error es genérico.
- `frontend/components/OpportunityExplainDrawer.tsx:224-263` — preflight y test order usan POST sin
  token; sus botones están en `frontend/components/OpportunityExplainDrawer.tsx:369-406`.

Resultado en producción: botones activos que responden 401. La UI promete control a un visitante
que no puede ni debe ejercerlo; es el riesgo R2 identificado por el plan.

## Objetivo

Aplicar la opción A del plan dentro del timebox: el deploy público es un **visor read-only honesto**.

- No se emite ninguna petición a una ruta protegida desde una acción disponible en la UI pública.
- Todo control de estado se oculta o queda deshabilitado con una explicación textual.
- La superficie declara su naturaleza con el badge persistente `READ-ONLY DEMO`.
- Strategy Lab conserva el what-if de sesión y export conserva la evidencia descargable.
- El operador muta estado exclusivamente por CLI/SSH con token; el navegador público no recibe,
  almacena ni transmite el token.

El flag read-only es una barrera de UX y de honestidad, **no** el límite de seguridad. Si el frontend
se construye mal, la autenticación del backend sigue impidiendo mutaciones anónimas; aun así, una
imagen que muestre controles protegidos se considera NO-GO porque reintroduce el fallo visible.

## No objetivos

- No implementar la opción B (BFF de Next con allowlist + Basic Auth): post-entrega.
- No implementar OIDC, roles ni bitácora de mutaciones: post-entrega.
- No cambiar la autenticación ni las dependencias de rutas del backend.
- No añadir login, input de token ni almacenamiento de token en la UI.
- No convertir los cálculos what-if actuales en lógica ejecutada íntegramente en el navegador.

## Usuario

- Jurado que navega el visor público sin credenciales.
- Operador que preactiva la sesión jury y controla el sistema por SSH antes/durante la demo.
- Desarrollador local, que conserva la superficie completa al ejecutar Next sin el flag.

## Estado actual

Existe:

- Token obligatorio en prod (`backend/app/config.py:245-255`) y validación del header en las rutas
  protegidas (`backend/app/api/v1/router.py:86-97`).
- `ControlPanel`, `ConfigPanel`, `StoragePanel`, Strategy Lab, preflight y test order renderizando
  controles protegidos incondicionalmente.
- Export de sesión mediante `GET /api/v1/session/export`
  (`frontend/components/ControlPanel.tsx:60-83`); el backend construye el payload con lista blanca
  (`backend/app/api/v1/router.py:1128-1183`).
- Strategy Lab llama `onApply(draft)` antes de persistir (`frontend/components/StrategyLabPanel.tsx:32-49`).
  El padre guarda esos parámetros en estado (`frontend/app/page.tsx:206-212` y
  `frontend/app/page.tsx:440`) y `useStream`
  relanza projection/capacity/forward/survival por GET
  (`frontend/hooks/useStream.ts:426-440`, `frontend/hooks/useStream.ts:498-510` y
  `frontend/hooks/useStream.ts:694-710`).
- El what-if de una oportunidad usa POST por requerir un payload, pero es cálculo sin persistencia:
  `frontend/components/OpportunityExplainDrawer.tsx:169-194` y
  `backend/app/api/v1/router.py:652-662`.
- `deploy/standalone/Dockerfile.frontend:12-14` compila sin flag read-only y el servicio frontend
  de `deploy/standalone/docker-compose.yml:27-41` no declara `build.args`.

Brecha:

- No existe `READ_ONLY` ni `NEXT_PUBLIC_READ_ONLY`.
- La omisión del flag produce hoy una superficie completa; no hay default seguro para el build
  standalone público ni un gate que detecte una imagen incorrecta.
- No existe un inventario verificable que cruce rutas protegidas con sus disparadores de UI.
- Los errores de ControlPanel, ConfigPanel y Strategy Lab no distinguen 401 de fallo de red.
- No hay badge de superficie en el header (`frontend/app/page.tsx:230-280`).

## Requisitos funcionales

### RF-001 Flag build-time `NEXT_PUBLIC_READ_ONLY`

`NEXT_PUBLIC_READ_ONLY=1` es **build-time, no runtime**: Next sustituye la variable al ejecutar
`npm run build`. La ruta oficial de deploy debe ser segura ante una omisión accidental:

- En `deploy/standalone/Dockerfile.frontend`, declarar `ARG NEXT_PUBLIC_READ_ONLY=1` y después
  `ENV NEXT_PUBLIC_READ_ONLY=$NEXT_PUBLIC_READ_ONLY`, ambos antes de `RUN npm run build`.
- Validar antes del build que el argumento sea exactamente `0` o `1`; un valor vacío, `true` o un
  typo hace fallar la imagen.
- En `deploy/standalone/docker-compose.yml`, pasar además
  `build.args.NEXT_PUBLIC_READ_ONLY: "1"`. El default `1` del Dockerfile y el valor explícito del
  compose son redundancia deliberada: si compose omite el argumento, el build standalone sigue
  siendo read-only.
- La ejecución local con `npm run dev` o `npm run build`, fuera de ese Dockerfile, conserva el
  default aplicativo `false` cuando la variable no existe. **Nota para el implementador**: no
  añadir `NEXT_PUBLIC_READ_ONLY` a `frontend/.env.local`, a `frontend/.env.local.example` ni a los
  scripts de `package.json`; el stack local de desarrollo debe seguir mostrando la superficie
  completa por omisión. Para probar la rama read-only en local se pasa la variable de forma
  explícita y puntual: `NEXT_PUBLIC_READ_ONLY=1 npm run dev`.
- Poner el flag solo en `environment:` del compose queda prohibido como mecanismo de activación:
  no modifica un bundle ya compilado.
- Una imagen construida fuera de la ruta oficial y sin flag puede mostrar la superficie completa.
  El backend seguirá rechazando mutaciones, pero el gate de RF-010 debe impedir su despliegue.

### RF-002 Constante central `READ_ONLY`

Añadir una única constante exportada junto a `API_BASE` en `frontend/lib/config.ts`:

```ts
export const READ_ONLY = process.env.NEXT_PUBLIC_READ_ONLY === '1';
```

Todos los componentes de la matriz RF-009 consumen esta constante. No se permiten comprobaciones
ad hoc de `process.env` por componente ni un segundo flag con semántica equivalente.

**Mecanismo de exposición al árbol de componentes**: import directo del módulo
(`import { READ_ONLY } from '../lib/config'`), el mismo patrón que ya usan todos los componentes
afectados para `API_BASE` (p. ej. `frontend/components/ControlPanel.tsx:7` y
`frontend/components/StrategyLabPanel.tsx:7`). No se introduce React Context, provider ni prop
drilling: `NEXT_PUBLIC_*` se sustituye por literal en build-time, así que la constante de módulo es
estable, funciona en cualquier client component y no provoca re-renders. `frontend/app/page.tsx`
la importa igual para el badge de RF-006.

### RF-003 Controles protegidos deshabilitados u ocultos

En `READ_ONLY`, tratar toda la interacción, no solo el botón final:

- `ControlPanel`: kill switch, resume, selector de modo y botones de escenario.
- `ConfigPanel`: switches y campos numéricos, además de `Guardar configuración base`.
- `StoragePanel`: selector de retención y `Aplicar y podar ahora`.
- `OpportunityExplainDrawer`: `Preflight` y `Test order`.

Los estados actuales siguen visibles como información. Cuando se conserve un control para explicar
una capacidad, debe estar deshabilitado y asociado al texto literal `Demo pública read-only`; para
que el tooltip funcione sobre elementos HTML deshabilitados, se usa un wrapper que sí reciba eventos.
Ocultar también cumple si la capacidad ya está explicada en otro elemento visible.

No basta con deshabilitar el botón final y dejar inputs editables: una superficie que permite editar
sin poder guardar sigue siendo engañosa. Tampoco basta con confiar en que el backend devuelva 401.

### RF-004 Strategy Lab se conserva como what-if no persistente

Strategy Lab demuestra C1 y **no se retira**. En `READ_ONLY`:

- `Aplicar` siempre ejecuta `onApply(draft)` y retorna antes de `PATCH /api/v1/params`.
- El cambio de estado en `frontend/app/page.tsx:206-212` y `frontend/app/page.tsx:440` dispara los
  GET existentes de projection/capacity/forward/survival mediante `useStream`; no se añade otro
  flujo de red.
- El POST `/opportunities/{id}/what-if` puede permanecer: el backend documenta que no registra
  oportunidades, no ejecuta órdenes y no altera el embudo (`backend/app/api/v1/router.py:652-662`).
- La etiqueta pasa a `WHAT-IF LOCAL · NO PERSISTE` (badge actual en
  `frontend/components/StrategyLabPanel.tsx:72-78`). Aquí “local” significa que los parámetros
  viven en el estado de esta sesión del navegador; los cálculos siguen realizándose en endpoints
  read-only del backend.
- `Reset` conserva el comportamiento local actual
  (`frontend/components/StrategyLabPanel.tsx:59-70`) y nunca llama a `POST /params/reset`.
- El mensaje de éxito en esta rama no puede decir `Parámetros aplicados` sin matiz; debe indicar
  `What-if actualizado; no persiste` o equivalente.

Cambios concretos en el componente — solo hay una función de red que tocar:

- `apply()` (`frontend/components/StrategyLabPanel.tsx:32-57`): en `READ_ONLY`, tras
  `onApply(draft)` (línea 35) muestra la notificación no persistente y retorna antes del `fetch`
  de la línea 37. La rama completa conserva el `PATCH` y añade la distinción 401 de RF-007.
- `reset()` (`frontend/components/StrategyLabPanel.tsx:59-70`) ya es 100 % local (setDraft +
  onApply, sin red): **no requiere cambios**.
- El badge de la línea 77 cambia su texto a `WHAT-IF LOCAL · NO PERSISTE` cuando `READ_ONLY`.
- Los `NumberInput` del draft permanecen editables en read-only: alimentan el what-if de sesión,
  que es exactamente la capacidad que se conserva.

### RF-005 Export de sesión permanece activo

`Export session` (`frontend/components/ControlPanel.tsx:60-83`) permanece habilitado en read-only:
usa GET y el backend exporta una lista blanca (`backend/app/api/v1/router.py:1128-1183`). Un fallo de
export no debe bloquear ni rehabilitar controles protegidos.

### RF-006 Badge `READ-ONLY DEMO` en el header

Mostrar un badge textual con el literal `READ-ONLY DEMO` en el header del dashboard
(`frontend/app/page.tsx:230-280`) cuando `READ_ONLY` sea verdadero. Debe:

- permanecer visible al cambiar de tab;
- tener una variante visible en viewport móvil, sin reglas `hiddenFrom` que eliminen ambas;
- exponer el texto literal en el DOM y no comunicar el estado solo por color;
- no confundirse ni reemplazarse con los badges dinámicos `DEMO DATA`, `HALTED` o conectividad.

### RF-007 Errores distinguen 401 de fallo de red

En la superficie completa, preservar el status antes de entrar al manejo de error en:

- `frontend/components/ControlPanel.tsx:44-58`;
- `frontend/components/ConfigPanel.tsx:73-109`;
- `frontend/components/StrategyLabPanel.tsx:32-57`.

Una respuesta 401 muestra `Requiere token de control` o equivalente. Un status no-401 muestra el
error específico de la acción y una excepción de `fetch` muestra error de conexión. La rama
read-only no usa este manejo como control de acceso: no debe emitir la petición protegida.

### RF-008 Sesión jury preactivada por CLI

Antes de presentar, el operador activa jury por SSH desde el propio servidor, contra loopback:

```bash
curl --fail-with-body -X POST 'http://127.0.0.1:8090/api/v1/demo?mode=jury' \
  -H "X-Control-Token: $ARB_CONTROL_TOKEN"
```

El token no viaja por el HTTP público sin TLS. El visor muestra el modo y escenario resultantes por
SSE/polling sin exponer controles. El procedimiento debe incluir verificación HTTP 200 y consulta
posterior de `GET /api/v1/demo`; un curl fallido detiene la preparación de la demo.

### RF-009 Inventario auditable de superficie mutable

La auditoría cruza **rutas de control protegidas** con disparadores del frontend. El estado actual es:

| Acción protegida expuesta hoy | Evidencia backend | Disparador frontend | Conducta read-only |
|---|---|---|---|
| `PATCH /params` | `backend/app/api/v1/router.py:417-434` | `frontend/components/StrategyLabPanel.tsx:32-57` | no se llama; apply local |
| `PUT /config/sim` | `backend/app/api/v1/router.py:519-551` | `frontend/components/ConfigPanel.tsx:73-109` | edición y guardado bloqueados |
| `PATCH /storage/retention` | `backend/app/api/v1/router.py:599-617` | `frontend/components/StoragePanel.tsx:94-113` y `frontend/components/StoragePanel.tsx:177-222` | selector y apply bloqueados |
| `POST /execution/preflight` | `backend/app/api/v1/router.py:909-938` | `frontend/components/OpportunityExplainDrawer.tsx:224-249` y `frontend/components/OpportunityExplainDrawer.tsx:369-395` | bloqueado/oculto |
| `POST /execution/test-order` | `backend/app/api/v1/router.py:941-971` | `frontend/components/OpportunityExplainDrawer.tsx:224-263` y `frontend/components/OpportunityExplainDrawer.tsx:396-406` | bloqueado/oculto |
| `POST /control/kill-switch` | `backend/app/api/v1/router.py:974-986` | `frontend/components/ControlPanel.tsx:44-58` y `frontend/components/ControlPanel.tsx:99-111` | bloqueado/oculto |
| `POST /control/resume` | `backend/app/api/v1/router.py:989-1004` | `frontend/components/ControlPanel.tsx:44-58` y `frontend/components/ControlPanel.tsx:112-124` | bloqueado/oculto |
| `POST /demo` | `backend/app/api/v1/router.py:1071-1087` | `frontend/components/ControlPanel.tsx:126-143` | selector bloqueado |
| `POST /demo/scenario/{name}` | `backend/app/api/v1/router.py:1112-1125` | `frontend/components/ControlPanel.tsx:153-180` | botones bloqueados/ocultos |

También existen rutas protegidas sin disparador actual en la UI: `POST /params/reset`
(`backend/app/api/v1/router.py:437-444`) y `POST /backtest`
(`backend/app/api/v1/router.py:1018-1035`). Las dos deben permanecer sin disparador público. Los
alias singular/plural de escenario en `backend/app/api/v1/router.py:1112-1113` cuentan como dos
paths hacia una misma acción.

En cada entrega se repite el inventario de todos los `fetch` no-GET del frontend y todos los
decoradores `POST|PUT|PATCH|DELETE` del router. Cada diferencia frente a la tabla se clasifica antes
del deploy como: protegida y bloqueada, o cálculo read-only explícito. El POST what-if es la única
excepción actual y está justificado en RF-004. Un método HTTP por sí solo no determina mutabilidad;
la clasificación se basa en efectos observables del handler.

Comandos base de la auditoría (además de revisar los call sites de helpers genéricos):

```bash
rg -n "method:\\s*['\"](POST|PUT|PATCH|DELETE)['\"]|fetch\\(" frontend --glob '!node_modules'
rg -n '@router\.(post|put|patch|delete)' backend/app/api/v1/router.py
```

Resultado de la auditoría 2026-07-11 (verificado sobre el código actual):

- Los únicos emisores `fetch` no-GET del frontend son los 5 de la tabla (cubren sus 9 acciones)
  más el what-if de RF-004; **no hay mutaciones fuera de la matriz**.
- Dos helpers concentran llamadas y deben revisarse por call site, no por firma:
  `post()` en `frontend/components/ControlPanel.tsx:45-58` es el único emisor de las 4 rutas de
  control (`control/kill-switch`, `control/resume`, `demo?mode=`, `demo/scenario/{name}`), y
  `fetchJson()` en `frontend/hooks/useStream.ts:419-424` acepta `RequestInit` pero todos sus call
  sites (líneas 493-678) lo usan solo con GET y `AbortSignal`. Si un cambio futuro pasa `method`
  a `fetchJson`, entra en el inventario.

### RF-010 Gate de build público y documentación

El deploy solo puede continuar si se construye una imagen frontend nueva por la ruta standalone y:

- `docker compose config` resuelve `build.args.NEXT_PUBLIC_READ_ONLY` a `"1"`;
- el build rechaza cualquier valor distinto de `0|1`;
- el artefacto `.next` contiene el literal `READ-ONLY DEMO`;
- el HTML/DOM servido por el contenedor muestra `READ-ONLY DEMO` en desktop y móvil;
- una inspección del bundle contra el valor real de `ARB_CONTROL_TOKEN` no encuentra coincidencias;
- el smoke de RF-009 no registra ninguna llamada a sus rutas protegidas.

Comandos literales del gate (se ejecutan en el servidor, desde `deploy/standalone/`, tras
`docker compose build --no-cache frontend`; la imagen se inspecciona con `docker run`, sin
necesidad de contenedor en marcha):

```bash
# 1) compose resuelve el arg a "1"
if docker compose config | grep -Eq '^[[:space:]]+NEXT_PUBLIC_READ_ONLY: "?1"?$'; then
  echo GO-arg
else
  echo NO-GO-arg >&2
  exit 1
fi

# 2) el artefacto .next contiene el literal del badge
if docker run --rm --entrypoint sh arbitraje-btc-frontend -c \
  "grep -rqF 'READ-ONLY DEMO' /app/.next"; then
  echo GO-badge
else
  echo NO-GO-badge >&2
  exit 1
fi

# 3) el token real NO está en el bundle (grep=1 significa ausente; grep>1 también es NO-GO)
test -n "$ARB_CONTROL_TOKEN" || { echo "define ARB_CONTROL_TOKEN antes del gate"; exit 1; }
export ARB_CONTROL_TOKEN
if docker run --rm --entrypoint sh -e ARB_CONTROL_TOKEN arbitraje-btc-frontend -c '
  grep -rqF -- "$ARB_CONTROL_TOKEN" /app/.next
  rc=$?
  [ "$rc" -eq 1 ]
'; then
  echo GO-token
else
  echo NO-GO-token >&2
  exit 1
fi

# 4) el DOM servido por el stack muestra el badge (>= 1)
html="$(curl --fail-with-body --silent --show-error http://127.0.0.1:8090/)" || exit 1
if printf '%s' "$html" | grep -qF 'READ-ONLY DEMO'; then
  echo GO-dom
else
  echo NO-GO-dom >&2
  exit 1
fi
```

El paso 4 funciona porque Next prerenderiza el client component del header: con `READ_ONLY`
constante en build-time, el literal aparece ya en el HTML inicial, no solo tras hidratar. La
verificación móvil (375 px) y el Network de RF-009 siguen siendo smoke manual con DevTools.

La opción A y el comando de RF-008 quedan escritos en el README de deploy y/o guion de entrega. Si
el badge falta, aparecen controles protegidos o el flag solo está en runtime, la imagen es NO-GO;
reiniciar el contenedor no lo corrige: hay que reconstruirla.

## Prohibiciones explícitas (del plan, no negociables)

- **Token en `localStorage`, estado React o bundle**: ningún secreto en variables `NEXT_PUBLIC_*`,
  props, código cliente o argumentos de build.
- **nginx inyectando `X-Control-Token`** hacia el backend en un sitio público sin autenticación
  propia: convertiría a cada visitante anónimo en operador.
- **Correr producción como dev** (`ARB_ENV != prod` para esquivar el validator de token).
- **Usar 401 como mecanismo de UX read-only**: la petición protegida no debe salir del navegador.
- **BFF/OIDC hoy**: no forma parte de este PRD ni de su gate.

## Cambios técnicos

### Frontend

- `frontend/lib/config.ts` — constante única `READ_ONLY`.
- `frontend/components/ControlPanel.tsx` — bloquear mutaciones, conservar estado y export, distinguir
  401 en la rama completa.
- `frontend/components/ConfigPanel.tsx` — inputs y guardado en lectura; distinguir 401.
- `frontend/components/StoragePanel.tsx` — conservar métricas y bloquear retención/poda.
- `frontend/components/StrategyLabPanel.tsx` — rama read-only que retorna tras `onApply`, etiqueta
  honesta y reset local; distinguir 401 en la rama completa.
- `frontend/components/OpportunityExplainDrawer.tsx` — bloquear preflight/test order y conservar
  explain + what-if.
- `frontend/app/page.tsx` — badge persistente `READ-ONLY DEMO`.

### Deploy

- `deploy/standalone/Dockerfile.frontend` — `ARG` con default seguro, validación `0|1`, `ENV` antes
  del build y comprobación del marcador en el artefacto.
- `deploy/standalone/docker-compose.yml` — `build.args.NEXT_PUBLIC_READ_ONLY: "1"` en frontend.

## Plan de implementación

1. Añadir `READ_ONLY` central y la redundancia de build (`ARG=1`, validación y `build.args=1`).
2. Adaptar `ControlPanel`, `ConfigPanel`, `StoragePanel` y `OpportunityExplainDrawer` según RF-003.
3. Crear la rama read-only de Strategy Lab sin duplicar los GET existentes.
4. Añadir el badge de header con variante móvil.
5. Diferenciar 401, otros status y fallo de red en las tres superficies de RF-007.
6. Repetir y registrar el inventario RF-009; clasificar cualquier nuevo fetch no-GET.
7. Construir sin cache y ejecutar el gate de artefacto, DOM y Network de RF-010.
8. Documentar la opción A y preactivar jury por CLI.

## Pruebas

- Build local sin variable: `READ_ONLY=false`; typecheck, lint y build limpios.
- Build standalone sin pasar argumento: resulta read-only por default del Dockerfile.
- Build standalone con `NEXT_PUBLIC_READ_ONLY=2` o vacío: falla antes de `npm run build`.
- Build standalone/compose con valor `1`: el artefacto y el DOM contienen `READ-ONLY DEMO`.
- Smoke público desktop y viewport móvil: recorrer todas las tabs, abrir una oportunidad y accionar
  todo elemento habilitado; Network registra **0** requests a las rutas de la tabla RF-009.
- Strategy Lab: `Aplicar` provoca nuevos GET de projection/capacity/forward/survival con los
  overrides que cada endpoint admite, muestra el mensaje no persistente y Network registra **0**
  `PATCH /api/v1/params`; Reset tampoco llama a `/params/reset`.
- What-if de oportunidad: puede emitir `POST /opportunities/{id}/what-if`, devuelve 2xx y no cambia
  revisión de runtime, embudo, ejecuciones ni persistencia.
- Configuración y storage: los valores son legibles, pero todos los inputs de edición y acciones
  protegidas están deshabilitados u ocultos con explicación.
- Export: `GET /api/v1/session/export` devuelve 200, descarga JSON válido y no contiene
  `control_token`, `ARB_CONTROL_TOKEN`, `db_url` ni el valor real del token.
- Superficie completa local con flag apagado y backend dev: comportamiento actual operativo; un 401
  provocado muestra token requerido y un fallo de red muestra conexión, no 401.
- CLI jury: con token devuelve 200; sin header devuelve 401; `GET /api/v1/demo` refleja `mode=jury`.

## Criterios de aceptación (gate del Bloque 2 — auth)

- [ ] El Dockerfile standalone usa default read-only `1`, valida `0|1` y compose pasa `"1"`.
- [ ] El artefacto y el DOM público contienen `READ-ONLY DEMO`; el badge se ve en todas las tabs y
  en un viewport de 375 px.
- [ ] El valor real de `ARB_CONTROL_TOKEN` no aparece en bundle, HTML, almacenamiento del navegador,
  requests del frontend ni historial/args de la imagen frontend.
- [ ] La auditoría RF-009 está actualizada: toda ruta protegida tiene su disparador bloqueado o no
  tiene disparador, y toda nueva llamada no-GET está clasificada.
- [ ] El smoke público completo produce 0 requests a rutas protegidas y, por tanto, 0 respuestas 401.
- [ ] ConfigPanel y StoragePanel son legibles pero no editables; ControlPanel conserva los estados
  y export; preflight/test order no son accionables.
- [ ] Strategy Lab actualiza el what-if de sesión sin `PATCH /params` ni `/params/reset`, y se
  etiqueta `WHAT-IF LOCAL · NO PERSISTE`.
- [ ] Los tres manejadores RF-007 distinguen 401, otro status y fallo de red.
- [ ] La sesión jury se preactiva por SSH contra `127.0.0.1`, responde 200 y el visor refleja jury.
- [ ] La opción A y su procedimiento operativo están documentados; no se añadió BFF, OIDC ni token UI.

## Riesgos

- Flag ausente en compose → mitigado por default `1` del Dockerfile standalone y gate del badge.
- Imagen construida fuera del Dockerfile o cache obsoleta → backend conserva la seguridad, pero el
  deploy es NO-GO; mitigación: build nuevo sin cache y smoke del contenedor servido.
- Flag puesto solo en runtime → no cambia el bundle; mitigación: inspección de `compose config`,
  artefacto y DOM, no solo variables del contenedor.
- Superficie nueva olvidada → mitigación: matriz RF-009 + inventario repetible de rutas y fetches.
- Tooltip inaccesible en controles disabled → mitigación: wrapper interactivo y texto visible/ARIA.
- Llamar “local” a cómputo backend → mitigación: RF-004 define que local es el estado de sesión y
  que GET/what-if siguen calculándose en backend sin persistir.
- Ocultar Strategy Lab por precaución → incumple C1; mitigación: RF-004 lo mantiene explícitamente.
- Inyectar el token vía nginx para eliminar 401 → prohibición explícita; el operador usa CLI/SSH.
