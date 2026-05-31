"""Tests del embudo de oportunidades en AppState.

Verifican la semántica corregida en STORY-008: 'detected' es el tope del embudo
(toda opp que pasó por detección) y viable/discarded son el desglose tras el
evaluador. Antes, al reescribir el evaluador el estado a discarded/viable, el
contador 'detected' quedaba en 0 (lectura contradictoria para el jurado)."""
from __future__ import annotations

from app.config import get_settings
from app.models.enums import DiscardReason, OpportunityStatus, Strategy
from app.models.opportunity import Opportunity
from app.state import AppState
from app.stream.hub import StreamHub


def _state() -> AppState:
    return AppState(settings=get_settings(), hub=StreamHub(client_queue_maxsize=100))


def _opp(
    status: OpportunityStatus,
    *,
    id: str = "opp-1",
    reason: DiscardReason | None = None,
) -> Opportunity:
    return Opportunity(
        id=id,
        strategy=Strategy.spatial,
        symbol="BTC/USD",
        buy_venue="binance",
        sell_venue="kraken",
        status=status,
        discard_reason=reason,
    )


def _disc(**kw) -> Opportunity:
    return _opp(OpportunityStatus.discarded, reason=DiscardReason.not_profitable_fees, **kw)


def _viable(**kw) -> Opportunity:
    return _opp(OpportunityStatus.viable, **kw)


def test_detected_counts_every_opportunity():
    st = _state()
    st.record_opportunity(_disc())
    st.record_opportunity(_viable())
    # 'detected' es el tope: cuenta ambas sin importar su veredicto.
    assert st.opp_counts[OpportunityStatus.detected.value] == 2


def test_breakdown_sums_to_detected():
    st = _state()
    for _ in range(3):
        st.record_opportunity(_disc())
    st.record_opportunity(_viable())
    assert st.opp_counts[OpportunityStatus.detected.value] == 4
    assert st.opp_counts[OpportunityStatus.discarded.value] == 3
    assert st.opp_counts[OpportunityStatus.viable.value] == 1
    breakdown = (
        st.opp_counts[OpportunityStatus.viable.value]
        + st.opp_counts[OpportunityStatus.discarded.value]
    )
    assert breakdown == st.opp_counts[OpportunityStatus.detected.value]


def test_opp_already_detected_not_double_counted():
    st = _state()
    # Una opp que llega aún en 'detected' (sin evaluar) cuenta una sola vez.
    st.record_opportunity(_opp(OpportunityStatus.detected))
    assert st.opp_counts[OpportunityStatus.detected.value] == 1
    assert sum(st.opp_counts.values()) == 1


def test_recent_opps_buffer_appends():
    st = _state()
    st.record_opportunity(_viable(id="opp-42"))
    assert len(st.recent_opps) == 1
    assert st.recent_opps[-1].id == "opp-42"
