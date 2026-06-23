# Investigación externa y roadmap de mejora

Fecha de corte: 18 de junio de 2026.

Este documento resume una investigación pública sobre proyectos del Coding Challenge México 2026, proyectos open source comparables y papers relevantes para arbitraje cripto. No sustituye una lista oficial de finalistas: no encontré una publicación oficial con ganadores o repos aceptados, así que la comparación usa repos públicos que mencionan explícitamente el reto, el sitio oficial y fuentes abiertas.

## Contexto del reto

Fuentes revisadas:

- Sitio oficial: <https://www.coding-challenge-mexico.com/>
- Publicaciones públicas sobre la convocatoria, incluyendo referencias al problema financiero/cripto, formato remoto, 48 horas y despliegue web.
- Búsquedas GitHub por `Coding Challenge Mexico`, `Coding Challenge México`, `arbitraje Bitcoin Coding Challenge`, `btc arbitrage coding challenge mexico` y variantes.

Señales importantes para evaluación:

- El problema favorece ingeniería full-stack con datos en tiempo real, no solamente una estrategia financiera.
- El jurado probablemente premia explicabilidad, despliegue funcional, robustez ante feeds inestables y una demo que se pueda evaluar rápido.
- La diferencia entre una app llamativa y una solución seria está en mostrar costo ejecutable: profundidad, fees, latencia, inventario, peg USD/USDT, falsos positivos y control de riesgo.

## Repos públicos encontrados del challenge

| Proyecto | Stack | Qué hace bien | Riesgo o límite observado | Lección para este repo |
|---|---:|---|---|---|
| [crazy-valter/arbitraje-de-bitcoin](https://github.com/crazy-valter/arbitraje-de-bitcoin) | FastAPI, Vue, Postgres, Redis | Arquitectura hexagonal, Docker, CI/CD, auth, Redis TTL, Postgres, documentación amplia | Demo usa spreads sintéticos grandes; el modelo de ejecución parece menos fino | Mantener el rigor matemático, pero presentar mejor la historia DevOps |
| [omarbramirez/btc-arbitrage-bot](https://github.com/omarbramirez/btc-arbitrage-bot) | Node, Express, React, Vite | WS directo Binance/Kraken, VWAP, circuit breakers, despliegue Railway/Vercel | Más compacto, menos profundo en proyecciones | Nuestra ventaja debe explicarse con endpoints y pruebas |
| [JaavRJ/coding-challenge-mexico](https://github.com/JaavRJ/coding-challenge-mexico) | Java, Spring Boot, Next.js | BigDecimal, SSE, paper trading, triangular, demo flash crash | Proyecto pesado para demo rápida | Adoptar el lenguaje de precisión y escenarios, sin perder simplicidad |
| [aarmentah/coding-challenge-mexico](https://github.com/aarmentah/coding-challenge-mexico) | Java, Flutter, Redis | Flujo operativo con aprobación humana y WhatsApp | Usa señales más cercanas a ticker/top-of-book | Documentar mejor por qué un bot automático necesita profundidad y EV |
| [JoahanMorales/CODING_CHALLENGE_MEXICO](https://github.com/JoahanMorales/CODING_CHALLENGE_MEXICO) | TypeScript | Decimal.js, CRC, OFI/MLOFI, microprice, FDR, aprendizaje sombra, test-order bridge | Muchas piezas ambiciosas; no todo es fácil de auditar rápido | Inspiración fuerte para features de microestructura y calibración |
| [UzielTzab/coding-challenge-mexico-vue-drf](https://github.com/UzielTzab/coding-challenge-mexico-vue-drf) | Django, DRF, Vue, Channels | Stack clásico, wallets, PnL, Redis/Postgres | Cobertura de exchanges limitada | Nuestra documentación debe dejar claro el alcance multi-exchange |
| [rvvictor/Challenge-CODING-CHALLENGE-MEXICO](https://github.com/rvvictor/Challenge-CODING-CHALLENGE-MEXICO) | FastAPI, React | WS primero con ccxt.pro, REST fallback, cross/triangular, EV queue, demo determinista | Puede competir directamente en narrativa técnica | Enfatizar validación, frontera, capacidad y modelo de riesgo |
| [TacosyHorchata/hackathon-btc-arbitrage](https://github.com/TacosyHorchata/hackathon-btc-arbitrage) | Python stdlib, vanilla frontend, Rust opcional | "Judge in 60 seconds", quote lanes, stress mode, cero instalación pesada | Menos plataforma, más demo | Crear un guion de demo igual de directo |
| [4liyat/arbitrage_system](https://github.com/4liyat/arbitrage_system) | FastAPI, React | Implementación simple Binance/Coinbase | Menos profundidad | Nuestra ventaja está en profundidad y riesgo, no en minimalismo |
| [kryptomarireal/bitbot](https://github.com/kryptomarireal/bitbot) | Go, React | Binance Spot Testnet, asistente IA, MCP, tutoriales, AWS/Caddy | Mucho foco en presentación y agentic tooling | Añadir testnet/preflight y un asistente solo de lectura sería diferenciador |
| [ImanolD/btc_arbitrage_cchallenge](https://github.com/ImanolD/btc_arbitrage_cchallenge) | TypeScript, Bun, Vite | Modo EV vs spread, supervivencia de oportunidad, asistente, WhatsApp | Algunas piezas son más demo que motor | Exponer `P_survive` y contraste naive-vs-EV en UI |
| [JulioVecino/btc-arbitrage](https://github.com/JulioVecino/btc-arbitrage) | Go, React, PWA | Hot path eficiente, parser zero-allocation, z-score, persistencia, re-quote con latencia, circuit breaker | Usa `float64`; precisión contable discutible | Medir y documentar latencia propia; considerar optimización incremental |
| [ManuelCanulDev/Coding_Challenge_Mexico](https://github.com/ManuelCanulDev/Coding_Challenge_Mexico) | Node, React, CCXT | "Reality check": fondos preposicionados vs transferencia, SQLite settings, Coolify | Profundidad limitada | Copiar la claridad del modo reality-check |
| [HumbertoBernal/atalaya-arb](https://github.com/HumbertoBernal/atalaya-arb) | Next.js | Despliegue muy simple, no backend state, L2 WS, triangular Coinbase | Menos backend y persistencia | Una demo pública estable importa mucho |
| [AlanPidal/Coding_Challenge_2026](https://github.com/AlanPidal/Coding_Challenge_2026) | JavaScript | Tracker cripto visual | No es arbitraje central | No competir por visualización genérica |
| [abiside/coding-challenge-mexico](https://github.com/abiside/coding-challenge-mexico) | HTML | Entrada ligera | Poca señal técnica pública | La documentación debe mostrar sustancia |
| [Seebaastiaan/coding-challenge-mexico](https://github.com/Seebaastiaan/coding-challenge-mexico) | TypeScript | Entrada del reto | Poca información pública | Mantener foco en evidencia verificable |
| [Humol-e/Coding-challenge-mexico](https://github.com/Humol-e/Coding-challenge-mexico) | N/D | Entrada pública | Poca información pública | No inferir ventajas sin evidencia |

## Comparación directa con este proyecto

### Mapa técnico interno

| Capa | Archivos principales | Lectura técnica | Mejora de mayor impacto |
|---|---|---|---|
| Orquestación | `backend/app/main.py`, `backend/app/state.py`, `backend/app/runner.py` | Un solo proceso FastAPI con lifespan claro, event loop único, tasks de ingesta, normalización, bus, motor, simulación, cartera, persistencia y SSE | Documentar un diagrama de secuencia tick -> oportunidad -> ejecución simulada -> UI |
| Configuración | `backend/app/config.py` | Settings `ARB_`, exchanges habilitables y parámetros de riesgo/costos | Agregar tabla de variables críticas por perfil: demo, live-readonly, testnet, producción |
| Ingesta | `backend/app/ingest/*`, `backend/app/integrity/checker.py` | Ingestores por exchange, normalización posterior e integridad básica del libro | Añadir checks específicos por venue: sequence gaps, CRC donde aplique, reconexión y edad de snapshot |
| Normalización | `backend/app/normalize/*` | Peg provider y normalización a USD; ya ataca el error común de asumir USDT = USD | Exponer basis y penalización de peg como datos de primera clase en UI/API |
| Motor | `backend/app/engine/*` | Detector espacial, z-score, evaluador neto, priorizador y math de libro | Agregar endpoint de explicación por oportunidad con todos los componentes del score |
| Economía | `backend/app/engine/cost_model.py` | Punto fuerte: una sola fuente para VWAP, fees, slippage, rebalance y neto | Extender a sensibilidad por tamaño y curva acumulada precomputada por libro |
| Riesgo | `backend/app/risk/*` | Breakers, watchdog y kill switch; descarta antes de simular si el sistema está haltado | Documentar matriz de breakers con disparador, efecto y métrica visible |
| Simulación e inventario | `backend/app/sim/*` | Simulación taker, portfolio, rebalancer y P&L | Añadir estados estilo ejecución real: reserved, submitted, partial, hedged, reconciled |
| Backtest/replay | `backend/app/backtest/*` | Grabación y replay point-in-time para demo y validación | Convertir replay en calibrador de supervivencia de oportunidad |
| Proyección | `backend/app/projection/*` | Frontier, capacity y forward; pocos competidores muestran esta capa | Añadir comparación visual naive spread vs edge esperado |
| API | `backend/app/api/v1/router.py` | REST/SSE completo con endpoints de control, métricas, validación y proyecciones | Documentar contratos de respuesta mínimos para jurado y futuros clientes |
| Frontend | `frontend/app/page.tsx`, `frontend/components/*` | Dashboard denso con waterfall, frontier, capacity, forward, funnel, PnL y control | Hacer más visible el inspector de decisión y razones de descarte |
| Pruebas | `backend/tests/*` | Cobertura amplia por módulos: costo, evaluator, proyección, stream, risk, persistence, demo | Agregar pruebas de contratos JSON para docs y snapshots de demo determinista |

Fortalezas claras del repo actual:

- Evalúa la oportunidad como edge ejecutable, no como spread visual.
- Camina libro por volumen y calcula VWAP por lado.
- Incluye fees taker, slippage, latencia, riesgo de pierna, penalización por inventario y peg USD/USDT.
- Tiene validación determinista del waterfall de edge neto.
- Incluye endpoints no comunes en otros proyectos: `projection`, `capacity`, `forward`, `validation`, `metrics`.
- Tiene arquitectura asincrónica, fallback demo, métricas de funnel y protección de event loop para cálculos pesados.
- Documenta invariantes y supuestos, lo que ayuda a auditar el criterio financiero.

Debilidades relativas frente al campo:

- Ya existe guion de evaluación; la siguiente brecha es convertirlo en demo determinista dentro del producto.
- No hay, al menos en la documentación principal, una historia de ejecución testnet con orden real o preflight firmado.
- No se muestra una comparación lado a lado contra un bot naive top-of-book.
- La parte de microestructura puede ir más lejos: sequence gaps por exchange, CRC cuando aplique, OFI/MLOFI, microprice y calibración con replay.
- No hay scanner triangular o funding/basis arbitrage, mientras varios competidores lo mencionan.
- La documentación ya está separada en PRDs, arquitectura, ejecución y runbooks; el siguiente paso es implementar esa ruta.

## Open source comparable

| Proyecto | Qué aporta | Cómo usarlo como referencia |
|---|---|---|
| [ccxt/ccxt](https://github.com/ccxt/ccxt) | API unificada de exchanges; base del ecosistema | Mantener compatibilidad y documentar diferencias entre REST, WS y `ccxt.pro` |
| [hummingbot/hummingbot](https://github.com/hummingbot/hummingbot) | Bot cripto maduro, market making, cross-exchange market making, conectores | Inspirarse en conectores, estrategias, inventario, hedge y configuración |
| [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | Backtesting, estrategia, hyperopt, UI, Telegram, gestión de riesgo | Inspirarse en backtesting reproducible, reporting y estrategia configurable |
| [Drakkar-Software/OctoBot](https://github.com/Drakkar-Software/OctoBot) | Bot con UI, estrategias y despliegue para usuarios | Mejorar experiencia de configuración y operaciones |
| [maxme/bitcoin-arbitrage](https://github.com/maxme/bitcoin-arbitrage) | Detector clásico de arbitraje con profundidad | Referencia histórica para explicar por qué profundidad importa |
| [wardbradt/peregrine](https://github.com/wardbradt/peregrine) | Bellman-Ford para detectar ciclos entre muchos mercados | Base algorítmica para triangular y multi-hop |
| [nkaz001/hftbacktest](https://github.com/nkaz001/hftbacktest) | Backtest L2/L3 con latencias y queue position | Inspiración para replay más realista y simulación de fills |
| [tardis-dev/tardis-node](https://github.com/tardis-dev/tardis-node) | Datos históricos y tiempo real tick-level | Fuente potencial para pruebas históricas serias |
| [zlq4863947/triangular-arbitrage](https://github.com/zlq4863947/triangular-arbitrage) | Proyecto chino de arbitraje triangular | Referencia para scanner triangular, aunque está archivado |
| [zlq4863947/triangular-arbitrage2](https://github.com/zlq4863947/triangular-arbitrage2) | Segunda versión de triangular arbitrage | Referencia de arquitectura server-side |
| [liaohuqiu/btcbot-open](https://github.com/liaohuqiu/btcbot-open) | Bot chino de "brick moving" entre Binance y Bitfinex | Recalca fondos preposicionados y órdenes FOK |
| [c1ay/carry_brick](https://github.com/c1ay/carry_brick) | Estrategia china de hedging/arbitraje | Referencia de matriz exchange-cliente |
| [cryptocj520/bphltaoli](https://github.com/cryptocj520/bphltaoli) | Arbitraje por funding rate en Hyperliquid/Backpack | Extensión natural a futuros/perpetuos |

Lectura del ecosistema:

- En Estados Unidos y Europa, los proyectos maduros tienden a enfocarse en conectores, backtesting, market making, inventario, configuración y operación continua.
- En repos chinos aparece mucho el concepto de "mover ladrillos": capital preposicionado, FOK, transferencia fuera de la ruta crítica, funding y triangular.
- En proyectos del reto mexicano, la mayoría optimizó para una demo clara en 48 horas; pocos mostraron un modelo profundo de edge ejecutable.

## Papers y literatura relevante

| Fuente | Hallazgo útil | Implicación para este proyecto |
|---|---|---|
| [Makarov y Schoar, Trading and Arbitrage in Cryptocurrency Markets](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3171204) | Hay arbitrajes persistentes entre exchanges; son mayores entre regiones y se relacionan con fricciones de capital | Modelar settlement, capital preposicionado y corredores regionales es más realista que asumir transferencia instantánea |
| [MIT Sloan CFI summary](https://mitsloan.mit.edu/cfi/trading-and-arbitrage-cryptocurrency-markets) | La misma investigación enfatiza segmentación de mercado y límites de arbitraje | Documentar por qué no basta con ver precio distinto |
| [Hautsch, Scheuch y Voigt, Building Trust Takes Time](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3302159) | La latencia de settlement y el riesgo de contraparte limitan el arbitraje blockchain | Separar arbitraje con balances preposicionados de arbitraje que depende de transferir activos |
| [BIS WP 955, Quantifying the high-frequency trading arms race](https://www.bis.org/publ/work955.htm) | La latencia explica una fracción importante del spread efectivo y del impacto | Medir y mostrar `latency_ms` y supervivencia de oportunidad como parte central del score |
| [A limit order book model for latency arbitrage](https://arxiv.org/abs/1110.4811) | El beneficio de ser rápido depende de LOB, impacto y competencia | Penalizar latencia por tamaño y profundidad, no solo con una constante |
| [Latency Arbitrage in Cryptocurrency Markets](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5143158) | En cripto, velocidad de ejecución y dinámica del order book son críticas | Añadir replay y métricas de caducidad de señales |
| [Avellaneda y Stoikov, High-frequency trading in a limit order book](https://people.orie.cornell.edu/sfs33/LimitOrderBook.pdf) | Inventario y riesgo cambian el precio óptimo de cotización | Usar penalización de inventario y rebalancing como parte visible de la decisión |
| [High-frequency market-making with inventory constraints](https://arxiv.org/abs/1206.4810) | Extiende el control de inventario en market making | Base para un módulo maker/taker futuro |
| [Cont, Kukanov y Stoikov, The Price Impact of Order Book Events](https://arxiv.org/abs/1011.6402) | Order Flow Imbalance predice movimientos de corto plazo | Añadir OFI como feature para `P_survive` |
| [Multi-Level Order-Flow Imbalance](https://arxiv.org/abs/1907.06230) | La señal de imbalance mejora al mirar varios niveles del libro | Medir MLOFI por venue para evitar fills adversos |
| [Statistical Arbitrage in Cryptocurrency Markets](https://www.mdpi.com/1911-8074/12/1/31) | Capacidad, costos y restricciones de short reducen rentabilidad | La frontera de capacidad debe ser parte de la demo, no un extra |
| [Deep Limit Order Book Forecasting: a microstructural guide](https://arxiv.org/html/2403.09267v1) | Buen pipeline LOB exige limpieza, frames y modelos reproducibles | Formalizar dataset de replay y features |
| [Explainable Patterns in Cryptocurrency Microstructure](https://arxiv.org/html/2602.00776v1) | Imbalance y patrones intradía existen, pero ejecución real tiene ruido y jitter | Priorizar explicabilidad sobre black-box ML |
| [Exploring Microstructural Dynamics in Cryptocurrency Limit Order Books](https://arxiv.org/html/2506.05764v2) | Los LOB cripto son ruidosos; se necesita extracción robusta de señal | Cuidar outliers, stale books y gaps |

## Roadmap priorizado

El roadmap ejecutable vive en [`docs/prd/README.md`](prd/README.md), la arquitectura técnica en
[`docs/architecture/README.md`](architecture/README.md) y el plan de implementación en
[`docs/execution/README.md`](execution/README.md). Esas carpetas separan requisitos, diseño y
tareas para evitar duplicar decisiones.

### P0 - Documentación y demo evaluable

Objetivo: que un jurado entienda en menos de 2 minutos por qué el proyecto es superior a un spread watcher.

Acciones:

- Añadir un guion de demo con comandos, endpoints y orden recomendado.
- Crear tabla "criterio del reto -> evidencia en repo -> endpoint/test".
- Documentar el contraste `spread bruto` vs `edge ejecutable`.
- Añadir una captura o flujo de UI para la explicación waterfall.
- Preparar modo `STRESS` o `DEMO_JURY` con oportunidades deterministas etiquetadas como demo.

Criterio de aceptación:

- Una persona puede levantar backend/frontend, abrir la UI y ver una oportunidad explicada sin leer código.
- La demo muestra al menos una oportunidad aceptada y varias rechazadas con razón explícita.

### P1 - Modelo de datos y microestructura

Objetivo: mejorar la precisión de la probabilidad de ejecución.

Acciones:

- Guardar oportunidades rechazadas en un dataset de "shadow learning".
- Calibrar `P_survive` con replay: edad del libro, volatilidad, spread, tamaño, OFI/MLOFI, venue, hora y latencia.
- Implementar sequence gap checks por exchange donde el feed lo permita.
- Añadir CRC32 de Kraken y validaciones equivalentes por venue cuando estén disponibles.
- Precomputar curvas acumuladas de profundidad para calcular VWAP por múltiples tamaños con menos costo.
- Exponer en API y UI `basis_usd_usdt`, `peg_adverse_bps`, edad de libro y score de integridad.

Criterio de aceptación:

- Cada oportunidad tiene una explicación con features de microestructura.
- Replay produce métricas de calibración: tasa de supervivencia estimada vs observada.

### P2 - Ejecución y preflight testnet

Objetivo: demostrar que el sistema puede aproximarse a ejecución real sin poner capital en riesgo.

Acciones:

- Añadir modo `TESTNET_ONLY` con Binance Spot Testnet o equivalente.
- Implementar preflight firmado: balances, min notional, precision, lot size, fee tier, dry-run/test order.
- Separar claramente estados: detected, preflighted, reserved, submitted, partially_filled, hedged, reconciled, failed.
- Añadir cancel/kill switch y límites por venue, ruta y exposición.
- Registrar payloads de orden saneados, sin secretos.

Criterio de aceptación:

- La demo puede mostrar un `TEST_ORDER` o preflight firmado con ID testnet.
- Ninguna ruta de ejecución real se activa sin flags explícitos y confirmación.

### P3 - Arbitrajes adicionales

Objetivo: ampliar cobertura sin diluir el motor principal.

Acciones:

- Scanner triangular intra-venue con Bellman-Ford o multiplicación logarítmica de tasas.
- Scanner funding/basis para spot-perp o perp-perp.
- Corredor regional México: Bitso/MXN, USD/MXN, USDT/MXN y costo de conversión.
- Separar "same quote lane" de "cross-stablecoin lane" en UI y métricas.

Criterio de aceptación:

- Cross-exchange spot sigue siendo el path principal.
- Triangular y funding aparecen como módulos desactivables, con costos propios.

### P4 - Observabilidad y operación

Objetivo: convertir la demo en sistema operable.

Acciones:

- Exportador Prometheus o endpoint compatible para métricas de latencia, stale feeds, oportunidades, rechazos y errores.
- Dashboard Grafana de salud de feeds y funnel.
- Runbook de incidentes: feed stale, exchange down, peg roto, latencia alta, PnL divergente.
- Persistencia opcional en Postgres/Timescale para replay y auditoría.
- OpenTelemetry para trazas de ingestión -> normalización -> evaluación -> broadcast.

Criterio de aceptación:

- Una caída de feed queda visible en menos de 10 segundos.
- Una sesión de demo puede exportarse y reproducirse.

### P5 - Experiencia de producto

Objetivo: que el usuario vea el razonamiento de la máquina, no solo números.

Acciones:

- Panel "naive bot vs this engine": spread top-of-book, edge neto, razón de rechazo.
- Sliders de tamaño, latencia, fee tier, peg y rebalance.
- Inspector por oportunidad: libros caminados, waterfall, riesgo, capacidad, decisión.
- Modo replay con timeline.
- Asistente de solo lectura o MCP para contestar preguntas sobre oportunidades, métricas y estado, sin tocar ejecución.

Criterio de aceptación:

- El dashboard permite explicar cada decisión sin abrir logs.
- Los controles no prometen profit; muestran sensibilidad y límites.

## Optimizaciones técnicas concretas

Hot path:

- Mantener el cálculo principal libre de I/O y serialización pesada.
- Evitar `model_dump` o conversiones Pydantic dentro de loops de alta frecuencia salvo al emitir API/SSE.
- Usar buffers acotados y coalescing por venue/symbol para no procesar ticks obsoletos.
- Precalcular cumulative notional/size por libro para consultas VWAP repetidas.
- Medir antes de compilar: si el perfil muestra cuello de botella en walking books, considerar Rust, Cython, Numba o `msgspec`.

Ingestión:

- Registrar edad de libro por exchange y descartar snapshots stale.
- Diferenciar REST fallback de WS live en el score de calidad.
- Aislar feeds lentos para que no bloqueen oportunidades de venues sanos.
- Exponer gaps y reconexiones como métricas de primera clase.

Modelo financiero:

- Separar costo seguro de costo estimado: fees y VWAP son observables; latencia, pierna e inventario son estimaciones.
- Mostrar sensibilidad por tamaño: un edge positivo para 0.01 BTC puede desaparecer en 0.5 BTC.
- Penalizar stablecoin basis de forma asimétrica: comprar con USDT caro o vender contra USDT barato no es equivalente.
- Distinguir capital preposicionado de transferencia post-trade.

Backtest/replay:

- Usar datos tick-level cuando sea posible.
- Medir señales que sobrevivieron hasta `latency_ms` simulado.
- Simular partial fills y queue priority para escenarios maker.
- Guardar falsos positivos y falsos negativos.

## Qué no conviene hacer

- No meter un LLM en el hot path de trading.
- No vender oportunidades demo sintéticas como live.
- No prometer rentabilidad.
- No mezclar USD y USDT sin mostrar basis y riesgo de peg.
- No ejecutar con dinero real sin preflight, límites, kill switch y reconciliación.
- No perseguir microservicios si el cuello de botella real es explicación, datos o calibración.

## Backlog sugerido

1. `docs`: tabla de evidencia del reto y guion de demo.
2. `frontend`: panel naive-vs-edge y waterfall más visible.
3. `backend`: endpoint `/api/v1/opportunities/{id}/explain` con componentes del score.
4. `backend`: dataset shadow de oportunidades rechazadas.
5. `backend`: replay que calcula supervivencia observada por latencia.
6. `backend`: sequence/CRC checks por exchange soportado.
7. `backend`: curvas acumuladas de libro para VWAP por tamaño.
8. `backend`: modo testnet/preflight con orden de prueba.
9. `frontend`: sliders de latencia, tamaño, peg y fee tier.
10. `ops`: Prometheus/Grafana o exporter documentado.
11. `research`: notebook o script que compara naive spread vs edge neto en una sesión.
12. `market`: módulo triangular intra-venue.
13. `market`: módulo funding/basis arbitrage.
14. `market`: corredor México con Bitso/MXN y FX.
15. `product`: exportar sesión demo como JSON reproducible.

## Posicionamiento recomendado

Frase corta para el proyecto:

> Un motor de arbitraje BTC que no pregunta "dónde está más barato", sino "cuánto queda después de ejecutar con profundidad, fees, latencia, inventario y peg".

Mensaje competitivo:

- La mayoría de entradas del reto detectan spreads.
- Este proyecto modela si el spread puede sobrevivir ejecución.
- La UI debe convertir esa diferencia en una explicación visible y auditable.
