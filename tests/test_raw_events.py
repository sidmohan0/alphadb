from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from alphadb.config import settings_from_env
from alphadb.events.log import RawEventLog, canonical_payload_hash
from alphadb.markets.spec import kxbtc15m_spec
from alphadb.state.repository import OperationalStateRepository


def event_log_or_skip() -> tuple[OperationalStateRepository, RawEventLog]:
    repository = OperationalStateRepository(settings_from_env().database_url)
    try:
        with repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    repository.apply_migrations()
    return repository, RawEventLog(repository.database_url)


def test_append_raw_event_records_hash_and_payload_metadata() -> None:
    repository, event_log = event_log_or_skip()
    tracer = repository.create_tracer_run(kxbtc15m_spec())
    payload = {"bid": 49, "ask": 51, "ticker": tracer.market_ticker}

    record = event_log.append(
        run_id=tracer.run_id,
        market_ticker=tracer.market_ticker,
        source="kalshi_rest",
        source_event_id=f"{tracer.market_ticker}:snapshot:1",
        schema_version="kalshi.orderbook_snapshot.v1",
        received_at=datetime(2026, 5, 31, 20, 0, tzinfo=UTC),
        payload=payload,
    )
    replayed = list(event_log.replay_events(run_id=tracer.run_id))

    assert record.inserted is True
    assert record.payload_hash == canonical_payload_hash(payload)
    assert len(replayed) == 1
    assert replayed[0]["source"] == "kalshi_rest"
    assert replayed[0]["schema_version"] == "kalshi.orderbook_snapshot.v1"
    assert replayed[0]["payload_hash"] == record.payload_hash
    assert replayed[0]["payload"] == payload


def test_duplicate_source_event_id_is_idempotent() -> None:
    repository, event_log = event_log_or_skip()
    tracer = repository.create_tracer_run(kxbtc15m_spec())
    source_event_id = f"{tracer.market_ticker}:snapshot:duplicate"

    first = event_log.append(
        run_id=tracer.run_id,
        market_ticker=tracer.market_ticker,
        source="kalshi_rest",
        source_event_id=source_event_id,
        schema_version="kalshi.orderbook_snapshot.v1",
        payload={"sequence": 1},
    )
    second = event_log.append(
        run_id=tracer.run_id,
        market_ticker=tracer.market_ticker,
        source="kalshi_rest",
        source_event_id=source_event_id,
        schema_version="kalshi.orderbook_snapshot.v1",
        payload={"sequence": 1},
    )

    assert first.inserted is True
    assert second.inserted is False
    assert second.raw_event_id == first.raw_event_id
    assert len(list(event_log.replay_events(run_id=tracer.run_id))) == 1


def test_replay_reader_orders_events_deterministically_and_counts_by_source_schema() -> None:
    repository, event_log = event_log_or_skip()
    tracer = repository.create_tracer_run(kxbtc15m_spec())
    base_time = datetime(2026, 5, 31, 20, 0, tzinfo=UTC)

    later = event_log.append(
        run_id=tracer.run_id,
        market_ticker=tracer.market_ticker,
        source="coinbase",
        source_event_id=f"{tracer.market_ticker}:coinbase:2",
        schema_version="coinbase.candle.v1",
        received_at=base_time + timedelta(seconds=2),
        payload={"close": 100_001},
    )
    earlier = event_log.append(
        run_id=tracer.run_id,
        market_ticker=tracer.market_ticker,
        source="coinbase",
        source_event_id=f"{tracer.market_ticker}:coinbase:1",
        schema_version="coinbase.candle.v1",
        received_at=base_time,
        payload={"close": 100_000},
    )

    replayed_ids = [row["raw_event_id"] for row in event_log.replay_events(run_id=tracer.run_id)]
    assert replayed_ids == [earlier.raw_event_id, later.raw_event_id]

    count_rows = event_log.counts_by_source_schema()
    assert any(
        row["source"] == "coinbase"
        and row["schema_version"] == "coinbase.candle.v1"
        and row["events"] >= 2
        for row in count_rows
    )
