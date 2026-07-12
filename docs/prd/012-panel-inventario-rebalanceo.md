# PRD-012: Panel Inventario & Rebalanceo (C3)

Estado: Propuesto  
Prioridad: P0 (cierre 12-jul, Bloque 4)  
Área: Backend (fix puntual), Frontend  
Dependencias: ninguna (los contratos backend necesarios ya existen)  
Plan: [docs/plan-accion-final-12jul.md](../plan-accion-final-12jul.md) §5, Bloque 4

## Problema

El criterio C3 del comité pregunta literalmente “¿dónde está el BTC?”. El backend calcula balances por venue, equity marcada a mercado, skew de inventario y eventos de rebalanceo con coste debitado, pero **nada de eso es visible en la UI**: hoy la respuesta exige abrir DevTools contra `/pnl` o `/balances`. Además, la tarea periódica registra los rebalanceos con `ts=0.0`; cualquier fecha derivada de ese valor sería 1970 y, por tanto, evidencia falsa.

## Objetivo

Un panel `InventoryPanel` que responda en una sola vista:

- Cuánto BTC y quote hay en cada venue y cuánto vale su equity simulada.
- Cuál es el skew de inventario actual, su límite y si está en breach.
- Qué rebalanceos ocurrieron: cuándo (epoch real), qué skew corrigieron y cuánto costaron.
- Qué diferencia hay entre el coste amortizado usado para decidir una oportunidad y el coste acumulado realmente debitado al ledger.
- Qué queda fuera de alcance (reposición fiat) y por qué es una decisión de diseño explícita.

## No objetivos

- No mostrar `open_btc` / BTC comprometido: existe internamente, pero no está en `/pnl` ni `/balances`. Exponerlo y probarlo es stretch, no requisito del panel mínimo.
- No inventar origen/destino de rebalanceos: los eventos no los contienen; el algoritmo reparte BTC libre hacia una cuota común, no modela una transferencia venue→venue.
- No cambiar `Portfolio.rebalance()`, la fórmula de skew ni los contratos backend, salvo corregir el timestamp de la tarea periódica.
- No presentar ninguna cifra como saldo real: todo es capital simulado.

## Usuario

- Jurado que evalúa el criterio C3 (wallets y gestión de inventario).
- Operador que quiere verificar que el skew está bajo control sin consultar la API.

## Estado actual

Contratos backend verificados en código:

- `GET /pnl` (`backend/app/api/v1/router.py:866-879`) devuelve, con portfolio inicializado, el resultado de `Portfolio.pnl_summary()` (`backend/app/sim/inventory.py:493-517`):

  ```ts
  type PnlReady = {
    realized_pnl: number;
    unrealized_pnl: number;
    total_pnl: number;
    equity_usd: number;
    initial_quote_usd: number;
    equity_by_venue: Record<string, number>;
    skew: InventorySkew;
    equity_series: EquityPoint[];
    rebalance: RebalanceSummary; // recent contiene como máximo 10 eventos
  };
  ```

- La rama real de `/pnl` sin portfolio (`backend/app/api/v1/router.py:873-877`) conserva los cuatro importes base y `equity_series`, pero devuelve `skew: {}` y **omite** `initial_quote_usd`, `equity_by_venue` y `rebalance`. Los tipos y el render deben tolerar esas claves ausentes; no asumir que el contrato siempre es `PnlReady`.
- `GET /balances` (`backend/app/api/v1/router.py:843-863`) devuelve, con portfolio inicializado:

  ```ts
  type BalancesReady = {
    balances: BalanceItem[]; // dos por venue: BTC y su quote_ccy
    equity_by_venue: Record<string, number>;
    equity_usd: number;
    skew: InventorySkew;
    snapshot: {
      ts: number;
      balances: BalanceItem[];
      total_usd: number | null;
    };
  };
  ```

- La rama real de `/balances` sin portfolio (`backend/app/api/v1/router.py:849-853`) es exactamente `{ balances: [], equity_by_venue: {}, skew: {}, snapshot: null }`: **no incluye `equity_usd`**. `BalanceItem` es `{ exchange: string; asset: string; amount: number }` y el snapshot repite esa lista (`backend/app/models/account.py:7-16`).
- `InventorySkew` (`backend/app/sim/inventory.py:439-468`) es `{ btc_by_venue: Record<string, number>; total_btc: number; skew: number; limit: number; breached: boolean }`.
- Cada evento (`backend/app/sim/inventory.py:328-337`) contiene exactamente `{ ts, cost_usd, fee_btc, ref_mark, skew_before, skew_after }`. No contiene origen, destino ni `open_btc`.
- El rebalanceo distribuye únicamente BTC libre (`backend/app/sim/inventory.py:291-323`) y debita `cost_usd = fee_btc · ref_mark` al `realized_pnl` y al acumulado (`backend/app/sim/inventory.py:313-326`); no mueve quote.
- El coste amortizado de decisión **no existe** como `rebalance_usd` en `/pnl` ni `/balances`. El contrato ya disponible para una oportunidad lo expone como el componente `breakdown` con `key="rebalance"` de `GET /opportunities/{id}/explain` (`backend/app/api/v1/router.py:636-649`, `backend/app/engine/explain.py:83-100`); su `usd` es negativo porque es una resta del waterfall. Para mostrarlo como “coste”, la UI usa su magnitud y conserva la etiqueta “última oportunidad”.

Brechas:

- `Pnl` (`frontend/hooks/useStream.ts:172-179`) solo declara `skew` como `Record<string, unknown>`; faltan el contrato tipado de skew, `initial_quote_usd`, `equity_by_venue` y `rebalance`, incluida la rama sin portfolio.
- No existe tipo TS, estado ni fetch para `/balances`.
- **Bug:** `Rebalancer.run()` pasa `ts=0.0` a `Portfolio.rebalance()` (`backend/app/sim/rebalancer.py:46`); es la única llamada del repo con ese valor.

## Requisitos funcionales

### RF-001 Fix previo obligatorio: timestamp real del rebalanceo

`Rebalancer.run()` debe importar `time` y pasar `time.time()` (segundos epoch UTC) como `ts` al método puro `Portfolio.rebalance()`. **No usar `time.monotonic()`**: mide tiempo del proceso y no representa una fecha. Alcance verificado: `pf.rebalance(detector.books, ts=0.0)` en `backend/app/sim/rebalancer.py:46` es la **única** llamada del repo con `ts=0.0` (los tests inyectan epochs propios); no cambian las firmas de `run()` ni de `Portfolio.rebalance()`. El reloj se lee en la capa impura (`Rebalancer`, ya asíncrona y con I/O) y el epoch sigue entrando a `Portfolio.rebalance()` por parámetro, que permanece determinista y sin leer el reloj. El test parchea `time.time` en el módulo `app.sim.rebalancer` (monkeypatch), fuerza un único rebalanceo con el andamiaje del test periódico existente y verifica que el evento conserva exactamente el epoch inyectado.

### RF-002 Tipos TS fieles al contrato

En `frontend/hooks/useStream.ts` (o módulo de tipos equivalente), declarar:

```ts
export interface BalanceItem {
  exchange: string;
  asset: string;
  amount: number;
}

export interface InventorySkew {
  btc_by_venue: Record<string, number>;
  total_btc: number;
  skew: number;
  limit: number;
  breached: boolean;
}

export interface RebalanceEvent {
  ts: number;
  cost_usd: number;
  fee_btc: number;
  ref_mark: number;
  skew_before: number;
  skew_after: number;
}

export interface RebalanceSummary {
  count: number;
  cost_total_usd: number;
  recent: RebalanceEvent[];
}

export interface InventorySnapshot {
  ts: number;
  balances: BalanceItem[];
  total_usd: number | null;
}

export interface BalancesResponse {
  balances: BalanceItem[];
  equity_by_venue: Record<string, number>;
  equity_usd?: number;                 // ausente sin portfolio
  skew: InventorySkew | Record<string, never>;
  snapshot: InventorySnapshot | null;
}
```

Ampliar `Pnl` con `initial_quote_usd?`, `equity_by_venue?`, `rebalance?` y `skew: InventorySkew | Record<string, never>`; las tres propiedades opcionales reflejan la rama sin portfolio, no una preferencia de diseño. Antes de renderizar, usar guards de forma y `Number.isFinite`; TypeScript no valida JSON en runtime.

### RF-003 Flujo de datos y refresco acotado

El dueño del I/O será `useStream`, no el componente visual:

- Reutilizar el `pullLight` existente de 5 s (`frontend/hooks/useStream.ts:669-683`) para pedir `/balances` inmediatamente al montar y luego cada 5 s. No crear un segundo intervalo. Es el mismo precedente de `naive-vs-edge` y `wins` (`useStream.ts:675-680`): el fetch vive en el hook y el panel recibe props; se acepta que `/balances` se pida aunque la pestaña Operación no esté visible, igual que esos dos.
- Mantener como máximo un request de `/balances` en vuelo; si el tick siguiente llega antes de terminar, se omite. Compartir el `AbortController`, abortar al desmontar y limpiar el intervalo.
- Guardar `balances`, `balancesLoading`, `balancesError` y `balancesUpdatedAt` (hora cliente del último éxito), además de `retryBalances()`. Un fallo conserva el último snapshot exitoso y lo marca como desactualizado; un éxito posterior limpia el error.
- `/pnl` mantiene su doble vía actual: push SSE tras ejecuciones (`frontend/hooks/useStream.ts:620-625`) y pull de respaldo cada 5 s. Es la fuente de `rebalance`; `/balances` es la fuente primaria de saldos/equity/skew.
- Para el coste amortizado, tomar como máximo una vez por ciclo ligero el ID de la oportunidad más reciente y consultar su explicación existente. Buscar el componente `breakdown` con `key === 'rebalance'`; solo si `usd` es `number` finito aplicar `Math.abs(usd)`. Su tipo real es `number | null` (`frontend/hooks/useStream.ts:62-67`), y 404, 409, explicación parcial o componente ausente producen “—”, nunca `0`. No reconsultar el mismo ID.
- No sincronizar artificialmente respuestas: mostrar `balancesUpdatedAt` y etiquetar el coste de decisión con el ID de su oportunidad. `t_recv`/`t_detect` son relojes monotónicos, no epochs aptos para una fecha UI (`backend/app/models/opportunity.py:29-30`). Nunca sumar el coste de decisión al acumulado debitado.

### RF-004 Componente `InventoryPanel.tsx`

Crear `frontend/components/InventoryPanel.tsx` como componente de presentación (patrón `NaiveVsEdgePanel`: props tipadas, sin fetch) y montarlo en la pestaña **Operación** como **primer hijo directo** del `<Stack gap="lg">` de `<Tabs.Panel value="operacion">` (`frontend/app/page.tsx:429-431`), a ancho completo y por encima de `<ControlPanel />` — es la respuesta a “¿dónde está el BTC?” y debe verse antes que controles y configuración. Ojo: el `Tabs` usa `keepMounted={false}` (`page.tsx:334`), así que el panel se desmonta al cambiar de pestaña; por eso el estado y el intervalo viven en `useStream` (montado siempre en la página), no en el componente.

```ts
export interface DecisionRebalanceCost {
  opportunityId: string;
  usd: number;
}

export interface InventoryPanelProps {
  balances: BalancesResponse | null;
  pnl: Pnl | null;
  decisionCost: DecisionRebalanceCost | null;
  loading: boolean;
  error: boolean;
  updatedAt: number | null;
  onRetry: () => void;
}
```

El componente no hace fetch ni guarda una segunda copia de las respuestas. Sus reglas de combinación son:

1. `/balances` manda para `balances`, `equity_by_venue`, `equity_usd` y `skew` cuando la forma está completa.
2. `pnl.equity_by_venue` y `pnl.skew` son respaldo independiente si falta esa sección de `/balances`; `pnl.rebalance` es siempre la fuente de eventos y coste debitado.
3. Las filas son la unión ordenada de exchanges presentes en `balances`, `equity_by_venue` y `skew.btc_by_venue`. Para cada exchange, `asset === "BTC"` alimenta BTC y el activo no BTC alimenta Quote. Una pareja ausente o un número no finito se muestra como “—”; no se convierte a cero.
4. `snapshot.balances` no se suma a `balances` porque es una copia; `snapshot.ts` puede ser 0 si aún no hay libros y no se usa como indicador de frescura HTTP.

Contenido visual:

1. **Barras comparables por venue**: BTC, Quote y Equity simulada, una fila por venue recibido. Cada columna escala por separado contra el máximo valor absoluto finito; si el máximo es 0, la barra mide 0 % (sin división por cero). Valores negativos usan `NEG`, no una barra positiva engañosa.
2. **Línea de skew**: valor, límite y estado textual `NORMAL`/`BREACH` tomados del backend. La barra representa `min(abs(skew) / limit, 1)`, con tratamiento explícito de `limit <= 0` como dato no disponible; `breached` manda sobre el color/estado, no una comparación recalculada.
3. **Tabla compacta de eventos**: los `recent` de `/pnl`, con hora local (`new Date(ts * 1000)`), skew antes→después, `fee_btc`, `cost_usd` y `ref_mark`. No mostrar origen/destino. Un `ts` no finito o `<= 0` se muestra como “timestamp no disponible”, nunca como 1970.
4. **Costes separados**: “Decisión amortizada · última oportunidad {id}” usa `decisionCost.usd`; “Debitado al ledger · sesión” usa `pnl.rebalance.cost_total_usd`. Se presentan en tarjetas distintas, no se suman y explican que el segundo ya está incluido en `realized_pnl`.
5. **Nota siempre visible**: “Inventario pre-posicionado. Reposición fiat por wire off-line, fuera de alcance de esta simulación”. El rebalanceo periódico solo redistribuye BTC libre.

Referencia visual (valores ilustrativos, no fixtures):

```text
┌─ INVENTARIO & REBALANCEO · CAPITAL SIMULADO ─────────────────────────────┐
│              BTC                 Quote             Equity simulada        │
│ kraken       1.80 ████████       $84,120           $197,520               │
│ coinbase     0.70 ███            $128,400          $172,500               │
│ gemini       2.10 █████████      $76,930           $209,230               │
├──────────────────────────────────────────────────────────────────────────┤
│ Skew 42% ▕████████░░░░▏ límite 50% · NORMAL                              │
│ Decisión amortizada (última opp) $13.40 │ Debitado sesión $40.20         │
│ Rebalanceos: 3 · último: 12:41:08                                       │
│ ⓘ Inventario pre-posicionado · reposición fiat por wire fuera de alcance │
└──────────────────────────────────────────────────────────────────────────┘
```

### RF-005 Estados vacíos, parciales y de error

- `rebalance.count === 0` con resumen válido muestra “Sin rebalanceos en la sesión” y mantiene visible la sección y el coste debitado `$0.00`.
- `rebalance` ausente no equivale a cero eventos: muestra “Historial de rebalanceos no disponible”.
- Respuesta vacía honesta de `/balances` (`balances: []`, `snapshot: null`) muestra “Portfolio no inicializado”; no pinta venues ni saldos cero.
- Si falla `/balances` y no existe dato previo, usar `FetchFallback` tal como existe (`primitives.tsx:103-131`): su texto de error es fijo (“No se pudo cargar.”) y el string configurable es el de carga — `loading="Cargando inventario simulado…"` — más `onRetry`. No modificar el primitivo ni duplicarlo; skew/eventos de un `/pnl` válido pueden seguir visibles como sección parcial.
- Si falla `/balances` después de un éxito, conservar los valores, mostrar badge “DATOS DESACTUALIZADOS” y la hora de `updatedAt`; no borrar el panel ni afirmar que está en vivo.
- Si solo hay datos de algunas secciones o venues, renderizar lo disponible y “—” en cada campo faltante. No completar con promedios, snapshot duplicado, valores del mockup ni ceros sintéticos.
- Todas las cifras y el título se etiquetan como capital/inventario **simulado**.

### RF-006 Estilo y accesibilidad

Reutilizar `BRAND`, `POS`, `NEG`, `VenueTag`, `SectionHeader`, `FetchFallback` y `StatCard` del design system (`frontend/components/primitives.tsx:7-12,28-131,137-212`); no duplicar hexadecimales ni crear primitivos paralelos. Los nombres de venue usan `VenueTag` (trae punto de color estable por exchange y fallback gris para desconocidos); las dos tarjetas de coste de RF-004 usan `StatCard` (`accent="neutral"`, `sub` para fuente/alcance); el badge “DATOS DESACTUALIZADOS” es el `Badge` de Mantine ya usado en la página (`variant="light" color="yellow"`), no un componente nuevo. Las barras son `Box`/divs con estilo inline (patrón de barra de erosión de `NaiveVsEdgePanel`), no un chart. Cifras con `ff="monospace"`/`mono-nums`. Las barras incluyen etiqueta textual o `aria-label` con venue, métrica y valor, y el estado de skew no depende solo del color.

## Cambios técnicos

Backend:

- `backend/app/sim/rebalancer.py` — `import time` junto a los imports existentes (línea 12) y reemplazar `ts=0.0` por `ts=time.time()` en la línea 46 (única llamada afectada).
- `backend/tests/test_inventory.py` — prueba dedicada `test_rebalance_event_has_wall_clock_epoch_ts` junto a `test_rebalancer_periodic_task_fires_once_then_idles` (líneas 767-790), reutilizando su andamiaje: `SimpleNamespace(portfolio, detector)`, `rebalance_interval_ms = 5` y drift inicial que fuerza exactamente un rebalanceo.

Frontend:

- `frontend/hooks/useStream.ts` — tipos exactos, estado/refresco de `/balances`, retry/frescura y extracción acotada del coste de decisión desde la explicación existente.
- Nuevo `frontend/components/InventoryPanel.tsx` — render puro según `InventoryPanelProps`.
- `frontend/app/page.tsx` — consumir los nuevos valores de `useStream` y montar el panel en Operación.

## Plan de implementación

1. Corregir `ts=0.0` y añadir el test determinista del epoch (bloqueante: sin esto la tabla mentiría con 1970).
2. Declarar tipos TS fieles a las ramas completa/vacía de `/pnl` y `/balances`.
3. Integrar `/balances` y el coste de decisión en el ciclo ligero existente, con una sola petición en vuelo, retry, abort y frescura.
4. Implementar `InventoryPanel.tsx`: filas/barras, skew, costes, tabla, nota fiat y estados parcial/vacío/error.
5. Montar en Operación y verificar fixtures completos, cero eventos, portfolio vacío, respuesta parcial y backend caído.

## Pruebas

Backend:

- `test_rebalance_event_has_wall_clock_epoch_ts` (en `backend/tests/test_inventory.py`): con `time.time` parcheado a `1_720_000_000.25` vía `monkeypatch` sobre el módulo `app.sim.rebalancer`, un tick que rebalancea registra en `pnl_summary()["rebalance"]["recent"][0]["ts"]` exactamente ese epoch. El test existente `test_rebalancer_periodic_task_fires_once_then_idles` sigue en verde con `rebalance_count == 1`.
- Ejecutar la suite dirigida `uv run pytest tests/test_inventory.py` y confirmar que `Portfolio.rebalance(..., ts=valor)` sigue conservando el valor inyectado (los tests existentes ya usan `ts=1.0`/`ts=2.0`).

Frontend — smoke manual documentado: no hay harness de pruebas de componente (los scripts de `frontend/package.json` son solo `dev/build/start/lint/typecheck`), así que los casos siguientes se verifican a mano contra el dashboard y se registran en el PR:

- Fixture completo con dos venues y un evento: seis importes de inventario, skew/límite, dos costes y las cinco columnas reales del evento visibles.
- `count: 0, recent: []`: texto exacto “Sin rebalanceos en la sesión”, sin excepción.
- Rama vacía real de `/balances`: “Portfolio no inicializado”, sin `$0.00` ni `0 BTC` fabricados.
- Respuesta parcial (falta quote de un venue, `skew: {}`, sin `rebalance`): “—” y “Historial de rebalanceos no disponible”, sin excepción ni `NaN`/`Infinity` en DOM.
- Fallo inicial y fallo después de éxito: respectivamente fallback con retry y snapshot preservado con badge de desactualización.
- Cadencia observada en la pestaña Network: pull inicial + un `/balances` cada 5 s, máximo uno en vuelo; al navegar fuera y volver a Operación (el panel se desmonta por `keepMounted={false}`) no se duplican requests ni aparecen warnings de setState en consola.
- Ejecutar `npm run typecheck`, `npm run lint` y `npm run build`.

## Criterios de aceptación

- Con respuesta completa, cada exchange recibido ocupa una fila y muestra su BTC, quote y equity simulada sin abrir DevTools.
- Un rebalanceo forzado muestra `skew_before`, `skew_after`, `fee_btc`, `cost_usd`, `ref_mark` y una fecha local derivada de un epoch `> 0`; no aparece 1970.
- Los cinco casos de frontend definidos en Pruebas renderizan sin excepción, `NaN`, `Infinity` ni ceros sintéticos.
- En 15 s de operación estable se observan como máximo cuatro requests de `/balances` (inicial + ticks de 5, 10 y 15 s), nunca dos simultáneos.
- Backend caído antes del primer éxito muestra retry; caído después de un éxito conserva datos y los marca “DATOS DESACTUALIZADOS”.
- Cero eventos y resumen ausente producen mensajes distintos y verificables.
- Coste amortizado de la última oportunidad y coste debitado de sesión aparecen con fuente/alcance distintos; no existe una suma de ambos.
- La nota de reposición fiat y la etiqueta “capital simulado” son visibles sin hover.
- `open_btc`, origen y destino no aparecen en UI ni se añaden a los contratos.
- Suite backend dirigida y `typecheck`/`lint`/`build` frontend finalizan con código 0.

## Riesgos

- Confundir ausencia con cero. Mitigación: propiedades opcionales, guards runtime y estados distintos para `count === 0` vs `rebalance` ausente.
- Mezclar snapshots de distinta cadencia. Mitigación: precedencia explícita, `updatedAt` visible y coste de decisión etiquetado por oportunidad.
- Duplicar fetches o dejarlos solaparse. Mitigación: un solo `pullLight`, guard de in-flight y cleanup con abort.
- Inventar semántica que el contrato no tiene (`open_btc`, origen/destino). Mitigación: pintar solo campos verificados; `open_btc` permanece stretch.
- Confundir coste de decisión con coste contable. Mitigación: fuente, signo y alcance explícitos; tarjetas separadas y ninguna suma.
