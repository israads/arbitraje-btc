# Respuestas al comité — Coding Challenge México

> Listas para copiar y pegar en el correo a `info@coding-challenge-mecico.com`.
> Antes de enviar: verifica que el dominio coincida con el de la convocatoria original ("mecico" vs "mexico").

---

## PREGUNTA 01 — Selección de criptomonedas para arbitraje real

Mi punto de partida es que la pregunta correcta no es "¿qué moneda?", sino "¿dónde se cumple esta desigualdad?":

```
spread_persistente > fees(2 patas) + slippage(a mi tamaño) + costo_rebalanceo + riesgo_latencia
```

En mi proyecto medí exactamente eso y la conclusión fue contundente: sobre BTC, un gap nativo de +$97 entre Binance y Kraken se convirtió en −$12 al normalizar el peg USDT/USD, y en **net negativo tras fees**. La oportunidad existe pero el costo se la come. Por eso no elegiría "una" moneda: correría un *screening* que re-rankea candidatos por edge neto en cada momento. Dicho esto, los tiers donde la desigualdad sí se cumple son:

**1) Mid-caps líquidos (mi elección principal): SOL, XRP, DOGE, LINK, AVAX, TON.** Son el punto óptimo entre liquidez e ineficiencia: tienen profundidad suficiente para dimensionar, pero spreads más anchos y persistentes que BTC/ETH (donde el HFT ya cerró el gap a 0.1–1%), y cotizan en muchos venues —más venues significan más pares ordenados que comparar—.

**2) Peg/depeg de stablecoins.** Mi sistema ya normaliza USDT/USDC/USD por peg vivo. Eventos como USDe cayendo a $0.65 (oct-2025) son la oportunidad de cola gruesa, con la salvedad de que un 2% "gratis" en una stable suele ser un depeg en curso, no un regalo —por eso implementé un gate de tolerancia de peg—.

**3) Primas regionales / rails fiat (ángulo México).** Aquí el spread persiste por barreras estructurales (regulación, FX, settlement), no por velocidad —el premium coreano o el diferencial de Bitso en MXN—. Es donde un actor mid-size sí puede jugar, porque le pagan por mover capital y asumir riesgo de settlement, no por ser el más rápido. La stablecoin MXNB (peso 1:1) abre un corredor interesante.

**4) Triangular intra-venue** (BTC→ETH→USDT en un solo exchange): elimina por completo el riesgo de transferencia y de legging cross-venue, porque todo liquida en la misma cuenta.

La idea de fondo: el arbitraje viable migró de "carrera de velocidad sobre majors" a "donde las fricciones estructurales crean spreads persistentes". Mi sistema no apuesta por una moneda; mide cuál sobrevive a los costos y dimensiona con su capacity curve antes de que el edge marginal cruce cero.

---

## PREGUNTA 02 — Gestión de órdenes parciales o fallidas

Una pata parcial o fallida rompe la neutralidad del arbitraje y me deja una posición direccional expuesta al precio. Es el riesgo existencial de cualquier estrategia de dos patas, y lo modelé explícitamente en mi proyecto.

Mi lógica base es: lo realmente casado es `matched = min(filled_compra, filled_venta)`. El excedente no casado se registra como *leg risk* con su cost basis y se marca a mercado; el P&L realizado solo cuenta el tramo casado, y la posición abierta va aparte como no realizado (separación que me costó depurar: atrapé bugs de doble conteo y de P&L fantasma). Sobre esa base aplico una **escalera de decisión por umbrales**:

1. **Re-completar**: si tras la latencia la pata faltante sigue siendo net-positiva dentro de un *time budget* acotado, la completo.
2. **Hedge inmediato**: si no, neutralizo el delta al instante con un perpetuo en el venue más profundo y barato, y deshago el spot con calma. El perp es el hedge más líquido que existe; preferirlo a un unwind forzado en libro fino es la respuesta institucional.
3. **Unwind acotado**: si no hay hedge razonable, deshago la pata ejecutada a mercado aceptando una pérdida acotada (lo tengo implementado: `unwound=True`, pérdida a realized).
4. **Retener como inventario** solo si deshacer en libro delgado cuesta más que el movimiento adverso esperado.

Mitigaciones que añadiría para producción real (donde sim ≠ real):

- **Tipo de orden**: IOC (llena lo inmediato y cancela el resto) o FOK (todo-o-nada, cero parcial a costa de menor fill rate).
- **Secuenciación**: ejecutar primero la pata difícil (venue menos líquido), confirmar el fill y luego disparar la pata profunda.
- **Dimensionar al mínimo de ambas profundidades** (walk-the-book), para minimizar parciales por construcción.
- **Reconciliación e idempotencia**: cada orden con *client order id*; ante timeout/desconexión, consultar el estado real —"fallida" no es "no ejecutada", pudo llenarse— y nunca reenviar a ciegas.
- **Límites duros**: notional máximo de leg risk abierto y un *breaker* que corta flujo nuevo si el inventario abierto supera el umbral (ya implementado vía circuit breakers + kill switch).

La filosofía: tratar el fill parcial como esperado, no excepcional; acotar siempre la pérdida; y nunca dejar que el fallo de una pata se propague.

---

## PREGUNTA 03 — Rebalanceo de wallets: criterios y frecuencia

El problema es estructural: cada trade agota quote en el venue de compra y cripto en el de venta. El skew crece y, sin gestión, un día no tengo el activo correcto en el venue correcto justo cuando aparece la oportunidad —costo de oportunidad silencioso—.

La decisión de diseño más importante, que tomé en mi proyecto, es separar dos capas:

**1) Inventario pre-posicionado.** Mantengo cripto + fiat en cada venue para que cada arbitraje sea local e instantáneo, sin transferencia on-chain por trade. Es el diseño correcto del mundo real: el settlement on-chain (minutos a horas de confirmaciones, más fees) es demasiado lento para una oportunidad que vive ~1 segundo. En mi evaluador incluso amortizo el costo de rebalanceo sobre los trades esperados, en vez de cargar un withdrawal completo por operación.

**2) Rebalanceo periódico** que restaura esa distribución.

**Criterios y frecuencia:**

- **Por banda, no por reloj.** Rebalanceo cuando el skew supera un umbral (normalizado por el inventario gross), no en horario fijo. Una *no-trade band* evita el churn y el desperdicio de fees. El chequeo es event-driven y frecuente; la *acción* solo se dispara fuera de la banda.
- **Cost-aware.** Solo rebalanceo si el valor de oportunidad recuperado supera el costo total de transferencia, que no es solo el fee de retiro: incluye fee de red, el riesgo de precio de la cripto en tránsito (que hedgeo con un perp mientras viaja) y el costo de oportunidad del capital bloqueado.
- **Cripto vs fiat se tratan distinto.** La cripto va on-chain (lento, con fee, con riesgo de precio en tránsito → batchear envíos y hedgear el tramo en vuelo). El fiat va por rails bancarios (lentos, en horario hábil, pero sin riesgo de precio) o —la respuesta moderna— usando stablecoins como rail de rebalanceo (USDT/USDC, o MXNB para el corredor mexicano): 24/7, barato y casi instantáneo.
- **Asimetría de flujo.** Si un venue es estructuralmente el "comprador" y otro el "vendedor", siempre me agotaré del mismo lado: pre-posiciono más del lado que se agota (targets direccionales, no iguales) y neteo trades en una ventana antes de transferir.
- **Automatización con freno.** Umbrales y transferencias automáticas, pero con gate de aprobación (multi-sig o límite de notional) por encima de cierto monto, direcciones de retiro en whitelist y límites de retiro —la exposición de hot wallet es un riesgo de seguridad, no solo de capital—.

Como dato, mi capacity curve cuantifica precisamente esto: el costo de rebalanceo es lo que aplana la curva y fija la capacidad máxima del sistema antes de que el edge marginal cruce cero. Es decir, no solo lo gestiono: medí cómo limita la escala de todo el negocio.
