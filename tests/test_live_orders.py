from datetime import UTC, date, datetime
from uuid import uuid4

import psycopg
import pytest

from alphadb.config import settings_from_env
from alphadb.live_orders import (
    GatedLiveKalshiOrderAdapter,
    LiveOrderAttempt,
    LiveOrderError,
    LiveOrderRepository,
    exchange_response_accepted,
    kalshi_order_request_from_intent,
    live_adapter_status_rows,
)
from alphadb.markets.spec import kxbtc15m_spec
from alphadb.paper.ioc import PaperExecutionRepository
from alphadb.state.repository import OperationalStateRepository


class FakeOrderClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def create_order(self, *, request_payload, settings):
        self.requests.append((dict(request_payload), settings.kalshi_api_key_id))
        return self.response


def live_order_repository_or_skip() -> OperationalStateRepository:
    repository = OperationalStateRepository(settings_from_env().database_url)
    try:
        with repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    repository.apply_migrations()
    return repository


def approved_intent(repository: OperationalStateRepository) -> str:
    return repository.create_tracer_run(
        kxbtc15m_spec(),
        now=datetime(2026, 5, 31, 21, 0, tzinfo=UTC),
    ).order_intent_id


def gated_settings():
    return settings_from_env(
        {
            "ALPHADB_RUNTIME_MODE": "gated-live",
            "ALPHADB_ENABLE_LIVE_ORDERS": "1",
            "ALPHADB_HUMAN_CUTOVER_APPROVED": "1",
            "KALSHI_API_KEY_ID": "key-id",
            "KALSHI_PRIVATE_KEY_PATH": "/tmp/key.pem",
        }
    )


def test_live_order_request_maps_order_intent_to_taker_ioc_semantics() -> None:
    repository = live_order_repository_or_skip()
    order_intent_id = approved_intent(repository)
    intent = PaperExecutionRepository(repository.database_url).get_approved_order_intent(order_intent_id)

    payload = kalshi_order_request_from_intent(intent)

    assert payload["ticker"] == intent.market_ticker
    assert payload["side"] == "bid"
    assert payload["count"] == "1.00"
    assert payload["price"] == "0.4900"
    assert payload["time_in_force"] == "immediate_or_cancel"
    assert payload["post_only"] is False
    assert payload["self_trade_prevention_type"] == "taker_at_cross"


def test_live_order_adapter_denies_paper_mode_and_missing_credentials() -> None:
    repository = live_order_repository_or_skip()
    order_intent_id = approved_intent(repository)
    adapter = GatedLiveKalshiOrderAdapter(database_url=repository.database_url, client=FakeOrderClient({}))

    with pytest.raises(LiveOrderError, match="paper_mode_disables_live_orders"):
        adapter.submit_order_intent(
            order_intent_id=order_intent_id,
            settings=settings_from_env({"ALPHADB_RUNTIME_MODE": "paper"}),
        )
    with pytest.raises(LiveOrderError, match="missing_kalshi_credentials"):
        adapter.submit_order_intent(
            order_intent_id=order_intent_id,
            settings=settings_from_env(
                {
                    "ALPHADB_RUNTIME_MODE": "gated-live",
                    "ALPHADB_ENABLE_LIVE_ORDERS": "1",
                }
            ),
        )

    with repository.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select status
                from live_order_attempts
                where order_intent_id = %s
                """,
                (order_intent_id,),
            )
            statuses = {str(row["status"]) for row in cursor.fetchall()}
    assert statuses == {"guard_denied"}


def test_live_order_adapter_records_exchange_success_and_rejection_without_exposing_secrets() -> None:
    repository = live_order_repository_or_skip()
    submitted_intent = approved_intent(repository)
    rejected_intent = approved_intent(repository)
    submitted_client = FakeOrderClient({"order": {"status": "accepted", "order_id": "abc"}})
    rejected_client = FakeOrderClient({"order": {"status": "rejected", "reason": "bad_price"}})

    submitted = GatedLiveKalshiOrderAdapter(
        database_url=repository.database_url,
        client=submitted_client,
    ).submit_order_intent(order_intent_id=submitted_intent, settings=gated_settings())
    rejected = GatedLiveKalshiOrderAdapter(
        database_url=repository.database_url,
        client=rejected_client,
    ).submit_order_intent(order_intent_id=rejected_intent, settings=gated_settings())
    rows = live_adapter_status_rows(gated_settings())

    assert submitted.status == "submitted"
    assert rejected.status == "rejected"
    assert submitted_client.requests[0][1] == "key-id"
    assert not any("key-id" in str(row) for row in rows)


def test_filled_max_cost_counts_ioc_fills_not_submitted_notional() -> None:
    repository = live_order_repository_or_skip()
    unique_day = uuid4()
    trading_day = date(
        2031 + unique_day.bytes[0] % 60,
        1 + unique_day.bytes[1] % 12,
        1 + unique_day.bytes[2] % 28,
    )
    created_at = datetime(
        trading_day.year,
        trading_day.month,
        trading_day.day,
        12,
        0,
        tzinfo=UTC,
    )
    full_fill_intent = approved_intent(repository)
    no_fill_intent = approved_intent(repository)
    partial_fill_intent = approved_intent(repository)
    intents = (full_fill_intent, no_fill_intent, partial_fill_intent)

    full_fill = GatedLiveKalshiOrderAdapter(
        database_url=repository.database_url,
        client=FakeOrderClient(
            {
                "order_id": "full",
                "fill_count": "1.00",
                "remaining_count": "0.00",
            }
        ),
    ).submit_order_intent(order_intent_id=full_fill_intent, settings=gated_settings())
    no_fill = GatedLiveKalshiOrderAdapter(
        database_url=repository.database_url,
        client=FakeOrderClient(
            {
                "order_id": "none",
                "fill_count": "0.00",
                "remaining_count": "0.00",
            }
        ),
    ).submit_order_intent(order_intent_id=no_fill_intent, settings=gated_settings())
    partial_fill = GatedLiveKalshiOrderAdapter(
        database_url=repository.database_url,
        client=FakeOrderClient(
            {
                "order_id": "partial",
                "fill_count": "0.50",
                "remaining_count": "0.50",
            }
        ),
    ).submit_order_intent(order_intent_id=partial_fill_intent, settings=gated_settings())

    with repository.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update order_intents
                set max_cost_dollars = 0.49
                where order_intent_id in (%s, %s, %s)
                """,
                intents,
            )
            cursor.execute(
                """
                update live_order_attempts
                set created_at = %s
                where live_order_attempt_id in (%s, %s, %s)
                """,
                (
                    created_at,
                    full_fill.live_order_attempt_id,
                    no_fill.live_order_attempt_id,
                    partial_fill.live_order_attempt_id,
                ),
            )
        connection.commit()

    live_orders = LiveOrderRepository(repository.database_url)

    assert live_orders.submitted_max_cost_dollars(trading_day=trading_day) == pytest.approx(1.47)
    assert live_orders.filled_max_cost_dollars(trading_day=trading_day) == pytest.approx(0.735)


def test_top_level_order_id_response_counts_as_accepted_ioc_attempt() -> None:
    assert exchange_response_accepted(
        {
            "client_order_id": "intent_123",
            "fill_count": "0.00",
            "order_id": "order_123",
            "remaining_count": "0.00",
            "ts_ms": 1780292536260,
        }
    )


def test_live_order_repository_updates_exchange_response_evidence() -> None:
    repository = live_order_repository_or_skip()
    live_orders = LiveOrderRepository(repository.database_url)
    risk_day = date(2026, 6, 4)
    base_time = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)

    accepted = live_orders.persist(
        live_attempt(
            "accepted",
            risk_day=risk_day,
            submitted_at=base_time,
        )
    )
    rejected = live_orders.persist(
        live_attempt(
            "rejected",
            risk_day=risk_day,
            submitted_at=base_time,
        )
    )
    no_fill = live_orders.persist(
        live_attempt(
            "no_fill",
            risk_day=risk_day,
            submitted_at=base_time,
        )
    )
    partial = live_orders.persist(
        live_attempt(
            "partial",
            risk_day=risk_day,
            submitted_at=base_time,
        )
    )

    accepted_row = live_orders.record_submit_response(
        live_order_attempt_id=accepted.live_order_attempt_id,
        response_payload={"order": {"status": "accepted", "order_id": "ord_accepted"}, "fill_count": "1.00"},
        accepted=True,
        observed_at=base_time,
    )
    rejected_row = live_orders.record_submit_response(
        live_order_attempt_id=rejected.live_order_attempt_id,
        response_payload={"order": {"status": "rejected", "order_id": "ord_rejected"}},
        accepted=False,
        observed_at=base_time,
    )
    no_fill_row = live_orders.record_submit_response(
        live_order_attempt_id=no_fill.live_order_attempt_id,
        response_payload={"order_id": "ord_none", "fill_count": "0.00", "remaining_count": "0.00"},
        accepted=True,
        observed_at=base_time,
    )
    partial_row = live_orders.record_submit_response(
        live_order_attempt_id=partial.live_order_attempt_id,
        response_payload={
            "order_id": "ord_partial",
            "fill_count": "0.50",
            "remaining_count": "0.50",
        },
        accepted=True,
        observed_at=base_time,
    )

    assert accepted_row["status"] == "accepted"
    assert accepted_row["exchange_order_id"] == "ord_accepted"
    assert accepted_row["exchange_status"] == "accepted"
    assert accepted_row["fill_count"] == 1.0
    assert rejected_row["status"] == "rejected"
    assert rejected_row["exchange_status"] == "rejected"
    assert no_fill_row["status"] == "accepted"
    assert no_fill_row["fill_count"] == 0.0
    assert no_fill_row["remaining_count"] == 0.0
    assert partial_row["fill_count"] == 0.5
    assert partial_row["remaining_count"] == 0.5


def test_live_order_repository_records_safe_submit_error_metadata() -> None:
    class FakeHttpError(RuntimeError):
        code = 409
        body = '{"message":"conflict","api_key":"secret-value"}'

    repository = live_order_repository_or_skip()
    live_orders = LiveOrderRepository(repository.database_url)
    risk_day = date(2026, 6, 4)
    submitted_at = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    attempt = live_orders.persist(
        live_attempt("http_error", risk_day=risk_day, submitted_at=submitted_at)
    )

    row = live_orders.record_submit_error(
        live_order_attempt_id=attempt.live_order_attempt_id,
        exc=FakeHttpError("HTTP 409 conflict"),
        observed_at=submitted_at,
    )

    assert row["status"] == "submit_error"
    assert row["exchange_http_status"] == 409
    assert row["exchange_error_class"] == "FakeHttpError"
    assert row["exchange_error_metadata"]["http_status"] == 409
    assert row["exchange_error_metadata"]["body"]["message"] == "conflict"
    assert row["exchange_error_metadata"]["body"]["api_key"] == "[redacted]"


def live_attempt(
    suffix: str,
    *,
    risk_day: date,
    submitted_at: datetime,
) -> LiveOrderAttempt:
    return LiveOrderAttempt(
        live_order_attempt_id=f"live_order_{suffix}_{uuid4().hex[:8]}",
        order_intent_id=None,
        risk_decision_id=None,
        strategy="test_strategy",
        live_risk_day=risk_day,
        reservation_id=f"res_{suffix}",
        market_ticker=f"KXBTC15M-{suffix.upper()}",
        client_order_id=f"client_{suffix}_{uuid4().hex[:8]}",
        intended_side="yes",
        intended_price_dollars=0.4,
        intended_quantity=1.0,
        intended_max_loss_dollars=0.41,
        runtime_mode="gated-live",
        status="submit_pending",
        guard_reason=None,
        request_payload={"client_order_id": f"client_{suffix}"},
        submitted_at=submitted_at,
    )
