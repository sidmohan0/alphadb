from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest

from alphadb.collectors.kalshi_rest import (
    FixtureKalshiRestClient,
    RestKxbtc15mCollector,
    eligible_markets,
)
from alphadb.config import settings_from_env
from alphadb.events.log import RawEventLog
from alphadb.markets.spec import kxbtc15m_spec
from alphadb.state.repository import OperationalStateRepository


def collector_or_skip(
    client: FixtureKalshiRestClient,
) -> tuple[OperationalStateRepository, RestKxbtc15mCollector]:
    repository = OperationalStateRepository(settings_from_env().database_url)
    try:
        with repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    repository.apply_migrations()
    return repository, RestKxbtc15mCollector(
        database_url=repository.database_url,
        client=client,
        source_mode="fixture",
    )


def test_collector_discovers_kxbtc15m_through_registry_and_logs_snapshots() -> None:
    client = FixtureKalshiRestClient()
    repository, collector = collector_or_skip(client)

    summary = collector.collect(
        series="KXBTC15M",
        max_markets=1,
        now=datetime(2026, 5, 31, 21, 12, tzinfo=UTC),
    )
    replayed = list(RawEventLog(repository.database_url).replay_events(run_id=summary.platform_run_id))

    assert client.list_market_calls == [
        {"series_ticker": "KXBTC15M", "status": "open", "limit": 1}
    ]
    assert client.orderbook_calls == ["KXBTC15M-26MAY312100-00"]
    assert summary.status == "completed"
    assert summary.market_tickers == ("KXBTC15M-26MAY312100-00",)
    assert summary.markets_discovered == 1
    assert summary.markets_collected == 1
    assert summary.raw_events_written == 2
    assert summary.orders_placed == 0
    assert {row["schema_version"] for row in replayed} == {
        "kalshi.market_snapshot.v1",
        "kalshi.orderbook_snapshot.v1",
    }
    assert all(row["source"] == "kalshi_rest" for row in replayed)


def test_collector_persists_status_and_recent_errors() -> None:
    class MissingOrderbookClient(FixtureKalshiRestClient):
        def get_orderbook(self, market_ticker: str) -> Mapping[str, Any]:
            raise RuntimeError(f"orderbook unavailable: {market_ticker}")

    _repository, collector = collector_or_skip(MissingOrderbookClient())

    summary = collector.collect(
        series="KXBTC15M",
        max_markets=1,
        now=datetime(2026, 5, 31, 21, 12, tzinfo=UTC),
    )
    recent_runs = collector.run_store.recent_runs(limit=25)
    current_run = next(
        row for row in recent_runs if row["collector_run_id"] == summary.collector_run_id
    )

    assert summary.status == "completed_with_errors"
    assert summary.markets_collected == 1
    assert summary.raw_events_written == 1
    assert summary.orders_placed == 0
    assert summary.errors[0].stage == "collect_market_snapshot"
    assert current_run["status"] == "completed_with_errors"
    assert current_run["errors"] == 1


def test_eligible_markets_are_filtered_by_marketspec_prefix() -> None:
    spec = kxbtc15m_spec()

    rows = eligible_markets(
        spec,
        [
            {"ticker": "KXBTC15M-26MAY312100-00"},
            {"ticker": "KXETH15M-26MAY312100-00"},
            {"ticker": ""},
        ],
    )

    assert rows == [{"ticker": "KXBTC15M-26MAY312100-00"}]
