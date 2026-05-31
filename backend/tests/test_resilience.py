"""STORY-012b — Suite de pruebas adversariales y de resiliencia.

Cubre los modos de fallo de los componentes YA CONSTRUIDOS (Sprint 1):
  1. FEED-KILL + reconexión: ExchangeIngestor reintenta con backoff sin `break`,
     CancelledError termina el loop limpio.
  2. BACKPRESSURE SSE: cliente lento no bloquea a los demás ni al publisher
     (drop-oldest por cola de cliente).
  3. NO-LEAK de listeners SSE: suscribir+desconectar N veces → client_count vuelve
     a la línea base (sin colas de clientes muertos acumuladas).
  4. BUS flood: inundar BoundedQueue → drop-oldest determinista, contador `dropped`
     correcto, los más recientes sobreviven, nunca bloquea.
  5. PEG stale/ausente: sin peg vivo el Normalizer devuelve None (nunca finge 1.0);
     peg fuera de tolerancia se marca.
  6. LIBRO CORRUPTO end-to-end: NaN/inf, vacío, un solo nivel → evaluator + simulator
     + portfolio: sin crash, sin NaN propagado a neto/equity/P&L.
  7. FILL PARCIAL con libro delgado: profundidad < q_target → matched=min, leg risk
     expuesto, sin crash.

NOTA: los tests de caos de CIRCUIT BREAKERS (STORY-018) y UNWIND de leg risk
(STORY-016) se añadirán cuando esos componentes existan (Sprint 2); STORY-012b cubre
la resiliencia de lo ya construido.
"""
from __future__ import annotations

import asyncio
import math

import pytest

from app.bus.queue import BoundedQueue
from app.config import ExchangeConfig, Settings
from app.engine.evaluator import NetEvaluator
from app.ingest.exchange_ingestor import ExchangeIngestor
from app.models.enums import DiscardReason, LegSide, OpportunityStatus, Strategy
from app.models.events import StreamEvent
from app.models.market import NormalizedBook, RawOrderBook
from app.models.opportunity import Opportunity
from app.normalize.normalizer import Normalizer
from app.normalize.peg import PegProvider
from app.sim import ExecutionSimulator
from app.sim.inventory import Portfolio
from app.stream.hub import StreamHub

# ---------------------------------------------------------------------------
# Helpers compartidos
# ---------------------------------------------------------------------------

class FakeClient:
    """Reproduce un guion de respuestas de `watch_order_book` (book o excepción).
    Idéntico al de test_ingest.py — reutilizado como patrón oficial del proyecto."""

    def __init__(self, scripted: list) -> None:
        self._scripted = list(scripted)
        self.calls = 0
        self.closed = False

    async def watch_order_book(self, symbol: str, limit: int | None = None) -> dict:
        self.calls += 1
        if not self._scripted:
            await asyncio.sleep(3600)  # agota el guion → bloquea hasta cancelación
        item = self._scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True


def _cfg_binance() -> ExchangeConfig:
    return ExchangeConfig(
        id="binance", symbol="BTC/USDT", quote_ccy="USDT",
        fee_taker=0.0010, withdrawal_btc=0.0002, ob_limit=5,
    )


def _settings(**over) -> Settings:
    base = dict(
        min_net_profit_usd=0.0,
        max_slippage=1.0,
        default_trade_qty_btc=1.0,
        exec_latency_ms=150,
        exchanges={
            "binance": ExchangeConfig(
                id="binance", symbol="BTC/USDT", quote_ccy="USDT",
                fee_taker=0.0010, withdrawal_btc=0.0002, ob_limit=20,
            ),
            "kraken": ExchangeConfig(
                id="kraken", symbol="BTC/USD", quote_ccy="USD",
                fee_taker=0.0040, withdrawal_btc=0.00005, ob_limit=25,
            ),
        },
    )
    base.update(over)
    return Settings(**base)


def _book(ex: str, bids, asks) -> NormalizedBook:
    return NormalizedBook(
        exchange=ex, symbol="BTC/USD", quote_ccy="USD",
        bids=bids, asks=asks, price_norm_factor=1.0, ts_recv_monotonic=0.0,
    )


def _viable(buy: str = "binance", sell: str = "kraken",
            q: float = 1.0, vb: float = 100.0, vs: float = 110.0) -> Opportunity:
    return Opportunity(
        id="opp-r", strategy=Strategy.spatial, symbol="BTC/USD",
        buy_venue=buy, sell_venue=sell, q_target=q,
        vwap_buy=vb, vwap_sell=vs, status=OpportunityStatus.viable,
    )


def _detected(buy: str = "binance", sell: str = "kraken") -> Opportunity:
    return Opportunity(
        id="opp-r", strategy=Strategy.spatial, symbol="BTC/USD",
        buy_venue=buy, sell_venue=sell, q_target=1.0,
        status=OpportunityStatus.detected,
    )


# ===========================================================================
# 1. FEED-KILL + reconexión
# ===========================================================================

async def test_feed_kill_ingestor_retries_without_break():
    """N errores consecutivos → reconecta con backoff (sin `break`), entrega libros
    tras recuperarse.  Verifica `calls >= N+1` (los errores + el libro final)."""
    good_book = {
        "bids": [[70000.0, 1.0]], "asks": [[70010.0, 2.0]],
        "timestamp": 1, "nonce": 1,
    }
    # 3 errores seguidos, luego un libro válido
    scripted = [
        RuntimeError("ws timeout"),
        ConnectionResetError("connection reset"),
        OSError("network unreachable"),
        good_book,
    ]
    fake = FakeClient(scripted)
    received: list = []
    ing = ExchangeIngestor(
        _cfg_binance(), received.append,
        client_factory=lambda c: fake, max_backoff=0.01,
    )
    task = asyncio.create_task(ing.run())

    # Espera hasta recibir al menos 1 libro (con timeout generoso)
    for _ in range(500):
        if received:
            break
        await asyncio.sleep(0.01)

    await ing.close()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert received, "debe entregar al menos un libro tras recuperarse"
    assert fake.calls >= 4, "debe haber llamado watch_order_book en cada error + libro"
    assert fake.closed is True


async def test_feed_kill_cancelled_error_terminates_loop():
    """CancelledError propagado correctamente: el loop termina limpio sin swallowing."""
    # El cliente bloquea indefinidamente (lista vacía → sleep 3600)
    fake = FakeClient([])
    received: list = []
    ing = ExchangeIngestor(
        _cfg_binance(), received.append,
        client_factory=lambda c: fake, max_backoff=0.01,
    )
    task = asyncio.create_task(ing.run())
    await asyncio.sleep(0)  # cede el control para que el task arranque

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task  # debe propagarse, no swallowed


async def test_feed_kill_multiple_errors_then_recovery():
    """Patrón: error → libro → error → libro → el ingestor nunca se rompe."""
    good = {"bids": [[50000.0, 1.0]], "asks": [[50010.0, 1.0]], "timestamp": 2, "nonce": 2}
    scripted = [RuntimeError("err1"), good, RuntimeError("err2"), good]
    fake = FakeClient(scripted)
    received: list = []
    ing = ExchangeIngestor(
        _cfg_binance(), received.append,
        client_factory=lambda c: fake, max_backoff=0.01,
    )
    task = asyncio.create_task(ing.run())

    for _ in range(600):
        if len(received) >= 2:
            break
        await asyncio.sleep(0.01)

    await ing.close()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(received) >= 2


# ===========================================================================
# 2. BACKPRESSURE SSE
# ===========================================================================

async def test_backpressure_slow_client_does_not_block_publisher():
    """Un cliente con cola llena (no consume) NO debe bloquear la llamada publish()
    ni impedir que el siguiente evento llegue a otros clientes."""
    hub = StreamHub(client_queue_maxsize=2)
    fast_gen = hub.subscribe()
    slow_gen = hub.subscribe()
    # El async-gen registra su cola solo cuando se inicia la iteración.
    # Arrancamos ambas colas con __anext__() en tareas y cedemos el event loop.
    t_fast = asyncio.create_task(fast_gen.__anext__())
    t_slow = asyncio.create_task(slow_gen.__anext__())
    await asyncio.sleep(0)  # deja que ambas tareas registren sus colas

    assert hub.client_count == 2

    # Llena las colas publicando 5 eventos (maxsize=2); el 1º llega a las tareas
    # en vuelo (t_fast / t_slow los resuelven), los siguientes llenan la cola.
    for i in range(5):
        hub.publish(StreamEvent(type="quote", data={"i": i}))

    # Las tareas en vuelo ya están resueltas — esperamos su resultado
    ev_fast = await asyncio.wait_for(t_fast, timeout=1.0)
    ev_slow = await asyncio.wait_for(t_slow, timeout=1.0)
    assert ev_fast.type == "quote"
    assert ev_slow.type == "quote"

    await fast_gen.aclose()
    await slow_gen.aclose()
    assert hub.client_count == 0


async def test_backpressure_drop_oldest_preserves_most_recent():
    """Con maxsize=3 y 6 publicaciones, la cola del cliente conserva los 3 más
    recientes (drop-oldest).

    Nota sobre la interacción con getters en vuelo: asyncio.Queue.put_nowait()
    inserta en el deque ANTES de despertar al getter. Si la cola se llena mientras
    el getter aún no ha consumido su ítem reservado, el drop-oldest puede eliminar
    ese ítem también. El resultado es que siempre se entregan los 3 ÚLTIMOS eventos
    publicados, independientemente de si había un getter en vuelo.
    """
    hub = StreamHub(client_queue_maxsize=3)
    gen = hub.subscribe()
    # Registra la cola arrancando la iteración
    t = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    assert hub.client_count == 1

    # Publica 6 eventos; drop-oldest garantiza que solo sobreviven los 3 últimos
    for i in range(6):
        hub.publish(StreamEvent(type="q", data={"n": i}))

    # Recoge los 3 eventos resultantes (siempre los más recientes)
    received = []
    first = await asyncio.wait_for(t, timeout=1.0)
    received.append(first.data["n"])
    for _ in range(2):
        t2 = asyncio.create_task(gen.__anext__())
        ev = await asyncio.wait_for(t2, timeout=1.0)
        received.append(ev.data["n"])

    await gen.aclose()

    # Los 3 valores recibidos deben ser los 3 más altos (drop-oldest)
    assert sorted(received) == [3, 4, 5]


async def test_backpressure_slow_client_does_not_delay_fast_client():
    """Dos clientes: el lento nunca consume; el rápido recibe todos sus eventos
    sin esperar al lento."""
    hub = StreamHub(client_queue_maxsize=5)
    fast_gen = hub.subscribe()
    slow_gen = hub.subscribe()  # nunca consume  # noqa: F841
    # Arranca ambas colas con __anext__() en tareas
    t_fast = asyncio.create_task(fast_gen.__anext__())
    t_slow = asyncio.create_task(slow_gen.__anext__())
    await asyncio.sleep(0)  # registra ambas colas
    assert hub.client_count == 2

    # Publica 5 eventos; el 1er evento resuelve las tareas en vuelo
    for i in range(5):
        hub.publish(StreamEvent(type="ev", data={"i": i}))

    # Recoge el 1er evento de cada tarea en vuelo
    first_fast = await asyncio.wait_for(t_fast, timeout=1.0)
    # t_slow se resuelve también (no nos importa su valor)
    await asyncio.wait_for(t_slow, timeout=1.0)

    # Recoge los 4 eventos restantes del cliente rápido
    received = [first_fast.data["i"]]
    for _ in range(4):
        task = asyncio.create_task(fast_gen.__anext__())
        ev = await asyncio.wait_for(task, timeout=1.0)
        received.append(ev.data["i"])

    await fast_gen.aclose()
    await slow_gen.aclose()

    # El cliente rápido recibió los 5 eventos en orden sin bloquearse por el lento
    assert len(received) == 5
    assert received == sorted(received)  # en orden creciente


# ===========================================================================
# 3. NO-LEAK de listeners SSE
# ===========================================================================

async def test_sse_no_leak_repeated_subscribe_unsubscribe():
    """Suscribir y desconectar (cerrar el async-gen) N veces → client_count vuelve
    a la línea base (no se acumulan colas de clientes muertos).

    Patrón: la tarea en vuelo sobre __anext__ debe cancelarse y awaited ANTES de
    llamar a aclose() — no se puede cerrar un async-gen mientras está corriendo.
    """
    hub = StreamHub(client_queue_maxsize=10)
    baseline = hub.client_count  # 0

    N = 20
    for _ in range(N):
        gen = hub.subscribe()
        # Arranca la iteración para registrar la cola
        t = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0)
        assert hub.client_count == baseline + 1

        # Cancela la tarea en vuelo y espera su finalización: esto propaga
        # CancelledError al generador, que ejecuta su finally y descarta la cola.
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass

        assert hub.client_count == baseline

    assert hub.client_count == baseline


async def test_sse_no_leak_concurrent_clients_all_close():
    """5 clientes concurrentes: todos cierran → client_count vuelve a 0."""
    hub = StreamHub(client_queue_maxsize=10)

    async def subscriber():
        gen = hub.subscribe()
        # Arranca la iteración para registrar la cola
        t = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0)
        # Cancela la tarea → propaga CancelledError al generador → finally descarta cola
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass

    await asyncio.gather(*[subscriber() for _ in range(5)])
    assert hub.client_count == 0


async def test_sse_client_count_tracks_live_connections():
    """client_count refleja exactamente el número de generadores abiertos."""
    hub = StreamHub(client_queue_maxsize=10)
    tasks = []
    for i in range(1, 6):
        g = hub.subscribe()
        # Arranca la iteración para que la cola quede registrada
        t = asyncio.create_task(g.__anext__())
        await asyncio.sleep(0)
        tasks.append(t)
        assert hub.client_count == i

    # Desconecta cancelando cada tarea (el generador ejecuta su finally)
    for i, t in enumerate(tasks):
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
        assert hub.client_count == len(tasks) - i - 1


# ===========================================================================
# 4. BUS flood (BoundedQueue)
# ===========================================================================

async def test_bus_flood_drop_oldest_counter():
    """Inundar la cola: `dropped` cuadra exactamente con los descartados."""
    maxsize = 5
    flood = 20
    q: BoundedQueue[int] = BoundedQueue(maxsize=maxsize)
    for i in range(flood):
        q.put_nowait(i)

    expected_dropped = flood - maxsize
    assert q.dropped == expected_dropped
    assert q.qsize() == maxsize


async def test_bus_flood_most_recent_survive():
    """Los elementos más recientes sobreviven en el flood (drop-oldest)."""
    maxsize = 3
    flood = 10
    q: BoundedQueue[int] = BoundedQueue(maxsize=maxsize)
    for i in range(flood):
        q.put_nowait(i)

    # Los últimos `maxsize` publicados deben ser los supervivientes
    surviving = [await q.get() for _ in range(maxsize)]
    assert surviving == list(range(flood - maxsize, flood))


async def test_bus_flood_never_blocks():
    """put_nowait NO debe bloquear nunca aunque la cola esté llena."""
    q: BoundedQueue[int] = BoundedQueue(maxsize=2)
    # Llenamos en bucle síncrono (no await): si bloqueara, el test se colgaría
    for i in range(100):
        q.put_nowait(i)  # síncrono, no await
    assert q.dropped == 98
    assert q.qsize() == 2


async def test_bus_flood_dropped_accumulates_across_bursts():
    """El contador `dropped` acumula entre múltiples ráfagas."""
    q: BoundedQueue[int] = BoundedQueue(maxsize=2)
    q.put_nowait(0)
    q.put_nowait(1)
    q.put_nowait(2)  # descarta 0, dropped=1
    await q.get()    # vacía 1
    q.put_nowait(3)
    q.put_nowait(4)  # descarta 2, dropped=2
    assert q.dropped == 2


# ===========================================================================
# 5. PEG stale/ausente
# ===========================================================================

def test_peg_absent_normalizer_returns_none():
    """Sin peg vivo, el Normalizer devuelve None para USDT (nunca finge 1.0)."""
    peg = PegProvider()
    norm = Normalizer(peg)
    raw = RawOrderBook(
        exchange="binance", symbol="BTC/USDT", quote_ccy="USDT",
        bids=[(70000.0, 1.0)], asks=[(70010.0, 1.0)], ts_recv_monotonic=1.0,
    )
    result = norm.normalize(raw)
    assert result is None, "sin peg vivo debe devolver None, nunca falsear 1.0"


def test_peg_stale_out_of_tolerance_marked():
    """Peg fuera de tolerancia (depeg) queda marcado como `within_tolerance=False`."""
    peg = PegProvider(target="USD", tolerance=0.005)
    peg.update("USDT", 0.9997, source="kraken", ts=0)
    assert peg.within_tolerance("USDT") is True  # dentro de ±0.5%

    peg.update("USDT", 0.90, source="kraken", ts=1)  # depeg extremo
    assert peg.within_tolerance("USDT") is False


def test_peg_usd_always_returns_one():
    """La moneda target (USD) siempre devuelve factor 1.0 sin necesitar peg vivo."""
    peg = PegProvider(target="USD")
    assert peg.factor_for("USD") == 1.0
    assert peg.within_tolerance("USD") is True


def test_peg_unknown_currency_returns_none():
    """Moneda desconocida sin entrada → None (nunca inventa factor)."""
    peg = PegProvider()
    assert peg.factor_for("EUR") is None
    assert peg.within_tolerance("EUR") is False


def test_normalizer_with_live_peg_applies_factor():
    """Con peg vivo el Normalizer aplica el factor correctamente."""
    peg = PegProvider()
    peg.update("USDT", 0.9995, source="kraken", ts=0)
    norm = Normalizer(peg)
    raw = RawOrderBook(
        exchange="binance", symbol="BTC/USDT", quote_ccy="USDT",
        bids=[(70000.0, 1.0)], asks=[(70010.0, 1.0)], ts_recv_monotonic=1.0,
    )
    nb = norm.normalize(raw)
    assert nb is not None
    assert abs(nb.best_bid - 70000.0 * 0.9995) < 1e-9
    assert abs(nb.best_ask - 70010.0 * 0.9995) < 1e-9
    assert nb.price_norm_factor == 0.9995


# ===========================================================================
# 6. LIBRO CORRUPTO end-to-end
# ===========================================================================

def test_corrupted_book_nan_qty_evaluator_thin_book():
    """Libro con qty=NaN → thin_book, q_target=0.0, net_pnl=None (sin NaN propagado)."""
    ev = NetEvaluator(_settings())
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, float("nan"))])
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)])
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.thin_book
    assert opp.q_target == 0.0
    assert opp.net_pnl is None


def test_corrupted_book_inf_price_evaluator_thin_book():
    """Precio=inf en asks → walk_book lo ignora → profundidad 0 → thin_book."""
    ev = NetEvaluator(_settings())
    buy = _book("binance", bids=[(99, 5)], asks=[(float("inf"), 1.0)])
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)])
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.thin_book
    assert math.isfinite(opp.q_target)


def test_corrupted_book_empty_asks_evaluator_thin_book():
    """Book con asks vacíos → thin_book, sin crash."""
    ev = NetEvaluator(_settings())
    buy = _book("binance", bids=[(99, 5)], asks=[])
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)])
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.thin_book


def test_corrupted_book_nan_price_simulator_no_crash():
    """Precio NaN en asks del venue de compra → simulator no crashea;
    matched_qty finito (posiblemente 0)."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(float("nan"), 1.0)])
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)
    assert math.isfinite(ex.matched_qty)
    assert math.isfinite(ex.realized_pnl)
    assert math.isfinite(ex.leg_risk_mtm)


def test_corrupted_book_nan_bid_simulator_mtm_finite():
    """best_bid=NaN en el venue de compra (leg risk largo) → MTM finito, no NaN."""
    s = _settings()
    sim = ExecutionSimulator(s)
    # buy: bids con NaN, asks llenos → fills 1.0; sell: solo 0.4 → leg risk largo en binance
    buy = _book("binance", bids=[(float("nan"), 5.0)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[(110.0, 0.4)], asks=[(111.0, 5.0)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)
    assert math.isfinite(ex.leg_risk_mtm), "MTM no debe ser NaN aunque best_bid sea NaN"
    assert ex.leg_risk_qty > 0.0


def test_corrupted_book_inf_bid_portfolio_equity_finite():
    """Precio inf en best_bid del libro → equity del portfolio finita (nunca inf/NaN)."""
    s = _settings()
    portfolio = Portfolio(s)
    sim = ExecutionSimulator(s)

    # Ejecución normal para tener algo en el portfolio
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)
    portfolio.apply_execution(ex)

    # Libro corrupto con best_bid=inf para marcar el portfolio
    corrupt_buy = _book("binance", bids=[(float("inf"), 5.0)], asks=[(100.0, 5.0)])
    normal_sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)])
    books = {"binance": corrupt_buy, "kraken": normal_sell}

    equity = portfolio.equity_total(books)
    assert math.isfinite(equity), "equity no debe ser inf/NaN con precios corruptos"


def test_corrupted_book_empty_bids_evaluator_thin_book():
    """Libro de venta sin bids → thin_book, sin crash."""
    ev = NetEvaluator(_settings())
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[], asks=[(111, 5)])
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.thin_book


def test_corrupted_book_single_level_evaluator_no_crash():
    """Libro de un solo nivel (muy delgado pero no corrupto): evaluador no crashea."""
    s = _settings(max_slippage=1.0)
    ev = NetEvaluator(s)
    # Un nivel de 0.05 BTC: < 10% del objetivo (1.0 BTC) → thin_book
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 0.05)])
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)])
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.thin_book
    assert math.isfinite(opp.q_target)


def test_corrupted_book_nan_propagation_portfolio_pnl_finite():
    """Fill parcial con libro corrupto → realized_pnl finito en portfolio."""
    s = _settings()
    portfolio = Portfolio(s)
    sim = ExecutionSimulator(s)

    # Libro de compra con qty NaN → walk_book lo ignora → matched_qty = 0
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, float("nan"))])
    sell = _book("kraken", bids=[(110.0, 0.4)], asks=[(111, 5)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)
    portfolio.apply_execution(ex)

    books = {
        "binance": _book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)]),
        "kraken": _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)]),
    }
    assert math.isfinite(portfolio.realized_pnl)
    assert math.isfinite(portfolio.equity_total(books))
    assert math.isfinite(portfolio.unrealized_pnl(books))


# ===========================================================================
# 7. FILL PARCIAL con libro delgado (consolida AC del simulador)
# ===========================================================================

def test_thin_book_partial_fill_matched_is_min():
    """Profundidad de venta < q_target → matched = min(buy_fill, sell_fill)."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)])    # 5 BTC disponibles
    sell = _book("kraken", bids=[(110.0, 0.3)], asks=[(111, 5)])   # solo 0.3 BTC
    opp = _viable(q=1.0)
    ex = sim.simulate(opp, buy, sell, ts=1.0)

    assert ex.partial is True
    assert abs(ex.matched_qty - 0.3) < 1e-9
    assert math.isfinite(ex.realized_pnl)
    assert math.isfinite(ex.leg_risk_mtm)


def test_thin_book_partial_fill_leg_risk_exposed():
    """Fill parcial: el excedente de compra queda como leg risk (largo en binance)."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[(110.0, 0.4)], asks=[(111, 5)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)

    assert ex.leg_risk_qty == pytest.approx(0.6)
    assert ex.leg_risk_venue == "binance"
    assert ex.leg_risk_side == LegSide.buy
    assert ex.leg_risk_mtm > 0.0  # MTM positivo (largos en binance)


def test_thin_book_partial_fill_no_crash_on_zero_depth_sell():
    """Profundidad de venta = 0 → matched = 0, leg risk = q_buy_filled, sin crash."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[], asks=[(111, 5)])   # sin bids
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)

    assert ex.matched_qty == pytest.approx(0.0)
    assert ex.partial is True
    assert ex.leg_risk_qty == pytest.approx(1.0)
    assert math.isfinite(ex.leg_risk_mtm)
    assert math.isfinite(ex.realized_pnl)


def test_thin_book_partial_fill_realized_pnl_only_matched():
    """P&L realizado cubre SÓLO el tramo casado; el excedente abierto no se contabiliza."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 5.0)])
    sell = _book("kraken", bids=[(110.0, 0.5)], asks=[(111, 5)])
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)

    matched = 0.5
    fee_buy = matched * 100.0 * 0.0010
    fee_sell = matched * 110.0 * 0.0040
    expected_pnl = (110.0 - 100.0) * matched - fee_buy - fee_sell
    assert ex.realized_pnl == pytest.approx(expected_pnl)
    assert ex.matched_qty == pytest.approx(matched)


def test_thin_book_evaluator_discards_below_min_fill_ratio():
    """Profundidad < 10% del objetivo (MIN_FILL_RATIO) → thin_book en evaluator."""
    s = _settings()
    ev = NetEvaluator(s)
    # 0.09 BTC disponibles < 10% de 1.0 BTC objetivo → thin_book
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 0.09)])
    sell = _book("kraken", bids=[(110.0, 5.0)], asks=[(111, 5)])
    opp = ev.evaluate(_detected(), buy, sell)
    assert opp.status == OpportunityStatus.discarded
    assert opp.discard_reason == DiscardReason.thin_book


def test_thin_book_both_legs_partial_fill():
    """Ambos legs delgados: matched = min de ambos, sin crash."""
    s = _settings()
    sim = ExecutionSimulator(s)
    buy = _book("binance", bids=[(99, 5)], asks=[(100.0, 0.6)])   # 0.6 BTC
    sell = _book("kraken", bids=[(110.0, 0.7)], asks=[(111, 5)])  # 0.7 BTC
    ex = sim.simulate(_viable(), buy, sell, ts=1.0)

    # matched = min(0.6, 0.7) = 0.6
    assert ex.matched_qty == pytest.approx(0.6)
    assert ex.partial is True
    # Excedente de venta = 0.7 - 0.6 = 0.1 (corto en kraken)
    assert abs(ex.leg_risk_qty - 0.1) < 1e-9
    assert ex.leg_risk_venue == "kraken"
    assert math.isfinite(ex.leg_risk_mtm)
