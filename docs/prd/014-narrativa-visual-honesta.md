# PRD-014: Narrativa visual honesta (origen, muestra, caso canónico y veredicto)

Estado: Propuesto  
Prioridad: P0 (cierre 12-jul, Bloque 6)  
Área: Frontend  
Dependencias: PRD-001 (drawer de explicación), Projection Suite v2 (frontier/forward)  
Plan: [docs/plan-accion-final-12jul.md](../plan-accion-final-12jul.md) §5 Bloque 6, riesgos R9-R10  
Timebox: 45 min. Regla de corte (§6.4 del plan): si no cabe todo, solo cambios 1-2 más el veredicto literal.

## Problema

El dashboard ya es honesto en estructura (badges `LIVE/DEMO/REPLAY/STALE`, capital marcado como
simulado, dry-run con nombre real), pero quedan cuatro puntos donde una cifra puede leerse como
algo que no es:

1. El `$109.75/BTC` del Edge Waterfall es un fixture determinista de `GET /api/v1/validation`,
   pero visualmente compite con las cifras de mercado y puede confundirse con un edge live (R10).
2. La `Tesis de negocio` presenta retail/institucional sin declarar `frontier.mode` ni la ruta;
   si el frontier cayó honestamente a `demo`, la tarjeta lo presenta igual que si fuera live (R9).
   Además, su texto de ayuda afirma genéricamente “medimos capturabilidad con datos vivos”.
3. El bloque `P(P&L>0)` de la tesis muestra un porcentaje sin la muestra que lo sostiene
   (`n_trades` empíricos y `n_paths` simulados) ni el proceso que la origina (recording/replay).
4. El motor ya decide operable/rechazada con bruto, neto y coste dominante, pero ningún panel lo
   dice con el veredicto literal que el jurado necesita leer: `OPERAR` / `NO OPERAR`.

La credibilidad ante el comité depende de que ninguna cifra afirme más de lo que el sistema midió.

## Objetivo

Que en el primer recorrido del dashboard cada cifra comercial declare, según corresponda, su
origen (`mode`/ruta o recording/replay), su muestra (`n_trades`/`n_paths`) y su naturaleza
(canónico vs live vs demo), y que la decisión del motor se lea como veredicto literal. Honestidad
antes que estética; texto antes que color.

## No objetivos

- No rediseñar `Tesis de negocio`, móvil, accesibilidad ni tabs: ya están cerrados y solo
  requieren smoke (PRD-015).
- No añadir charts, métricas, animaciones ni interacciones nuevas.
- No cambiar fórmulas económicas ni recalcular decisiones en frontend.
- No ampliar contratos API. En particular, no añadir `mode`/`source` a `ForwardProjection`:
  recording/replay es una propiedad fija del endpoint actual, no un campo de su respuesta.
- No convertir `asof_monotonic` en timestamp humano.

## Usuario

- Jurado que decide en 90 segundos si el sistema es creíble.
- Evaluador escéptico que pregunta “¿estas cifras son live?” (pregunta trampa 8 del plan).

## Estado actual (verificado en código)

| Superficie | Ya existe | Brecha |
|---|---|---|
| `EdgeWaterfall.tsx:72-95` | `SectionHeader.right` muestra `reconciliation.computed` por BTC dentro de un tooltip; el docstring declara que `/validation` es determinista (`EdgeWaterfall.tsx:8-14`) | La naturaleza canónica no está visible: solo el tooltip compara computado, objetivo y delta |
| `BusinessThesisCard.tsx:122-123,129-194` | Retail/institucional derivan de `frontier`; `goFrontier`/`goForward` abren sus paneles fuente | Los bloques no muestran `frontier.mode`/`frontier.route`; el help afirma “datos vivos” (`BusinessThesisCard.tsx:105-111`); el forward omite `n_trades`/`n_paths` |
| `BusinessThesisCard.tsx:205-209` | MXN ya se declara “expansión” sin cifra ni medición en vivo | — (texto a preservar) |
| `ForwardFanChart.tsx:53-67` | Badge `{n_paths} paths · {n_trades} trades` (`ForwardFanChart.tsx:61-63`); disclaimer “No es un pronóstico” (`ForwardFanChart.tsx:179-183`) | El proceso de origen no se ve como `RECORDING → REPLAY` |
| `BreakEvenFrontier.tsx:71-85` | Patrón de cabecera `live buy→sell` / `demo`; los badges están en `SectionHeader.right` (`BreakEvenFrontier.tsx:76-83`) | — (referencia visual; no se modifica) |
| `OpportunityExplainDrawer.tsx:305-321,350-367` | Bruto/neto/delta y, en Decisión, operable/rechazada, razón y coste dominante | Falta el veredicto dominante `OPERAR`/`NO OPERAR` |
| `useStream.ts:209-211` | `EdgeFrontier` expone `mode: string`, `route: {buy, sell, symbol} | null` y `asof_monotonic`; `ForwardProjection` expone muestra (`n_trades`/`n_paths`, `useStream.ts:262-263`), pero no origen (`useStream.ts:260-281`) | El origen del forward debe declararse por la semántica fija del endpoint, no inventando un campo |
| `page.tsx:323-329` | Equity dice `capital simulado total` y se alimenta de `pnl.equity_usd` | Usa `accent="brand"`; puede parecer resultado positivo y dominar la captura |

## Requisitos funcionales

### RF-001 Badge `CASO CANÓNICO` junto a $109.75/BTC

En `EdgeWaterfall.tsx`, modificar únicamente `SectionHeader.right` (`EdgeWaterfall.tsx:78-94`). El
`$109.75` se renderiza como `{money(rec.computed)}/BTC` en el `Badge` de `EdgeWaterfall.tsx:85-92`,
envuelto por el `Tooltip` de reconciliación (`EdgeWaterfall.tsx:79-93`). Punto de inserción: el
`Group` nuevo sustituye al `Tooltip` como valor directo de `right` y contiene al `Tooltip`+`Badge`
existentes más el badge canónico.

- Envolver el badge numérico actual y un badge nuevo en un `Group` compacto con `wrap="wrap"`. El literal
  **`CASO CANÓNICO`** queda inmediatamente adyacente a `{money(rec.computed)}/BTC`, visible sin
  hover; no va dentro del área de barras ni solo dentro del tooltip.
- El badge numérico conserva su semántica de reconciliación (`passed`, icono y color). El badge
  nuevo usa estilo neutral y no cambia con el feed ni con `passed`.
- Ampliar el tooltip del grupo o del badge canónico con este significado inequívoco: “Fixture
  determinista del enunciado, reconciliado con la misma `cost_model`; no es edge live ni usa la
  configuración actual”.
- La cifra sigue alimentada por `report.reconciliation.computed`; la referencia del reto por
  `report.reconciliation.target`; el literal `CASO CANÓNICO` es metadato fijo de
  `GET /api/v1/validation`, cuyo contrato ya se documenta en `useStream.ts:181-196`
  (`ValidationReport.reconciliation`).
- En el estado de carga/error (`!report`, `EdgeWaterfall.tsx:37-49`) el header no tiene `right`:
  no se añade badge alguno hasta tener datos; `CASO CANÓNICO` nunca aparece sin la cifra.

Cubre la pregunta trampa 2 del plan (“¿Qué es el $109.75?”) antes de que la hagan.

### RF-002 Fuente visible en `Tesis de negocio`

En `BusinessThesisCard.tsx`:

- Extender `ThesisBlock` con un slot opcional de metadatos, renderizado **debajo de `label` y antes
  de `value`** (hoy esos nodos están en `BusinessThesisCard.tsx:66-74`). No cambiar la jerarquía,
  cifra, explicación ni CTA del bloque.
- En los bloques Retail e Institucional, el slot usa un `Group` compacto con `wrap="wrap"` y muestra
  un badge de modo alimentado por
  `frontier.mode` y, si `frontier.route !== null`, un badge adyacente de ruta alimentado por
  `frontier.route.buy` y `frontier.route.sell` con el literal `buy→sell`.
- Normalización textual: `frontier.mode === 'demo'` muestra **`DEMO`**; `mode === 'live'` muestra
  **`LIVE`**; cualquier otro valor se muestra en mayúsculas, sin traducirlo a live ni inventar una
  ruta. El color puede acompañar, nunca sustituir el literal.
- La ruta se omite cuando `frontier.route === null`; no se muestran guiones, venues inferidos ni
  datos del SSE. El badge debe replicar la densidad visual, no copiar lógica, del patrón verificado
  en `BreakEvenFrontier.tsx:76-83`.
- Reemplazar en el `help` la afirmación “medimos capturabilidad con datos vivos” por: “Cada número
  declara su modo y su panel fuente; las proyecciones pueden caer a demo. Medimos capturabilidad,
  no prometemos retorno”.
- Conservar `goFrontier` y `goForward` (`BusinessThesisCard.tsx:122-123`) sin cambiar tab ni anchors.

### RF-003 Muestra y origen del forward

En el bloque `P(P&L>0)` de `BusinessThesisCard.tsx` y la cabecera de `ForwardFanChart.tsx`:

- Cuando `forward.available === true`, mostrar junto al porcentaje una fila compacta de metadatos
  con tres literales: **`RECORDING → REPLAY`**, **`{forward.n_trades} trades empíricos`** y
  **`{forward.n_paths} trayectorias simuladas`**. En la tesis va en el slot de metadatos, debajo de
  `P(P&L>0) · forward` y antes del porcentaje.
- En `ForwardFanChart`, colocar `RECORDING → REPLAY` en `SectionHeader.right`, inmediatamente antes
  del badge existente de muestra (`Badge` en `ForwardFanChart.tsx:61-63`). Se permiten dos badges dentro de
  un `Group` con `wrap="wrap"` y alineación al final; no se crea una leyenda ni otro componente de
  chart.
- `n_trades` y `n_paths` se leen exclusivamente de `ForwardProjection.n_trades` y
  `ForwardProjection.n_paths` (`useStream.ts:260-264`). `prob_profit` sigue alimentando el
  porcentaje; `terminal_p50` sigue alimentando la mediana. No derivar conteos desde `bands.step`,
  histogramas ni texto libre.
- `RECORDING → REPLAY` **no** se alimenta de un campo de `ForwardProjection`: es un literal fijo por
  la implementación de `GET /api/v1/forward`, que toma ticks del `Recorder` y ejecuta backtest/replay
  (`backend/app/api/v1/router.py:1420-1469`). No usar `frontier.mode`, `demo.source` ni la palabra
  “live” para etiquetar esta muestra.
- Si `forward && !forward.available`, conservar `forward.notes`/el mensaje de muestra insuficiente
  actual (`ForwardFanChart.tsx:69-79` y `BusinessThesisCard.tsx:175-183`): mostrar el origen fijo,
  pero no mostrar porcentaje, `n_paths` ni conteos que aparenten una simulación disponible.
- Si `forward === null` por carga/error, no renderizar badges de origen o muestra; conservar
  `FetchFallback`.

### RF-004 Veredicto literal `OPERAR` / `NO OPERAR`

En `OpportunityExplainDrawer.tsx`, dentro del `Box` Decisión (`OpportunityExplainDrawer.tsx:350-367`):

- Insertar inmediatamente debajo del rótulo `Decisión` y antes del grupo de badges una línea
  dominante (`fw=700`, tamaño mínimo 20 px) con **`OPERAR`** si `data.engine.trades === true` y
  **`NO OPERAR`** en cualquier otro caso.
- `engine.trades` es la única fuente del veredicto: campo `trades: boolean` (no nullable) de
  `OpportunityExplanation.engine` (`useStream.ts:84-91`, campo en `useStream.ts:90`), el mismo que
  hoy alimenta el badge operable/rechazada (`OpportunityExplainDrawer.tsx:355-357`). No inferirlo
  desde el signo de `engine.net_usd`, `engine.status`, `naive.would_trade`, el color ni la
  presencia de `dominant_cost`.
- Conservar los badges actuales: operable/rechazada desde `engine.trades`, razón desde
  `engine.reason` y coste dominante desde `engine.dominant_cost`. Conservar también las métricas ya
  visibles `naive.gross_usd`, `engine.net_usd` y delta (`OpportunityExplainDrawer.tsx:201-204,305-321`).
  No duplicar esas métricas dentro de Decisión.
- El veredicto debe seguir siendo comprensible en escala de grises y para un lector de pantalla:
  el color es refuerzo, no portador de la decisión.

Cubre el tramo 28-43 s del guion (§9): “el motor explica OPERAR o NO OPERAR”.

## Reglas transversales (aplican a los cuatro cambios)

- **`asof_monotonic` no se renderiza ni se formatea como hora.** Es reloj monotónico del proceso,
  no epoch (`useStream.ts:208-212`). No pasarlo a `Date`, `Intl.DateTimeFormat` ni
  `toLocaleTimeString`; la frescura visible sigue viniendo del estado SSE/feeds existente.
- **Ningún estado depende solo del color.** Los nuevos estados llevan siempre literal visible:
  `CASO CANÓNICO`, `DEMO`/`LIVE`, `RECORDING → REPLAY` y `OPERAR`/`NO OPERAR`. Tooltips, iconos y
  colores solo añaden contexto; no sustituyen esos textos. Los badges nuevos usan variantes de
  Mantine con texto de alto contraste sobre su fondo (`variant="light"` o `"default"`, como los ya
  auditados en `BreakEvenFrontier.tsx:77-82`); prohibido `variant="filled"` con tonos claros o
  texto `dimmed` para el literal. El criterio verificable es el smoke en escala de grises (§Pruebas).
- **Equity es neutral.** En el KPI existente, conservar `value={usd(pnl?.equity_usd)}`, el rótulo
  `Equity` y `capital simulado total`, pero cambiar `accent="brand"` por `accent="neutral"`
  (`StatCard` en `page.tsx:323-330`; el accent está en `page.tsx:326`). No usar verde/rojo ni
  tratar capital estático simulado como rentabilidad.
- **MXN** conserva literalmente su condición de expansión sin medición en vivo y sin cifra
  (`BusinessThesisCard.tsx:205-209`).
- No se toca la fórmula económica, los contratos backend, los endpoints, la navegación ni el
  significado de los estados existentes.

## Cambios técnicos

Archivos frontend:

- `frontend/components/EdgeWaterfall.tsx` — badge y tooltip RF-001.
- `frontend/components/BusinessThesisCard.tsx` — slot de metadatos; RF-002 y RF-003; help.
- `frontend/components/ForwardFanChart.tsx` — badge de origen RF-003.
- `frontend/components/OpportunityExplainDrawer.tsx` — veredicto RF-004.
- `frontend/app/page.tsx` — únicamente `accent="brand"` → `accent="neutral"` en Equity.

Archivos de referencia, sin cambios:

- `frontend/components/BreakEvenFrontier.tsx` — patrón visual de modo/ruta.
- `frontend/hooks/useStream.ts` — contratos existentes.
- Backend — sin cambios; el origen recording/replay se documenta como invariancia ya implementada.

## Mapa contrato → etiqueta

| Etiqueta visible | Fuente exacta | Regla de presentación |
|---|---|---|
| `$…/BTC` canónico | `report.reconciliation.computed` | Mantener formateo actual; adyacente a `CASO CANÓNICO` |
| `CASO CANÓNICO` | Invariancia de `/api/v1/validation` | Literal fijo; nunca depende de feed, `mode` o `passed` |
| `LIVE` / `DEMO` | `frontier.mode` | Mayúsculas; siempre textual |
| `buy→sell` | `frontier.route.buy`, `frontier.route.sell` | Solo si `route !== null`; no inferir venues |
| `% P(P&L>0)` | `forward.prob_profit` | Solo si `available === true`; conservar formateo actual |
| `… trades empíricos` | `forward.n_trades` | Solo si `available === true` |
| `… trayectorias simuladas` | `forward.n_paths` | Solo si `available === true` |
| `RECORDING → REPLAY` | Invariancia de `/api/v1/forward` | Literal fijo, no campo dinámico; nunca “live” |
| `OPERAR` / `NO OPERAR` | `data.engine.trades` (`boolean`, `useStream.ts:90`) | `true` → `OPERAR`; `false` → `NO OPERAR` |
| Razón / coste dominante | `data.engine.reason`, `data.engine.dominant_cost` | Conservar badges y normalización actuales |
| Equity | `pnl.equity_usd` | `accent="neutral"`; conservar “capital simulado total” |

## Plan de implementación

1. Cambio 1: badge en waterfall (menor riesgo, aislado).
2. Cambio 2: slot y badges modo/ruta en la tesis + help sin “datos vivos”.
3. Cambio 4: veredicto en el drawer.
4. Cambio 3: muestra en tesis + origen en fan chart.
5. Guardrail Equity: cambiar solo el accent a neutral.
6. `npm run typecheck && npm run lint && npm run build`; smoke visual desktop y 360 px.

El orden por cambios obligatorios `1 → 2 → 4 → 3` respeta la regla de corte: al cerrar el paso 3,
las etiquetas de origen prioritarias y el veredicto ya están implementados.

## Pruebas

- `npm run typecheck`, `npm run lint`, `npm run build` limpios (gate de PRD-015).
- Render con frontier `mode=demo`, `route=null`: Retail e Institucional muestran `DEMO` y ninguna
  ruta. Render con `mode=live` y ruta: ambos muestran `LIVE` y exactamente `buy→sell`.
- Render con forward disponible: la tesis y el fan chart muestran los mismos `n_trades` y `n_paths`
  del payload, además de `RECORDING → REPLAY`; no aparece “live” junto a esa muestra.
- Render con `forward.available=false`: no aparecen porcentaje ni `n_paths`; permanece el mensaje
  de muestra insuficiente. Con `forward=null`: permanece `FetchFallback` sin metadatos ficticios.
- Drawer con `engine.trades=true/false`: el veredicto es respectivamente `OPERAR`/`NO OPERAR`, sin
  cambiar razón, coste dominante ni métricas.
- Smoke en escala de grises y a 360 px: todos los estados se distinguen por texto, los grupos de
  badges hacen wrap sin solaparse y los CTAs siguen abriendo `tour-frontier`/`tour-forward`.
- Búsqueda estática: ningún componente nuevo pasa `asof_monotonic` a APIs de fecha; Equity usa
  `accent="neutral"`; el texto MXN permanece sin cifra.

## Criterios de aceptación

Los cinco del plan (Bloque 6), expresados de forma verificable:

- En frontier demo, las dos cifras de tesis muestran `DEMO`; ninguna etiqueta dice `LIVE` ni
  muestra una ruta inventada.
- Con forward disponible, `P(P&L>0)` está acompañado por los valores exactos `n_trades` y `n_paths`
  del response y por `RECORDING → REPLAY`; con forward no disponible, no se muestra probabilidad.
- La nota MXN conserva “expansión”, “sin medición en vivo” y ausencia de cifra.
- Los dos CTAs de frontier abren `tour-frontier` y el CTA forward abre `tour-forward`, sin cambiar
  el número que los precede.
- En el primer recorrido son legibles tesis → `OPERAR`/`NO OPERAR` → riesgo aun sin color.

Contratos adicionales por cambio:

- El header de Edge Waterfall presenta simultáneamente la cifra computada y `CASO CANÓNICO`; el
  tooltip dice que no es live ni configuración actual.
- Retail e Institucional muestran el mismo `frontier.mode` y, cuando existe, la misma `route` del
  payload; `asof_monotonic` no aparece en UI.
- El drawer cumple la tabla de verdad `engine.trades=true → OPERAR`; `false → NO OPERAR` y conserva
  bruto, neto, razón y coste dominante sin recálculo.
- Equity usa estilo neutral y sigue identificada como capital simulado total.
- A 360 px no hay badges cortados o superpuestos, ni scroll horizontal nuevo en la tarjeta de tesis.

## Riesgos

- Sobrecargar la tesis con metadatos y perder legibilidad en proyector. Mitigación: un único slot
  compacto por bloque, cifra grande intacta y wrap verificado a 360 px.
- Confundir una invariancia de endpoint con un campo dinámico. Mitigación: `RECORDING → REPLAY` es
  literal fijo documentado; se prohíbe inventar `forward.mode` o reutilizar `frontier.mode`.
- Recalcular lógica en frontend para el veredicto. Mitigación: RF-004 define una tabla de verdad
  basada solo en `engine.trades` y conserva las métricas existentes.
- Consumir el timebox en estética. Mitigación: orden alineado con §6.4; charts, scatter, tablas de
  rutas y rediseños quedan explícitamente fuera.
