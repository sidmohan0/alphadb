from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest

from alphadb.collectors.brti import (
    BRTI_FORWARD_CAPTURE_MANIFEST_SCHEMA,
    BRTI_INDEX_ID,
    BRTI_RAW_EVENT_SOURCE,
    BRTI_VALUE_SCHEMA_VERSION,
    BRTILatestContextRepository,
    BRTILiveCollector,
    BRTIValidationError,
    BRTIWebSocketFrame,
    build_brti_forward_capture_manifest,
    build_cfbenchmarks_subscribe_message,
    fixture_brti_frame,
    parse_cfbenchmarks_value_message,
)
from alphadb.config import settings_from_env
from alphadb.events.log import RawEventLog
from alphadb.state.repository import OperationalStateRepository


def brti_repository_or_skip() -> tuple[OperationalStateRepository, BRTILiveCollector]:
    repository = OperationalStateRepository(settings_from_env().database_url)
    try:
        with repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    repository.apply_migrations()
    return repository, BRTILiveCollector(database_url=repository.database_url)


def test_subscribe_message_targets_cfbenchmarks_value_index_ids() -> None:
    message = build_cfbenchmarks_subscribe_message(index_ids=("BRTI",), message_id=7)

    assert message == {
        "id": 7,
        "cmd": "subscribe",
        "params": {
            "channels": ["cfbenchmarks_value"],
            "index_ids": ["BRTI"],
        },
    }


def test_parse_valid_cfbenchmarks_value_message() -> None:
    received_at = datetime(2026, 6, 8, 17, 0, 2, tzinfo=UTC)
    source_timestamp = datetime(2026, 6, 8, 17, 0, 1, tzinfo=UTC)
    frame = fixture_brti_frame(
        source_timestamp=source_timestamp,
        received_at=received_at,
        value="68000.12",
    )

    observation = parse_cfbenchmarks_value_message(
        frame.message,
        received_at=frame.received_at,
    )

    assert observation.index_id == BRTI_INDEX_ID
    assert observation.value == Decimal("68000.12")
    assert observation.source_timestamp == source_timestamp
    assert observation.received_at == received_at
    assert observation.avg_60s is not None
    assert observation.avg_60s.window_size == 3
    assert observation.source_event_id.startswith("cfbenchmarks_value:BRTI:")


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda message: message["msg"].update({"index_id": "ETHUSD_RTI"}),
            "wrong_index",
        ),
        (
            lambda message: message["msg"].update({"data": "{not-json"}),
            "malformed_payload",
        ),
        (
            lambda message: message["msg"].update(
                {
                    "data": json.dumps(
                        {
                            "type": "value",
                            "id": "BRTI",
                            "time": message["msg"]["received_at"],
                            "value": "0",
                        }
                    )
                }
            ),
            "non_positive_value",
        ),
    ],
)
def test_parse_rejects_wrong_index_malformed_and_non_positive(
    mutate,
    reason: str,
) -> None:
    frame = fixture_brti_frame()
    message = dict(frame.message)
    message["msg"] = dict(frame.message["msg"])
    mutate(message)

    with pytest.raises(BRTIValidationError) as exc_info:
        parse_cfbenchmarks_value_message(message, received_at=frame.received_at)

    assert exc_info.value.reason == reason


def test_parse_rejects_future_source_timestamp() -> None:
    received_at = datetime(2026, 6, 8, 17, 0, tzinfo=UTC)
    frame = fixture_brti_frame(
        source_timestamp=received_at + timedelta(seconds=1),
        received_at=received_at,
    )

    with pytest.raises(BRTIValidationError) as exc_info:
        parse_cfbenchmarks_value_message(frame.message, received_at=frame.received_at)

    assert exc_info.value.reason == "future_source_timestamp"


def test_collector_writes_index_level_raw_event_and_latest_context() -> None:
    repository, collector = brti_repository_or_skip()
    received_at = datetime.now(UTC)
    frame = fixture_brti_frame(received_at=received_at)

    summary = collector.ingest_frames([frame])
    latest = BRTILatestContextRepository(repository.database_url).get_latest(
        now=received_at,
        freshness_limit=timedelta(seconds=5),
    )
    replayed = [
        row
        for row in RawEventLog(repository.database_url).replay_events()
        if row["source"] == BRTI_RAW_EVENT_SOURCE
        and row["source_event_id"] == latest.context.source_event_id
    ]

    assert summary.accepted == 1
    assert summary.rejected == 0
    assert summary.raw_events_inserted == 1
    assert summary.latest_context_updates == 1
    assert latest.is_usable is True
    assert latest.context is not None
    assert latest.context.index_id == BRTI_INDEX_ID
    assert latest.context.value == Decimal("68000.12")
    assert latest.context.source == BRTI_RAW_EVENT_SOURCE
    assert latest.context.schema_version == BRTI_VALUE_SCHEMA_VERSION
    assert len(replayed) == 1
    assert replayed[0]["market_ticker"] is None
    assert replayed[0]["raw_event_id"] == latest.context.raw_event_id


def test_collector_rejects_invalid_message_before_raw_persistence() -> None:
    repository, collector = brti_repository_or_skip()
    received_at = datetime.now(UTC)
    frame = fixture_brti_frame(received_at=received_at)
    message = dict(frame.message)
    message["msg"] = dict(frame.message["msg"])
    message["msg"]["index_id"] = "ETHUSD_RTI"

    summary = collector.ingest_frames([BRTIWebSocketFrame(message=message, received_at=received_at)])
    replayed = [
        row
        for row in RawEventLog(repository.database_url).replay_events()
        if row["source"] == BRTI_RAW_EVENT_SOURCE
        and row["payload"].get("index_id") == "ETHUSD_RTI"
    ]

    assert summary.accepted == 0
    assert summary.rejected == 1
    assert summary.rejections[0].reason == "wrong_index"
    assert replayed == []


def test_latest_context_reports_missing_and_stale() -> None:
    repository, collector = brti_repository_or_skip()
    latest_contexts = BRTILatestContextRepository(repository.database_url)
    unique_index = "BRTI_MISSING_TEST"

    missing = latest_contexts.get_latest(index_id=unique_index)

    assert missing.status == "missing"
    assert missing.reason == "missing_brti_latest_context"

    stale_index = f"BRTI_STALE_{uuid4().hex[:8]}"
    stale_collector = BRTILiveCollector(
        database_url=repository.database_url,
        index_id=stale_index,
    )
    received_at = datetime.now(UTC)
    frame = fixture_brti_frame(
        index_id=stale_index,
        source_timestamp=received_at - timedelta(seconds=1),
        received_at=received_at,
    )
    stale_collector.ingest_frames([frame])
    stale = latest_contexts.get_latest(
        index_id=stale_index,
        now=received_at + timedelta(seconds=10),
        freshness_limit=timedelta(seconds=5),
    )

    assert stale.status == "stale"
    assert stale.reason == "stale_brti_latest_context"


def test_latest_context_future_tolerance_is_opt_in() -> None:
    repository, _collector = brti_repository_or_skip()
    unique_index = f"BRTI_FUTURE_TOL_{uuid4().hex[:8]}"
    collector = BRTILiveCollector(
        database_url=repository.database_url,
        index_id=unique_index,
    )
    latest_contexts = BRTILatestContextRepository(repository.database_url)
    decision_time = datetime.now(UTC)
    frame = fixture_brti_frame(
        index_id=unique_index,
        source_timestamp=decision_time + timedelta(milliseconds=500),
        received_at=decision_time + timedelta(milliseconds=600),
    )
    collector.ingest_frames([frame])

    strict = latest_contexts.get_latest(
        index_id=unique_index,
        now=decision_time,
    )
    tolerated = latest_contexts.get_latest(
        index_id=unique_index,
        now=decision_time,
        future_tolerance=timedelta(seconds=2),
    )

    assert strict.status == "unusable"
    assert strict.reason == "future_brti_latest_context"
    assert tolerated.status == "usable"
    assert tolerated.reason is None
    assert tolerated.age_ms is not None
    assert tolerated.age_ms < 0


def test_older_observation_does_not_replace_newer_latest_context() -> None:
    repository, _collector = brti_repository_or_skip()
    unique_index = f"BRTI_ORDER_{uuid4().hex[:8]}"
    collector = BRTILiveCollector(
        database_url=repository.database_url,
        index_id=unique_index,
    )
    latest_contexts = BRTILatestContextRepository(repository.database_url)
    base = datetime.now(UTC) - timedelta(seconds=2)
    newer = fixture_brti_frame(
        index_id=unique_index,
        source_timestamp=base,
        received_at=base + timedelta(milliseconds=500),
        value="68001.00",
    )
    older = fixture_brti_frame(
        index_id=unique_index,
        source_timestamp=base - timedelta(seconds=1),
        received_at=base + timedelta(seconds=1),
        value="67999.00",
    )

    first = collector.ingest_frames([newer])
    second = collector.ingest_frames([older])
    latest = latest_contexts.get_latest(
        index_id=unique_index,
        now=base + timedelta(seconds=1),
    )

    assert first.latest_context_updates == 1
    assert second.latest_context_updates == 0
    assert second.stale_latest_drops == 1
    assert latest.context is not None
    assert latest.context.value == Decimal("68001.00")


def test_forward_capture_manifest_summarizes_metadata_without_raw_ticks() -> None:
    repository, _collector = brti_repository_or_skip()
    index_id = f"BRTI_MANIFEST_{uuid4().hex[:8]}"
    collector = BRTILiveCollector(database_url=repository.database_url, index_id=index_id)
    start = datetime(2035, 1, 1, 0, 0, tzinfo=UTC)
    frames = [
        fixture_brti_frame(
            index_id=index_id,
            source_timestamp=start + timedelta(seconds=1),
            received_at=start + timedelta(seconds=1, milliseconds=200),
            value="68000.12",
        ),
        fixture_brti_frame(
            index_id=index_id,
            source_timestamp=start + timedelta(seconds=2),
            received_at=start + timedelta(seconds=2, milliseconds=200),
            value="68001.12",
        ),
        fixture_brti_frame(
            index_id=index_id,
            source_timestamp=start + timedelta(seconds=6),
            received_at=start + timedelta(seconds=6, milliseconds=200),
            value="68002.12",
        ),
    ]

    collector.ingest_frames(frames)
    manifest = build_brti_forward_capture_manifest(
        database_url=repository.database_url,
        index_id=index_id,
        window_start=start,
        window_end=start + timedelta(seconds=10),
        generated_at=start + timedelta(seconds=7),
        gap_threshold_seconds=2.0,
        private_artifact_refs={"raw_capture": "s3://private/brti/capture.ndjson"},
    )
    encoded = json.dumps(manifest, sort_keys=True)

    assert manifest["schema_version"] == BRTI_FORWARD_CAPTURE_MANIFEST_SCHEMA
    assert manifest["source_identity"]["index_id"] == index_id
    assert manifest["coverage"]["observation_count"] == 3
    assert manifest["coverage"]["gap_count"] == 1
    assert manifest["coverage"]["max_gap_seconds"] == 4.0
    assert manifest["provenance"]["payload_hash_rollup_sha256"] is not None
    assert manifest["public_safety"]["raw_brti_ticks_included"] is False
    assert manifest["evaluation_boundary"]["historical_brti_backfill_assumed"] is False
    assert "forward-captured BRTI data after collector launch" in (
        manifest["evaluation_boundary"]["first_serious_evaluation_target"]
    )
    assert "68000.12" not in encoded
    assert "68001.12" not in encoded
    assert "68002.12" not in encoded
