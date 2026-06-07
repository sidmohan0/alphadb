from __future__ import annotations

import pytest

from alphadb.live_risk import UNRESOLVED_PENDING_RESERVATION_REASON
from alphadb.live_risk_refresh import (
    ExchangeOrderEvidence,
    PendingReservation,
    filled_max_loss_for,
    resolve_pending_reservation,
)


def test_resolver_releases_terminal_no_fill_and_authoritative_negative_lookup() -> None:
    canceled = resolve_pending_reservation(
        reservation(),
        ExchangeOrderEvidence(kind="order", status="canceled", fill_count=0, remaining_count=0),
    )
    negative = resolve_pending_reservation(
        reservation(order_id=None),
        ExchangeOrderEvidence(kind="negative_lookup", authoritative_no_order=True),
    )

    assert canceled.action == "release"
    assert canceled.release_max_loss_dollars == 0.82
    assert negative.action == "release"
    assert negative.reason == "authoritative_no_order"


def test_resolver_converts_filled_and_partially_filled_terminal_orders() -> None:
    full = resolve_pending_reservation(
        reservation(max_loss_dollars=0.82, intended_quantity=2),
        ExchangeOrderEvidence(kind="order", status="filled", fill_count=2, remaining_count=0),
    )
    partial_terminal = resolve_pending_reservation(
        reservation(max_loss_dollars=0.82, intended_quantity=2),
        ExchangeOrderEvidence(kind="order", status="canceled", fill_count=1, remaining_count=0),
    )

    assert full.action == "convert"
    assert full.convert_max_loss_dollars == 0.82
    assert full.release_max_loss_dollars == 0.0
    assert partial_terminal.action == "convert"
    assert partial_terminal.convert_max_loss_dollars == 0.41
    assert partial_terminal.release_max_loss_dollars == 0.41


def test_resolver_preserves_open_or_unresolved_remaining_exposure() -> None:
    open_order = resolve_pending_reservation(
        reservation(max_loss_dollars=0.82, intended_quantity=2),
        ExchangeOrderEvidence(kind="order", status="open", fill_count=0, remaining_count=2),
    )
    partial_remaining = resolve_pending_reservation(
        reservation(max_loss_dollars=0.82, intended_quantity=2),
        ExchangeOrderEvidence(kind="order", status="accepted", fill_count=1, remaining_count=1),
    )

    assert open_order.action == "preserve"
    assert open_order.preserve_max_loss_dollars == 0.82
    assert open_order.abnormal_reason == "unexpected_open_ioc_order"
    assert partial_remaining.action == "preserve"
    assert partial_remaining.convert_max_loss_dollars == 0.41
    assert partial_remaining.preserve_max_loss_dollars == 0.41


@pytest.mark.parametrize(
    "evidence",
    [
        ExchangeOrderEvidence(kind="unreachable"),
        ExchangeOrderEvidence(kind="timeout"),
        ExchangeOrderEvidence(kind="ambiguous_http", metadata={"http_status": 409}),
        ExchangeOrderEvidence(kind="unsupported_lookup"),
        ExchangeOrderEvidence(kind="artifact_only"),
        ExchangeOrderEvidence(kind="negative_lookup", authoritative_no_order=False),
        ExchangeOrderEvidence(kind="order", status=None),
    ],
)
def test_resolver_blocks_weak_or_ambiguous_evidence(evidence: ExchangeOrderEvidence) -> None:
    result = resolve_pending_reservation(reservation(), evidence)

    assert result.action == "block"
    assert result.blocks_admission is True
    assert result.blocked_reason == UNRESOLVED_PENDING_RESERVATION_REASON
    assert result.preserve_max_loss_dollars == 0.82


def test_resolver_blocks_identifierless_attempts_even_with_negative_lookup() -> None:
    result = resolve_pending_reservation(
        reservation(client_order_id=None, order_id=None),
        ExchangeOrderEvidence(kind="negative_lookup", authoritative_no_order=True),
    )

    assert result.action == "block"
    assert result.reason == "missing_exchange_identifier"


def test_filled_max_loss_is_quantity_bounded() -> None:
    assert filled_max_loss_for(reservation(max_loss_dollars=0.82, intended_quantity=2), 1) == 0.41
    assert filled_max_loss_for(reservation(max_loss_dollars=0.82, intended_quantity=2), 5) == 0.82


def reservation(
    *,
    max_loss_dollars: float = 0.82,
    intended_quantity: float = 2,
    client_order_id: str | None = "client_1",
    order_id: str | None = "ord_1",
) -> PendingReservation:
    return PendingReservation(
        reservation_id="res_1",
        market_ticker="KXBTC15M-REFRESH",
        max_loss_dollars=max_loss_dollars,
        intended_quantity=intended_quantity,
        client_order_id=client_order_id,
        order_id=order_id,
        time_in_force="immediate_or_cancel",
    )
