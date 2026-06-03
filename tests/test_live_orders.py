from datetime import UTC, date, datetime
from uuid import uuid4

import psycopg
import pytest

from alphadb.config import settings_from_env
from alphadb.live_orders import (
    GatedLiveKalshiOrderAdapter,
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
