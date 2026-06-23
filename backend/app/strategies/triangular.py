"""Arbitraje triangular intra-venue en modo demo/replay (PRD-008).

El módulo trabaja sobre `NormalizedBook` ya normalizados/recibidos por la app. No ingiere red
ni ejecuta órdenes: detecta ciclos de tres monedas dentro de un mismo venue, cobra fee en cada
leg y valida que el tamaño configurado tenga profundidad suficiente.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from ..config import Settings
from ..models.enums import OpportunityStatus, Strategy
from ..models.market import NormalizedBook, PriceLevel
from ..models.opportunity import Opportunity
from ..models.strategy import OpportunityLeg, StrategyExplanation, StrategyRisk

_EPS = 1e-12


def _parse_symbol(symbol: str) -> tuple[str, str] | None:
    parts = symbol.replace("-", "/").split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0].upper(), parts[1].upper()


@dataclass(frozen=True)
class _Fill:
    qty_in: float
    qty_out: float
    avg_price: float | None
    fee: float
    depth_limited: bool


@dataclass(frozen=True)
class _Edge:
    venue: str
    symbol: str
    side: Literal["buy", "sell"]
    asset_in: str
    asset_out: str
    levels: list[PriceLevel]
    fee_rate: float

    def top_rate(self) -> float | None:
        if not self.levels:
            return None
        price, qty = self.levels[0]
        if price <= 0.0 or qty <= 0.0 or not math.isfinite(price) or not math.isfinite(qty):
            return None
        if self.side == "buy":
            return (1.0 / price) * (1.0 - self.fee_rate)
        return price * (1.0 - self.fee_rate)

    def fill(self, qty_in: float) -> _Fill:
        if qty_in <= 0.0 or not math.isfinite(qty_in):
            return _Fill(qty_in=0.0, qty_out=0.0, avg_price=None, fee=0.0, depth_limited=True)

        remaining = qty_in
        consumed = 0.0
        gross_out = 0.0
        notional = 0.0
        for price, qty_base in self.levels:
            if remaining <= _EPS:
                break
            if (
                price <= 0.0 or qty_base <= 0.0
                or not math.isfinite(price) or not math.isfinite(qty_base)
            ):
                continue
            if self.side == "buy":
                capacity_in = price * qty_base
                take_in = min(remaining, capacity_in)
                base_out = take_in / price
                consumed += take_in
                gross_out += base_out
                notional += take_in
                remaining -= take_in
            else:
                take_base = min(remaining, qty_base)
                quote_out = take_base * price
                consumed += take_base
                gross_out += quote_out
                notional += quote_out
                remaining -= take_base

        if consumed <= 0.0:
            return _Fill(qty_in=0.0, qty_out=0.0, avg_price=None, fee=0.0, depth_limited=True)

        fee = gross_out * self.fee_rate
        avg_price = None
        if self.side == "buy" and gross_out > 0.0:
            avg_price = notional / gross_out
        elif self.side == "sell" and consumed > 0.0:
            avg_price = notional / consumed
        return _Fill(
            qty_in=consumed,
            qty_out=gross_out - fee,
            avg_price=avg_price,
            fee=fee,
            depth_limited=remaining > _EPS,
        )

    def as_leg(self, fill: _Fill) -> OpportunityLeg:
        return OpportunityLeg(
            venue=self.venue,
            symbol=self.symbol,
            side=self.side,
            asset_in=self.asset_in,
            asset_out=self.asset_out,
            qty_in=fill.qty_in,
            qty_out=fill.qty_out,
            price=fill.avg_price,
            fee=fill.fee,
            fee_rate=self.fee_rate,
        )


class TriangularStrategy:
    id = Strategy.triangular.value

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = settings.strategy_triangular_enabled
        self._n = 0

    def on_book(
        self,
        book: NormalizedBook,
        books: dict[str, NormalizedBook],
    ) -> list[Opportunity]:
        if not self.enabled:
            return []
        return self.find_opportunities(list(books.values()), venue=book.exchange)

    def find_opportunities(
        self,
        books: list[NormalizedBook],
        *,
        venue: str | None = None,
    ) -> list[Opportunity]:
        if not self.enabled:
            return []

        by_venue: dict[str, list[NormalizedBook]] = {}
        for book in books:
            if venue is not None and book.exchange != venue:
                continue
            by_venue.setdefault(book.exchange, []).append(book)

        out: list[Opportunity] = []
        for venue_id, venue_books in sorted(by_venue.items()):
            out.extend(self._find_for_venue(venue_id, venue_books))
        return out

    def explain(self, opportunity: Opportunity) -> StrategyExplanation:
        profit = opportunity.strategy_payload.get("net_profit")
        start = opportunity.strategy_payload.get("start_currency")
        return StrategyExplanation(
            strategy=self.id,
            opportunity_id=opportunity.id,
            title="Ciclo triangular intra-venue",
            summary=f"Convierte {start} en el mismo venue y termina con ganancia neta {profit}.",
            legs=opportunity.legs or [],
            metrics={
                "gross_edge_bps": opportunity.strategy_payload.get("gross_edge_bps"),
                "net_profit": profit,
                "end_amount": opportunity.strategy_payload.get("end_amount"),
            },
            risks=[
                StrategyRisk(
                    key="precision",
                    label="Precisión/min notional",
                    severity="medium",
                    detail=(
                        "El cálculo valida profundidad, pero la precisión final depende del venue."
                    ),
                )
            ],
            payload=opportunity.strategy_payload,
        )

    def _find_for_venue(self, venue: str, books: list[NormalizedBook]) -> list[Opportunity]:
        graph = self._build_graph(venue, books)
        if not graph:
            return []

        configured_start = self.settings.strategy_triangular_start_currency.upper()
        starts = [configured_start] if configured_start in graph else sorted(graph)
        min_factor = 1.0 + (self.settings.strategy_triangular_min_profit_bps / 10_000.0)
        opportunities: list[Opportunity] = []
        seen: set[tuple[str, str, str, str]] = set()

        for start in starts:
            for mid_a, first_edges in graph.get(start, {}).items():
                for mid_b, second_edges in graph.get(mid_a, {}).items():
                    if len({start, mid_a, mid_b}) != 3:
                        continue
                    third_edges = graph.get(mid_b, {}).get(start, [])
                    for edge1 in first_edges:
                        for edge2 in second_edges:
                            for edge3 in third_edges:
                                signature = (start, edge1.symbol, edge2.symbol, edge3.symbol)
                                if signature in seen:
                                    continue
                                seen.add(signature)
                                opp = self._opportunity_from_cycle(
                                    venue,
                                    start,
                                    (edge1, edge2, edge3),
                                    min_factor=min_factor,
                                )
                                if opp is not None:
                                    opportunities.append(opp)
        return opportunities

    def _build_graph(
        self,
        venue: str,
        books: list[NormalizedBook],
    ) -> dict[str, dict[str, list[_Edge]]]:
        exchange_cfg = self.settings.exchanges.get(venue)
        fee_rate = exchange_cfg.fee_taker if exchange_cfg is not None else 0.0
        graph: dict[str, dict[str, list[_Edge]]] = {}
        for book in books:
            parsed = _parse_symbol(book.symbol)
            if parsed is None:
                continue
            base, quote = parsed
            if book.asks:
                graph.setdefault(quote, {}).setdefault(base, []).append(
                    _Edge(
                        venue=book.exchange,
                        symbol=book.symbol,
                        side="buy",
                        asset_in=quote,
                        asset_out=base,
                        levels=book.asks,
                        fee_rate=fee_rate,
                    )
                )
            if book.bids:
                graph.setdefault(base, {}).setdefault(quote, []).append(
                    _Edge(
                        venue=book.exchange,
                        symbol=book.symbol,
                        side="sell",
                        asset_in=base,
                        asset_out=quote,
                        levels=book.bids,
                        fee_rate=fee_rate,
                    )
                )
        return graph

    def _opportunity_from_cycle(
        self,
        venue: str,
        start_currency: str,
        edges: tuple[_Edge, _Edge, _Edge],
        *,
        min_factor: float,
    ) -> Opportunity | None:
        top_rates = [edge.top_rate() for edge in edges]
        if any(rate is None or rate <= 0.0 for rate in top_rates):
            return None
        rates = [rate for rate in top_rates if rate is not None]
        weight_sum = -sum(math.log(rate) for rate in rates)
        top_factor = math.prod(rates)
        if weight_sum >= 0.0 or top_factor <= min_factor:
            return None

        amount = self.settings.strategy_triangular_trade_size
        fills: list[_Fill] = []
        for edge in edges:
            fill = edge.fill(amount)
            if fill.depth_limited or fill.qty_out <= 0.0:
                return None
            fills.append(fill)
            amount = fill.qty_out

        start_amount = self.settings.strategy_triangular_trade_size
        net_profit = amount - start_amount
        if amount <= start_amount * min_factor or net_profit <= 0.0:
            return None

        self._n += 1
        gross_edge_bps = (top_factor - 1.0) * 10_000.0
        symbols = " -> ".join(edge.symbol for edge in edges)
        legs = [edge.as_leg(fill) for edge, fill in zip(edges, fills, strict=True)]
        return Opportunity(
            id=f"tri-{venue}-{self._n}",
            strategy=Strategy.triangular,
            symbol=f"{start_currency} triangular",
            buy_venue=venue,
            sell_venue=venue,
            q_target=start_amount,
            net_pnl=net_profit if start_currency == "USD" else None,
            status=OpportunityStatus.viable,
            legs=legs,
            strategy_payload={
                "venue": venue,
                "cycle": symbols,
                "start_currency": start_currency,
                "start_amount": start_amount,
                "end_amount": amount,
                "net_profit": net_profit,
                "gross_edge_bps": gross_edge_bps,
                "weight_sum": weight_sum,
                "depth_validated": True,
            },
        )
