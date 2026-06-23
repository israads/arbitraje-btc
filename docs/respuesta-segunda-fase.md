# Respuestas segunda fase — Coding Challenge México

**Para:** info@coding-challenge-mexico.com
**Asunto:** Respuestas segunda fase — [nombre de tu proyecto] — Israel Domínguez

---

Hola,

Antes que nada gracias por la noticia. La verdad me dio mucho gusto saber que sigo entre los finalistas, y aquí van mis respuestas.

## Pregunta 1. Viabilidad real

Sí, lo haría. De hecho ya decidí continuarlo gane o no gane. Este proyecto me enseñó muchísimo sobre cómo funcionan realmente los mercados cripto y no lo quiero dejar guardado en un repositorio. Ya estoy haciendo pruebas por mi cuenta.

Ahora, siendo honesto con lo que encontré: entre los exchanges grandes (Binance, Kraken, Coinbase) el mercado de Bitcoin es mucho más eficiente de lo que parece. En mis pruebas con datos en vivo llegué a ver diferencias de hasta 97 dólares entre exchanges, que se veían como oportunidad clara. Pero cuando normalizas la moneda de cotización (USDT no vale exactamente 1 dólar, aunque todo mundo asume que sí) y descuentas comisiones, esa "oportunidad" termina siendo pérdida. Y no es un problema de velocidad, mi sistema detecta en menos de un milisegundo. El problema son los costos.

Pero justo ahí es donde veo el negocio real. El mismo sistema me dice dónde sí hay rentabilidad: con comisiones de nivel institucional el mismo trade que pierde dinero en nivel retail deja como 35 dólares netos por BTC. Y en mercados con más fricción, como el mexicano, los diferenciales entre exchanges locales y globales son bastante más grandes que entre los gigantes. Si tuviera tiempo y financiamiento, el plan sería ese: capital posicionado en dos o tres exchanges con comisiones negociadas, validar primero con el módulo de backtest que ya construí, y escalar solo lo que aguante esa prueba. No construí un sistema que promete dinero fácil. Construí uno que mide dónde hay dinero de verdad, y por eso creo que sí tiene posibilidades reales.

## Pregunta 2. Otros mercados

Sí se puede trasladar, aunque con matices. Lo que realmente se transfiere no es el "compra barato aquí, vende caro allá", sino la metodología: nunca comparar precios sin normalizar unidades, calcular la ganancia neta considerando la profundidad real del libro de órdenes y no solo el mejor precio, y meter todos los costos al cálculo antes de declarar que algo es oportunidad.

En acciones lo veo muy directo. El arbitraje estadístico que implementé (z-score sobre el spread entre dos mercados) es básicamente la base del pairs trading. En ETFs pasa algo parecido con el premium o descuento contra el valor del portafolio subyacente. Y en el caso mexicano hay un ejemplo que me gusta mucho: las acciones del SIC. Ahí el error de asumir que USDT vale un dólar tiene su equivalente exacto en asumir un tipo de cambio fijo entre el precio en México y el precio en el mercado de origen.

Las limitaciones también existen. Los mercados tradicionales están menos fragmentados (hay un solo libro centralizado por plaza, así que hay menos arbitraje espacial que explotar), la liquidación tarda uno o dos días e inmoviliza capital, los horarios son limitados, y en bonos y fondos de inversión la cosa se complica porque son mercados poco transparentes o que se valúan una vez al día. Cripto fue el laboratorio ideal para construir esto porque opera 24/7 con APIs públicas, pero la disciplina de medir el rendimiento neto después de costos sirve para cualquier activo.

## Pregunta 3. Facturación

Confirmo que no hay ningún problema. Facturo como persona física con actividad empresarial y puedo emitir el CFDI a nombre de la empresa sin complicación alguna.

---

Solo me queda decir que este challenge me ha gustado mucho más de lo que esperaba. Aprendí una barbaridad y veo una oportunidad muy interesante en todo esto. Obviamente quiero ganar, no lo voy a disimular, pero gane o no, este proyecto sigue.

Saludos,
Israel Arturo Domínguez Sarmiento
