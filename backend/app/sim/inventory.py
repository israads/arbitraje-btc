"""C10 — Gestor de cartera: inventario pre-posicionado, doble entrada y P&L (FR-010/011).

Modela los balances por venue (BTC + moneda de cotización) inicializados desde
`ExchangeConfig.initial_btc/initial_quote` (inventario PRE-POSICIONADO: sin transferencias
on-chain por trade; el rebalanceo amortizado lo modela el evaluador, aquí NO se duplica).

Contabilidad de DOBLE ENTRADA (invariante de conservación, NFR-004): ningún dinero se
crea ni se destruye. Cada `Leg` mueve quote y BTC en sentidos opuestos en su venue:
  · comprar BTC → −quote (coste + fee), +btc   (al VWAP del fill)
  · vender BTC  → +quote (neto − fee), −btc
Se aplican AMBOS tramos del `Execution`: el tramo CASADO (`matched_qty`) y la posición
ABIERTA de LEG RISK (el excedente del leg sobre-llenado). Los balances físicos (`btc`,
`quote`) se mueven por el `qty_filled` COMPLETO de cada leg para que la conservación sea
exacta (el quote total baja sólo por fees; el BTC total se conserva salvo el desbalance de
leg risk, que queda como posición abierta).

P&L — separación clave para NO inflar el neto (honestidad del neto):
  · realized = Σ `Execution.realized_pnl` (neto del tramo CASADO, fees incl.). El tramo
    casado es un PAR CERRADO (compras Q en un venue, vendes Q en otro): su P&L vive ENTERO
    aquí y NO debe re-contarse al marcar a mercado.
  · unrealized = marca a mercado SÓLO la posición ABIERTA (el LEG RISK no casado), contra
    su COSTE BASE de entrada (`leg_risk_entry_vwap·leg_risk_qty`). NI el tramo casado NI el
    inventario PRE-POSICIONADO sembrado aportan unrealized: el primero ya está en realized,
    el segundo no es ganancia del bot (entra como base de equity, coste base = su mark).
  · total_pnl = realized + unrealized. INVARIANTE: delta_equity(mismo libro) == total_pnl.
  · equity total = Σ (quote + btc·precio_mark) por venue — marca TODO el BTC (incluido el
    sembrado), correcto para equity/drawdown del dashboard.

Skew de inventario: DESBALANCE de BTC ENTRE venues (no el neto). Se normaliza por el BTC
GROSS medio por venue (Σ|btc|/n) para que posiciones opuestas largo/corto — el estado
operativo normal del arbitraje, que netea ~0 — registren skew ALTO y disparen el flag.

Serie de equity: timeline de puntos {ts, equity} listo para el dashboard (STORY-023,
ticker count-up + equity curve). El P&L plano/levemente negativo tras costes ES el punto
(honestidad del neto): NO se infla.

Determinista: sin red ni reloj en el cómputo; el `ts` de los snapshots se inyecta.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from ..config import Settings
from ..engine.bookmath import mid_lenient
from ..models.account import Balance, InventorySnapshot
from ..models.enums import LegSide
from ..models.execution import Execution, Leg
from ..models.market import NormalizedBook
from ..models.opportunity import Opportunity

# BTC neto por debajo de este umbral se considera plano (ruido de coma flotante).
_DUST = 1e-12


class VenueBalance:
    """Balances vivos de un venue: BTC + moneda de cotización (ya en USD por peg).

    `btc`/`quote` son los balances FÍSICOS totales (incluido el inventario pre-posicionado
    sembrado): marcan toda la equity y conservan la doble entrada. Para el P&L NO realizado
    se lleva APARTE la posición ABIERTA de leg risk:

      · `open_btc`           — BTC de la posición abierta (leg risk no casado): >0 largo,
                               <0 corto. NO incluye el inventario sembrado ni el tramo casado
                               (ese P&L ya es realized).
      · `open_cost_basis_usd`— coste base (USD) de esa posición abierta, para marcar a
                               mercado el unrealized = `open_btc·mark − open_cost_basis_usd`.

    El inventario PRE-POSICIONADO entra con `open_btc = 0`: NO genera P&L no realizado
    fantasma al arranque (honestidad del neto). El tramo CASADO de cada `Execution` mueve
    `btc`/`quote` (conservación) pero NO toca `open_btc`: su P&L ya está en realized.
    """

    __slots__ = ("venue", "quote_ccy", "btc", "quote", "open_btc", "open_cost_basis_usd")

    def __init__(self, venue: str, quote_ccy: str, btc: float, quote: float) -> None:
        self.venue = venue
        self.quote_ccy = quote_ccy
        self.btc = btc
        self.quote = quote
        # Posición ABIERTA (leg risk). Arranca en 0: el BTC sembrado no es posición abierta.
        self.open_btc = 0.0
        self.open_cost_basis_usd = 0.0

    def move_physical(self, side: LegSide, qty: float, price: float, fee: float) -> None:
        """Mueve los balances FÍSICOS (`btc`/`quote`) por el `qty` llenado, con DOBLE
        ENTRADA. Comprar: −quote(coste+fee), +btc. Vender: +quote(neto−fee), −btc. Esto
        cubre TODO el leg (matched + excedente) para conservación exacta; el coste base del
        unrealized se lleva por separado en `add_open_position` (sólo el leg risk)."""
        if qty <= 0.0:
            return
        if side is LegSide.buy:
            self.quote -= qty * price + fee
            self.btc += qty
        else:
            self.quote += qty * price - fee
            self.btc -= qty

    def add_open_position(self, side: LegSide, qty: float, entry_vwap: float) -> None:
        """Acumula una posición ABIERTA de leg risk (sólo lo NO casado) con su coste base,
        para el mark-to-market posterior. `buy` → largo (+`open_btc`, +coste); `sell` →
        corto (−`open_btc`, −coste, el coste base de un corto es negativo: lo recibido al
        vender). Maneja el cruce de signo (cerrar lo previo a su coste medio y abrir el resto
        al precio de entrada) para que el unrealized del tramo recién operado y marcado a su
        propio precio sea ~0."""
        if qty <= 0.0 or entry_vwap <= 0.0:
            return
        signed = qty if side is LegSide.buy else -qty
        prev = self.open_btc
        new = prev + signed
        if prev == 0.0 or (prev > 0.0) == (signed > 0.0):
            # Mismo signo (o partiendo de plano): suma coste base del tramo a su precio.
            self.open_cost_basis_usd += signed * entry_vwap
        elif (prev > 0.0) == (new > 0.0) and abs(new) > _DUST:
            # Reduce la posición sin cruzar de signo: retira coste base al coste MEDIO previo.
            avg = self.open_cost_basis_usd / prev
            self.open_cost_basis_usd += signed * avg
        else:
            # Cruce de signo: cierra TODO lo previo (coste base → 0) y abre el remanente
            # (new) al precio de entrada. Así el nuevo tramo abierto marca contra su propio
            # precio (unrealized del tramo recién abierto ~0).
            self.open_cost_basis_usd = new * entry_vwap
        self.open_btc = new

    def equity(self, mark: float | None) -> float:
        """Equity del venue: quote + btc·precio_mark (marca TODO el BTC, incluido el
        sembrado). Si no hay mark finito, marca a 0 (sólo cuenta el quote): conservador,
        nunca propaga NaN/inf a la equity total."""
        if mark is None or not math.isfinite(mark) or mark <= 0.0:
            return self.quote
        return self.quote + self.btc * mark

    def unrealized(self, mark: float | None) -> float:
        """P&L no realizado de la posición ABIERTA (leg risk) = open_btc·mark − coste base.
        El inventario sembrado y el tramo casado NO entran aquí (no inflan el P&L). Sin mark
        válido → 0 (no inventamos P&L)."""
        if mark is None or not math.isfinite(mark) or mark <= 0.0:
            return 0.0
        if abs(self.open_btc) <= _DUST:
            return 0.0
        return self.open_btc * mark - self.open_cost_basis_usd


class Portfolio:
    """Cartera multi-venue con doble entrada, P&L y skew (C10).

    No abre red ni lee reloj: `apply_execution`/`snapshot` reciben los libros y el `ts`. Es
    el dato vivo que consumen `/balances` y `/pnl` (cableados en STORY-010) y el dashboard
    (equity series, STORY-023)."""

    def __init__(self, settings: Settings, *, equity_series_maxlen: int = 1000) -> None:
        self.settings = settings
        self.venues: dict[str, VenueBalance] = {}
        self.realized_pnl: float = 0.0
        # Capital inicial total (USD) para drawdown/retorno; BTC inicial valorado al coste 0
        # no aporta aquí (sólo quote): se compara equity_quote-only de arranque vs viva.
        self.initial_quote_total: float = 0.0
        self.initial_btc_total: float = 0.0
        # Buffers acotados (deque maxlen): recorte O(1) automático, sin trim manual.
        # Timeline de equity para la curva del dashboard (STORY-023).
        self.equity_series: deque[dict[str, float]] = deque(maxlen=equity_series_maxlen)
        # Rebalanceo periódico (STORY-017): contadores + bitácora acotada de eventos.
        self.rebalance_count: int = 0
        self.rebalance_cost_total: float = 0.0
        self.rebalance_events: deque[dict[str, float]] = deque(maxlen=100)
        self._seed_from_config()

    def _seed_from_config(self) -> None:
        """Siembra los balances por venue desde `ExchangeConfig.initial_btc/initial_quote`.
        Inventario PRE-POSICIONADO: sin transferencias on-chain (así operan los MM). Entra
        con `open_btc = 0`: NO genera unrealized fantasma (no es posición abierta del bot)."""
        for cfg in self.settings.exchanges.values():
            if not cfg.enabled:
                continue
            self.venues[cfg.id] = VenueBalance(
                venue=cfg.id,
                quote_ccy=cfg.quote_ccy,
                btc=cfg.initial_btc,
                quote=cfg.initial_quote,
            )
            self.initial_quote_total += cfg.initial_quote
            self.initial_btc_total += cfg.initial_btc

    def _venue(self, venue: str) -> VenueBalance | None:
        return self.venues.get(venue)

    def _fee_taker(self, venue: str) -> float:
        cfg = self.settings.exchanges.get(venue)
        return cfg.fee_taker if cfg is not None and math.isfinite(cfg.fee_taker) else 0.0

    def can_afford(self, opp: Opportunity) -> bool:
        """Gate de capital/inventario (FR-007 AC#4 / FR-010 'no ejecuta sin saldo'): el venue
        de COMPRA debe tener `quote` suficiente para el coste + fee taker, y el de VENTA `btc`
        suficiente para la cantidad. El motor (C7) lo consulta en orden de score descendente,
        de modo que las mejores oportunidades consumen el saldo primero y el resto se descarta
        (`insufficient_balance`) al agotarse capital/inventario.

        Usa la `q_target` (cantidad efectiva por profundidad que fijó C6) y el `vwap_buy`
        recorrido. Venue NO sembrado → no bloquea (consistente con `apply_execution`, que ignora
        venues desconocidos sin romper la conservación). `q`/`vwap` no finitos → no afford.

        CONSERVADOR (no deja balances negativos): `walk_book` recorta el fill a `q_target` en
        cada pata (`take = min(qty, q − acc)`), así el simulador consume ≤ `q_target` BTC en la
        venta y ≤ `q_target·vwap` quote en la compra; validar contra `q_target` es por tanto una
        cota SUPERIOR del consumo real. El orden serial de `on_opp` (C7) hace que el saldo ya
        esté debitado por la opp anterior cuando se evalúa la siguiente → se materializa
        "ejecuta por score desc hasta agotar capital/inventario" sin reservas explícitas."""
        q = opp.q_target
        if q is None or q == 0.0:
            q = self.settings.default_trade_qty_btc
        # Tras el fallback (None/0 → objetivo por defecto), una q no finita o negativa es dato
        # corrupto: no se opera sobre ello (no se enmascara con el default).
        if not math.isfinite(q) or q <= 0.0:
            return False
        buy_vb = self.venues.get(opp.buy_venue)
        sell_vb = self.venues.get(opp.sell_venue)
        if buy_vb is None or sell_vb is None:
            return True  # venue desconocido: no inventamos un bloqueo (no se sembró)
        vb_px = opp.vwap_buy
        vwap_buy = vb_px if (vb_px and math.isfinite(vb_px) and vb_px > 0.0) else 0.0
        cost_quote = q * vwap_buy * (1.0 + self._fee_taker(opp.buy_venue))
        return buy_vb.quote >= cost_quote and sell_vb.btc >= q

    def _withdrawal_btc(self, venue: str) -> float:
        """Fee de retiro on-chain (BTC) del venue para el rebalanceo periódico real."""
        cfg = self.settings.exchanges.get(venue)
        return cfg.withdrawal_btc if cfg is not None and math.isfinite(cfg.withdrawal_btc) else 0.0

    def _reference_mark(self, books: dict[str, NormalizedBook]) -> float | None:
        """Mark de REFERENCIA único = media de los mids válidos por venue. Se usa para
        valorar el rebalanceo con UN solo precio y así NO inventar P&L del diferencial de
        marca entre venues al redistribuir BTC (mover BTC de un venue barato a uno caro y
        marcar a su propio precio crearía una ganancia fantasma). None si ningún venue tiene
        precio válido (no rebalanceamos a ciegas)."""
        marks: list[float] = []
        for venue in self.venues:
            nb = books.get(venue)
            if nb is None:
                continue
            m = mid_lenient(nb)
            if m is not None:
                marks.append(m)
        if not marks:
            return None
        ref = sum(marks) / len(marks)
        # Revalida el resultado (no sólo los inputs): una suma de mids válidos podría
        # desbordar a inf, y un `ref` no finito/<=0 envenenaría el ledger (NaN absorbente)
        # al debitar `cost_usd`. Resto del módulo es igual de defensivo con sus resultados.
        return ref if math.isfinite(ref) and ref > 0.0 else None

    def rebalance(
        self, books: dict[str, NormalizedBook], *, ts: float = 0.0
    ) -> dict[str, float] | None:
        """Evento de rebalanceo de inventario PERIÓDICO (FR-011, STORY-017) — NO por trade.

        Si el skew de inventario supera `inventory_skew_limit`, reequilibra el BTC entre
        venues e incurre el COSTE on-chain REAL: cada venue que ENVÍA BTC (por encima de la
        media) hace un retiro y paga su `withdrawal_btc` (en BTC), que se QUEMA (sale del
        sistema como fee de red) y se refleja en `realized_pnl` valorado al mark de referencia
        ÚNICO (ver `_reference_mark`). Devuelve el evento `{ts, cost_usd, fee_btc, skew_before,
        skew_after}` o `None` si no había que rebalancear (skew bajo límite, <2 venues o sin
        precio válido).

        HONESTIDAD / NO doble conteo: el coste amortizado por-trade del evaluador (C6) es SÓLO
        una métrica de DECISIÓN (viabilidad/ranking) y NUNCA toca el ledger; el P&L realizado
        de las ejecuciones (C9) tampoco incluye rebalanceo. Este evento periódico es el ÚNICO
        que debita el coste de rebalanceo al `realized_pnl`. Determinista: recibe libros + ts,
        sin red ni reloj.

        HONESTIDAD DEL P&L (marks per-venue): `realized_pnl` carga SÓLO el fee (cargo real y
        honesto). El reparto de BTC entre venues con marks ligeramente distintos introduce un
        remark de mark-to-market en `equity_total` (que marca per-venue) acotado por el spread
        inter-venue NORMALIZADO (≈0 en venues USD por peg; EXACTAMENTE 0 con marks uniformes,
        donde el invariante `delta_equity == delta_realized` se asienta en los tests). Es el
        mismo carácter mark-dependiente que ya tiene marcar el inventario físico a mercado.

        BTC LIBRE (preserva leg risk): se reparte sólo el BTC NO comprometido en posiciones
        abiertas (`btc − open_btc`). El BTC que respalda una posición de leg risk NO se mueve
        on-chain (es exposición direccional, no inventario libre), así `open_btc` nunca queda
        descalzado del `btc` físico que lo respalda."""
        n = len(self.venues)
        if n < 2:
            return None
        skew_before = self.inventory_skew()
        if not skew_before["breached"]:
            return None
        ref = self._reference_mark(books)
        if ref is None:
            return None  # sin precio válido: no inventamos coste ni movemos a ciegas
        # BTC LIBRE por venue (descontando lo comprometido en posiciones abiertas de leg risk).
        free = {v: vb.btc - vb.open_btc for v, vb in self.venues.items()}
        total_free = sum(free.values())
        # Sin BTC libre neto que repartir (p.ej. largo+corto que netea ~0, o todo comprometido)
        # → no hay transferencia on-chain real que hacer: no inventamos coste. Cubre también
        # el caso de `new_target` negativo (fee > total_free).
        if total_free <= _DUST:
            return None
        mean_free = total_free / n
        # Coste on-chain: suma de withdrawal_btc de los venues que ENVÍAN (libre > media).
        fee_btc = 0.0
        for v, f in free.items():
            if f - mean_free > _DUST:
                fee_btc += self._withdrawal_btc(v)
        cost_usd = fee_btc * ref
        # Reparte el BTC LIBRE por igual (quemando el fee del total libre); cada venue conserva
        # su posición abierta (open_btc) intacta encima de su nueva cuota de BTC libre.
        free_target = (total_free - fee_btc) / n
        for vb in self.venues.values():
            vb.btc = vb.open_btc + free_target
        self.realized_pnl -= cost_usd
        self.rebalance_count += 1
        self.rebalance_cost_total += cost_usd
        skew_after = self.inventory_skew()
        event: dict[str, float] = {
            "ts": ts,
            "cost_usd": cost_usd,
            "fee_btc": fee_btc,
            "ref_mark": ref,
            "skew_before": skew_before["skew"],
            "skew_after": skew_after["skew"],
        }
        self.rebalance_events.append(event)
        return event

    @staticmethod
    def _leg_amounts(leg: Leg) -> tuple[float, float, float]:
        """(qty_filled, vwap, fee) del leg, saneados a finitos no negativos."""
        qty = leg.qty_filled if math.isfinite(leg.qty_filled) and leg.qty_filled > 0.0 else 0.0
        vwap = leg.vwap if math.isfinite(leg.vwap) and leg.vwap > 0.0 else 0.0
        fee = leg.fee if math.isfinite(leg.fee) and leg.fee >= 0.0 else 0.0
        return qty, vwap, fee

    def apply_execution(self, execution: Execution) -> None:
        """Aplica un `Execution` a los balances con DOBLE ENTRADA y acumula realized P&L.

        Mueve los balances FÍSICOS por el `qty_filled` COMPLETO de cada leg (matched +
        excedente): comprar −quote +btc; vender +quote −btc. Esto garantiza la conservación
        exacta (el quote total baja sólo por fees; el BTC total se conserva salvo el
        desbalance de leg risk).

        Para el P&L NO realizado SÓLO registra como posición ABIERTA el EXCEDENTE de leg
        risk (`leg_risk_qty` a `leg_risk_entry_vwap`, en `leg_risk_venue`/`leg_risk_side`):
        el tramo CASADO es un par cerrado cuyo P&L ya viene en `realized_pnl` y NO se
        re-cuenta vía mark-to-market (si no, se duplicaría el spread del matched)."""
        # 1) Balances físicos por el fill completo de cada leg (conservación exacta).
        for leg in execution.legs:
            vb = self._venue(leg.venue)
            if vb is None:
                continue  # venue desconocido (no sembrado): se ignora, no rompe balances
            qty, vwap, fee = self._leg_amounts(leg)
            if qty <= 0.0:
                continue
            vb.move_physical(leg.side, qty, vwap, fee)

        # 2) Posición ABIERTA: SÓLO el excedente de leg risk (no casado) con su coste base.
        #    El tramo casado NO se registra como abierto (su P&L ya está en realized).
        lr_qty = execution.leg_risk_qty
        if (
            execution.leg_risk_venue is not None
            and execution.leg_risk_side is not None
            and math.isfinite(lr_qty) and lr_qty > _DUST
            and math.isfinite(execution.leg_risk_entry_vwap)
            and execution.leg_risk_entry_vwap > 0.0
        ):
            vb = self._venue(execution.leg_risk_venue)
            if vb is not None:
                vb.add_open_position(
                    execution.leg_risk_side, lr_qty, execution.leg_risk_entry_vwap
                )

        # 3) Acumula el P&L realizado neto del tramo casado (fees del tramo incluidas).
        if math.isfinite(execution.realized_pnl):
            self.realized_pnl += execution.realized_pnl

    def _mark(self, venue: str, books: dict[str, NormalizedBook], btc: float) -> float | None:
        """Precio de marca para el BTC del venue contra el libro actual. Largo → best_bid
        (lo que pagan al vender); corto → best_ask (lo que cuesta recomprar); respaldo al
        mid. Sin libro o precios corruptos → None (el llamador marca a 0 ese tramo)."""
        nb = books.get(venue)
        if nb is None:
            return None
        bid, ask = nb.best_bid, nb.best_ask
        long_side = btc >= 0.0
        primary = bid if long_side else ask
        if primary is not None and math.isfinite(primary) and primary > 0.0:
            return primary
        # Respaldo: mid si ambos lados son finitos, si no el lado que quede válido.
        if (
            bid is not None and ask is not None
            and math.isfinite(bid) and math.isfinite(ask)
            and bid > 0.0 and ask > 0.0
        ):
            return (bid + ask) / 2.0
        for px in (bid, ask):
            if px is not None and math.isfinite(px) and px > 0.0:
                return px
        return None

    def unrealized_pnl(self, books: dict[str, NormalizedBook]) -> float:
        """P&L no realizado agregado: marca SÓLO la posición ABIERTA (leg risk) de cada
        venue a mercado contra el libro actual. El inventario sembrado y el tramo casado NO
        aportan. Sin libro válido para un venue → ese venue aporta 0."""
        total = 0.0
        for venue, vb in self.venues.items():
            mark = self._mark(venue, books, vb.open_btc)
            total += vb.unrealized(mark)
        return total

    def equity_total(self, books: dict[str, NormalizedBook]) -> float:
        """Equity total agregada: Σ (quote + btc·precio_mark) por venue (marca TODO el BTC)."""
        total = 0.0
        for venue, vb in self.venues.items():
            mark = self._mark(venue, books, vb.btc)
            total += vb.equity(mark)
        return total

    def equity_by_venue(self, books: dict[str, NormalizedBook]) -> dict[str, float]:
        """Equity por venue (USD), para el desglose del dashboard."""
        out: dict[str, float] = {}
        for venue, vb in self.venues.items():
            mark = self._mark(venue, books, vb.btc)
            out[venue] = vb.equity(mark)
        return out

    def inventory_skew(self) -> dict[str, Any]:
        """Desbalance de BTC ENTRE venues. `skew` = max desviación absoluta respecto al BTC
        medio por venue, normalizada por el BTC GROSS medio por venue (Σ|btc|/n). Así dos
        venues con posiciones opuestas largo/corto (el peor desbalance del arbitraje, que
        netea ~0) registran skew ALTO. `breached` cuando supera `inventory_skew_limit`. Con
        TODOS los venues realmente vacíos (gross ~0) no hay skew computable → 0/False."""
        btc_by_venue = {v: vb.btc for v, vb in self.venues.items()}
        total_btc = sum(btc_by_venue.values())
        n = len(btc_by_venue)
        gross = sum(abs(b) for b in btc_by_venue.values())
        if n == 0 or gross <= _DUST:
            return {
                "btc_by_venue": btc_by_venue,
                "total_btc": total_btc,
                "skew": 0.0,
                "limit": self.settings.inventory_skew_limit,
                "breached": False,
            }
        mean_btc = total_btc / n
        max_dev = max(abs(b - mean_btc) for b in btc_by_venue.values())
        # Normaliza por el inventario GROSS medio por venue: no se cancela con signos
        # opuestos (a diferencia del neto), así mide el desbalance real entre venues.
        skew = max_dev / (gross / n)
        return {
            "btc_by_venue": btc_by_venue,
            "total_btc": total_btc,
            "skew": skew,
            "limit": self.settings.inventory_skew_limit,
            "breached": skew > self.settings.inventory_skew_limit,
        }

    def balances(self) -> list[Balance]:
        """Balances vivos por (venue, activo): un `Balance` de BTC y uno de quote por venue."""
        out: list[Balance] = []
        for vb in self.venues.values():
            out.append(Balance(exchange=vb.venue, asset="BTC", amount=vb.btc))
            out.append(Balance(exchange=vb.venue, asset=vb.quote_ccy, amount=vb.quote))
        return out

    def record_equity_point(self, books: dict[str, NormalizedBook], *, ts: float) -> float:
        """Sella un punto {ts, equity} en la serie (acotada) y lo devuelve. Lo invoca el
        wiring tras cada `Execution` aplicado para alimentar la equity curve (STORY-023)."""
        eq = self.equity_total(books)
        self.equity_series.append({"ts": ts, "equity": eq})  # drop-oldest automático (deque)
        return eq

    def snapshot(self, books: dict[str, NormalizedBook], *, ts: float) -> InventorySnapshot:
        """`InventorySnapshot` con balances vivos y equity total marcada a mercado."""
        return InventorySnapshot(
            ts=ts,
            balances=self.balances(),
            total_usd=self.equity_total(books),
        )

    def pnl_summary(self, books: dict[str, NormalizedBook]) -> dict[str, Any]:
        """Resumen de P&L para `/pnl`: realized + unrealized + total, equity y equity series.

        `total_pnl = realized + unrealized`, donde unrealized marca SÓLO la posición abierta
        de leg risk (el tramo casado ya está en realized, el inventario sembrado no es P&L):
        así el ticker arranca en 0 sin trades y NO infla el P&L (honestidad del neto). El
        P&L plano/levemente negativo tras costes ES el punto."""
        unrealized = self.unrealized_pnl(books)
        equity = self.equity_total(books)
        return {
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": unrealized,
            "total_pnl": self.realized_pnl + unrealized,
            "equity_usd": equity,
            "initial_quote_usd": self.initial_quote_total,
            "equity_by_venue": self.equity_by_venue(books),
            "skew": self.inventory_skew(),
            "equity_series": list(self.equity_series),
            # Rebalanceo periódico (STORY-017): coste real ya incluido en realized_pnl.
            "rebalance": {
                "count": self.rebalance_count,
                "cost_total_usd": self.rebalance_cost_total,
                "recent": list(self.rebalance_events)[-10:],
            },
        }
