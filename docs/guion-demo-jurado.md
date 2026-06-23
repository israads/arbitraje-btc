# Guion de demo para jurado

Objetivo: demostrar en 90 segundos que el proyecto no es un monitor de precios, sino un motor que calcula oportunidad ejecutable.

## Preparación

Backend:

```bash
cd backend
uv sync --python 3.12
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

URLs esperadas:

- API: <http://localhost:8000>
- Dashboard: <http://localhost:3000>
- Health: <http://localhost:8000/health>
- Validación: <http://localhost:8000/api/v1/validation>
- Proyección demo: <http://localhost:8000/api/v1/projection?mode=demo>
- Capacidad: <http://localhost:8000/api/v1/capacity?mode=demo>
- Forward: <http://localhost:8000/api/v1/forward>
- Demo jurado: `POST http://localhost:8000/api/v1/demo?mode=jury`
- Export sesión: <http://localhost:8000/api/v1/session/export>

## Demo de 90 segundos

1. Abrir el dashboard.

   Mensaje: "El sistema consume libros de órdenes, no solo tickers. Cada oportunidad camina profundidad y calcula precio ejecutable por tamaño".

2. Activar `Jury` en el panel de control.

   Mensaje: "Esta secuencia es determinista y está etiquetada como DEMO DATA. Recorre cinco casos: edge real, falso positivo, depeg, stale feed y profundidad adversa".

3. Mostrar una oportunidad y abrir su detalle.

   Mensaje: "El spread bruto no decide. La decisión sale después de VWAP, fees, slippage, latencia, riesgo de pierna, rebalance e impacto de peg".

4. Abrir la validación o el panel waterfall.

   Mensaje: "Esta validación determinista prueba el waterfall esperado. Si cambia una fórmula, el número deja de cerrar".

5. Mostrar oportunidades rechazadas o métricas de funnel.

   Mensaje: "La parte importante son los rechazos. El motor evita operar señales que parecen buenas en top-of-book, pero mueren después de costos".

6. Exportar la sesión desde el panel de control.

   Mensaje: "El export contiene configuración saneada, quotes, oportunidades recientes, explanations, métricas, breakers, demo status y validación; no incluye secretos".

7. Mostrar `projection`, `capacity` y `forward`.

   Mensaje: "No solo responde si una oportunidad existe ahora; estima frontera de rentabilidad, capacidad por tamaño y sensibilidad futura".

8. Cerrar con arquitectura.

   Mensaje: "El backend separa ingestión, normalización, integridad, bus, detector, evaluación neta, riesgo, simulación y streaming. La UI solo visualiza decisiones ya auditables".

## Demo técnica de 5 minutos

### 1. Salud y feeds

Comandos:

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/api/v1/quotes
```

Qué explicar:

- Exchange, símbolo, bid/ask, edad de dato y estado.
- Diferencia entre live, demo fallback y replay.
- Por qué feed stale invalida una oportunidad.

### 2. Waterfall de edge

Comando:

```bash
curl -s http://localhost:8000/api/v1/validation
```

Qué explicar:

- Spread bruto.
- VWAP por profundidad.
- Fee taker por venue.
- Slippage.
- Penalización por latencia y pierna.
- Rebalance.
- Peg USD/USDT.
- Edge neto final.

### 3. Oportunidades

Comando:

```bash
curl -X POST "http://localhost:8000/api/v1/demo?mode=jury"
curl -s http://localhost:8000/api/v1/opportunities
```

Qué explicar:

- Ruta buy venue -> sell venue.
- Tamaño evaluado.
- Edge neto.
- Score o prioridad.
- Razón de aceptación/rechazo.
- Endpoint de explicación por oportunidad: `/api/v1/opportunities/{id}/explain`.

### 4. Proyección y capacidad

Comandos:

```bash
curl -s "http://localhost:8000/api/v1/projection?mode=demo"
curl -s "http://localhost:8000/api/v1/capacity?mode=demo"
curl -s http://localhost:8000/api/v1/forward
```

Qué explicar:

- Cuánto volumen aguanta la oportunidad antes de dejar de ser rentable.
- Cómo cambia la decisión al variar tamaño, latencia o peg.
- Por qué capacidad importa más que un spread máximo aislado.

### 5. Riesgo operacional

Qué mostrar:

- Breakers.
- Métricas.
- Estado de balances si está configurado.
- Historial de ejecuciones simuladas.
- Modo demo claramente etiquetado.

### 6. Export auditable

Comando:

```bash
curl -s http://localhost:8000/api/v1/session/export
```

Qué explicar:

- Incluye settings relevantes por lista blanca, no secretos.
- Incluye oportunidades recientes con explanation cuando exista.
- Permite revisar la sesión después de la presentación.

## Preguntas esperadas y respuesta corta

### "¿Por qué no comprar donde está más barato y vender donde está más caro?"

Porque ese spread puede no existir para el tamaño que quieres operar. Al caminar el libro aparecen VWAP, fees, slippage, latencia, inventario y peg. El sistema decide con edge neto.

### "¿Mezclas USD y USDT?"

Solo si el modelo puede cobrar o penalizar el basis de stablecoin. El peg no se trata como 1.0000 garantizado.

### "¿Esto ejecuta dinero real?"

La versión de demo debe permanecer en simulación o testnet. La ejecución real requiere flags explícitos, preflight, límites, kill switch, reconciliación y secretos configurados fuera del repo.

### "¿Qué pasa si un exchange se cae?"

El feed queda marcado como stale, se reducen o eliminan oportunidades de ese venue y los breakers evitan decisiones sobre datos vencidos.

### "¿Por qué el proyecto es diferente?"

La mayoría de demos muestran spreads. Este proyecto muestra cuánto queda después de intentar ejecutar.

## Checklist antes de presentar

- Backend levanta sin errores.
- Frontend conecta al API correcto.
- `/health` responde OK.
- `/api/v1/validation` devuelve el caso determinista.
- Hay datos live, replay o demo fallback visibles.
- El modo `Jury` muestra escenario actual y badge `DEMO DATA`.
- `/api/v1/session/export` responde y no contiene secretos.
- El dashboard muestra al menos una razón de rechazo.
- Los modos demo/test/replay están etiquetados.
- No hay secretos en pantalla.
- La narrativa menciona edge ejecutable, no profit garantizado.

## Qué evitar durante la demo

- No decir que el bot garantiza ganancias.
- No presentar datos sintéticos como live.
- No afirmar que una oportunidad se puede ejecutar si no hay preflight.
- No ocultar que transferir fondos entre exchanges queda fuera de la ruta crítica.
- No explicar primero la arquitectura; empezar por la decisión financiera.
