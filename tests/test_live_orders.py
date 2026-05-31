from datetime import UTC, datetime

import psycopg
import pytest

from alphadb.config import settings_from_env
from alphadb.live_orders import (
    GatedLiveKalshiOrderAdapter,
    LiveOrderError,
    LiveOrderRepository,
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

    recent = LiveOrderRepository(repository.database_url).recent(limit=2)
    assert {row["status"] for row in recent} == {"guard_denied"}


def test_live_order_adapter_records_exchange_success_and_rejection_without_exposing_secrets() -> None:
    repository = live_order_repository_or_skip()
    accepted_intent = approved_intent(repository)
    rejected_intent = approved_intent(repository)
    accepted_client = FakeOrderClient({"order": {"status": "accepted", "order_id": "abc"}})
    rejected_client = FakeOrderClient({"order": {"status": "rejected", "reason": "bad_price"}})

    accepted = GatedLiveKalshiOrderAdapter(
        database_url=repository.database_url,
        client=accepted_client,
    ).submit_order_intent(order_intent_id=accepted_intent, settings=gated_settings())
    rejected = GatedLiveKalshiOrderAdapter(
        database_url=repository.database_url,
        client=rejected_client,
    ).submit_order_intent(order_intent_id=rejected_intent, settings=gated_settings())
    rows = live_adapter_status_rows(gated_settings())

    assert accepted.status == "accepted"
    assert rejected.status == "rejected"
    assert accepted_client.requests[0][1] == "key-id"
    assert not any("key-id" in str(row) for row in rows)
