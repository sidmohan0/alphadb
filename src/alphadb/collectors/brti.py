"""BRTI live market-context collector.

The collector records Kalshi `cfbenchmarks_value` ticks as index-level raw
events and maintains a compact latest-context projection for runtime consumers.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.collectors.kalshi_ws import (
    KalshiWebSocketCredentials,
    assert_live_smoke_enabled,
)
from alphadb.config import Settings, settings_from_env
from alphadb.events.log import RawEventLog, RawEventRecord
from alphadb.live_orders import load_private_key, sign_kalshi_request
from alphadb.state.repository import OperationalStateRepository

BRTI_INDEX_ID = "BRTI"
BRTI_RAW_EVENT_SOURCE = "kalshi_cfbenchmarks_value"
BRTI_VALUE_SCHEMA_VERSION = "kalshi.ws.cfbenchmarks_value.v1"
CFBENCHMARKS_VALUE_CHANNEL = "cfbenchmarks_value"
DEFAULT_BRTI_FRESHNESS_LIMIT_SECONDS = 5
DEFAULT_BRTI_GAP_THRESHOLD_SECONDS = 2.0
DEFAULT_KALSHI_WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
BRTI_FORWARD_CAPTURE_MANIFEST_SCHEMA = "brti.forward_capture_manifest.v1"


class BRTIValidationError(ValueError):
    """Raised when a BRTI feed message is not usable as latest context."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class WindowAverage:
    value: Decimal
    window_size: int
    window_start: datetime | None
    window_end_exclusive: datetime | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": str(self.value),
            "window_size": self.window_size,
            "window_start": _iso_or_none(self.window_start),
            "window_end_exclusive": _iso_or_none(self.window_end_exclusive),
        }


@dataclass(frozen=True)
class BRTIObservation:
    index_id: str
    value: Decimal
    source_timestamp: datetime
    source_timestamp_ms: int
    received_at: datetime
    raw_message: Mapping[str, Any]
    upstream_data: Mapping[str, Any]
    sid: int | None = None
    sequence: int | None = None
    upstream_received_at: datetime | None = None
    avg_60s: WindowAverage | None = None
    final_60s: WindowAverage | None = None

    @property
    def source_event_id(self) -> str:
        return f"{CFBENCHMARKS_VALUE_CHANNEL}:{self.index_id}:{self.source_timestamp_ms}"

    @property
    def source_lag_ms(self) -> int:
        return int((self.received_at - self.source_timestamp).total_seconds() * 1000)

    def raw_payload(self) -> dict[str, Any]:
        return {
            "channel": CFBENCHMARKS_VALUE_CHANNEL,
            "index_id": self.index_id,
            "sid": self.sid,
            "sequence": self.sequence,
            "source_timestamp": self.source_timestamp.isoformat(),
            "source_timestamp_ms": self.source_timestamp_ms,
            "upstream_received_at": _iso_or_none(self.upstream_received_at),
            "value": str(self.value),
            "avg_60s_data": self.avg_60s.as_dict() if self.avg_60s else None,
            "last_60s_windowed_average_15min": (
                self.final_60s.as_dict() if self.final_60s else None
            ),
            "raw_message": _json_safe(self.raw_message),
        }


@dataclass(frozen=True)
class BRTIWebSocketFrame:
    message: str | Mapping[str, Any]
    received_at: datetime


@dataclass(frozen=True)
class BRTIRejection:
    reason: str
    message: str
    received_at: datetime

    def as_dict(self) -> dict[str, str]:
        return {
            "reason": self.reason,
            "message": self.message,
            "received_at": self.received_at.isoformat(),
        }


@dataclass(frozen=True)
class BRTIIngestSummary:
    source: str
    index_id: str
    messages_seen: int
    control_messages_seen: int
    accepted: int
    rejected: int
    raw_events_inserted: int
    latest_context_updates: int
    stale_latest_drops: int
    rejections: tuple[BRTIRejection, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "index_id": self.index_id,
            "messages_seen": self.messages_seen,
            "control_messages_seen": self.control_messages_seen,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "raw_events_inserted": self.raw_events_inserted,
            "latest_context_updates": self.latest_context_updates,
            "stale_latest_drops": self.stale_latest_drops,
            "rejections": [rejection.as_dict() for rejection in self.rejections],
        }


@dataclass(frozen=True)
class BRTILatestContext:
    index_id: str
    value: Decimal
    source_timestamp: datetime
    source_timestamp_ms: int
    received_at: datetime
    source_lag_ms: int
    raw_event_id: str
    source_event_id: str
    payload_hash: str
    source: str
    schema_version: str
    source_sequence: int | None
    source_sid: int | None
    avg_60s_value: Decimal | None
    avg_60s_window_size: int | None
    avg_60s_window_start: datetime | None
    avg_60s_window_end_exclusive: datetime | None
    final_60s_value: Decimal | None
    final_60s_window_size: int | None
    final_60s_window_start: datetime | None
    final_60s_window_end_exclusive: datetime | None
    metadata: Mapping[str, Any]
    updated_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "index_id": self.index_id,
            "value": str(self.value),
            "source_timestamp": self.source_timestamp.isoformat(),
            "source_timestamp_ms": self.source_timestamp_ms,
            "received_at": self.received_at.isoformat(),
            "source_lag_ms": self.source_lag_ms,
            "raw_event_id": self.raw_event_id,
            "source_event_id": self.source_event_id,
            "payload_hash": self.payload_hash,
            "source": self.source,
            "schema_version": self.schema_version,
            "source_sequence": self.source_sequence,
            "source_sid": self.source_sid,
            "avg_60s_value": _decimal_or_none(self.avg_60s_value),
            "avg_60s_window_size": self.avg_60s_window_size,
            "avg_60s_window_start": _iso_or_none(self.avg_60s_window_start),
            "avg_60s_window_end_exclusive": _iso_or_none(
                self.avg_60s_window_end_exclusive
            ),
            "final_60s_value": _decimal_or_none(self.final_60s_value),
            "final_60s_window_size": self.final_60s_window_size,
            "final_60s_window_start": _iso_or_none(self.final_60s_window_start),
            "final_60s_window_end_exclusive": _iso_or_none(
                self.final_60s_window_end_exclusive
            ),
            "metadata": _json_safe(self.metadata),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class BRTILatestContextStatus:
    index_id: str
    status: str
    reason: str | None
    generated_at: datetime
    freshness_limit_ms: int
    age_ms: int | None
    context: BRTILatestContext | None

    @property
    def is_usable(self) -> bool:
        return self.status == "usable"

    def as_dict(self) -> dict[str, Any]:
        return {
            "index_id": self.index_id,
            "status": self.status,
            "reason": self.reason,
            "generated_at": self.generated_at.isoformat(),
            "freshness_limit_ms": self.freshness_limit_ms,
            "age_ms": self.age_ms,
            "context": self.context.as_dict() if self.context else None,
        }


class BRTILatestContextRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def upsert_observation(
        self,
        *,
        observation: BRTIObservation,
        raw_event: RawEventRecord,
    ) -> bool:
        metadata = {
            "channel": CFBENCHMARKS_VALUE_CHANNEL,
            "upstream_received_at": _iso_or_none(observation.upstream_received_at),
        }
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into brti_latest_contexts (
                        index_id,
                        value,
                        source_timestamp,
                        source_timestamp_ms,
                        received_at,
                        source_lag_ms,
                        raw_event_id,
                        source_event_id,
                        payload_hash,
                        source,
                        schema_version,
                        source_sequence,
                        source_sid,
                        avg_60s_value,
                        avg_60s_window_size,
                        avg_60s_window_start,
                        avg_60s_window_end_exclusive,
                        final_60s_value,
                        final_60s_window_size,
                        final_60s_window_start,
                        final_60s_window_end_exclusive,
                        metadata,
                        updated_at
                    )
                    values (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
                    )
                    on conflict (index_id) do update set
                        value = excluded.value,
                        source_timestamp = excluded.source_timestamp,
                        source_timestamp_ms = excluded.source_timestamp_ms,
                        received_at = excluded.received_at,
                        source_lag_ms = excluded.source_lag_ms,
                        raw_event_id = excluded.raw_event_id,
                        source_event_id = excluded.source_event_id,
                        payload_hash = excluded.payload_hash,
                        source = excluded.source,
                        schema_version = excluded.schema_version,
                        source_sequence = excluded.source_sequence,
                        source_sid = excluded.source_sid,
                        avg_60s_value = excluded.avg_60s_value,
                        avg_60s_window_size = excluded.avg_60s_window_size,
                        avg_60s_window_start = excluded.avg_60s_window_start,
                        avg_60s_window_end_exclusive = excluded.avg_60s_window_end_exclusive,
                        final_60s_value = excluded.final_60s_value,
                        final_60s_window_size = excluded.final_60s_window_size,
                        final_60s_window_start = excluded.final_60s_window_start,
                        final_60s_window_end_exclusive = excluded.final_60s_window_end_exclusive,
                        metadata = excluded.metadata,
                        updated_at = now()
                    where brti_latest_contexts.source_timestamp <= excluded.source_timestamp
                    returning index_id
                    """,
                    (
                        observation.index_id,
                        observation.value,
                        observation.source_timestamp,
                        observation.source_timestamp_ms,
                        observation.received_at,
                        observation.source_lag_ms,
                        raw_event.raw_event_id,
                        observation.source_event_id,
                        raw_event.payload_hash,
                        raw_event.source,
                        raw_event.schema_version,
                        observation.sequence,
                        observation.sid,
                        observation.avg_60s.value if observation.avg_60s else None,
                        observation.avg_60s.window_size if observation.avg_60s else None,
                        observation.avg_60s.window_start if observation.avg_60s else None,
                        (
                            observation.avg_60s.window_end_exclusive
                            if observation.avg_60s
                            else None
                        ),
                        observation.final_60s.value if observation.final_60s else None,
                        observation.final_60s.window_size if observation.final_60s else None,
                        observation.final_60s.window_start if observation.final_60s else None,
                        (
                            observation.final_60s.window_end_exclusive
                            if observation.final_60s
                            else None
                        ),
                        Jsonb(metadata),
                    ),
                )
                updated = cursor.fetchone() is not None
            connection.commit()
        return updated

    def get_latest(
        self,
        *,
        index_id: str = BRTI_INDEX_ID,
        now: datetime | None = None,
        freshness_limit: timedelta = timedelta(
            seconds=DEFAULT_BRTI_FRESHNESS_LIMIT_SECONDS
        ),
    ) -> BRTILatestContextStatus:
        generated_at = _ensure_utc(now or datetime.now(UTC))
        freshness_limit_ms = int(freshness_limit.total_seconds() * 1000)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        index_id,
                        value,
                        source_timestamp,
                        source_timestamp_ms,
                        received_at,
                        source_lag_ms,
                        raw_event_id,
                        source_event_id,
                        payload_hash,
                        source,
                        schema_version,
                        source_sequence,
                        source_sid,
                        avg_60s_value,
                        avg_60s_window_size,
                        avg_60s_window_start,
                        avg_60s_window_end_exclusive,
                        final_60s_value,
                        final_60s_window_size,
                        final_60s_window_start,
                        final_60s_window_end_exclusive,
                        metadata,
                        updated_at
                    from brti_latest_contexts
                    where index_id = %s
                    """,
                    (index_id,),
                )
                row = cursor.fetchone()

        if row is None:
            return BRTILatestContextStatus(
                index_id=index_id,
                status="missing",
                reason="missing_brti_latest_context",
                generated_at=generated_at,
                freshness_limit_ms=freshness_limit_ms,
                age_ms=None,
                context=None,
            )

        context = _latest_context_from_row(row)
        age_ms = int((generated_at - context.source_timestamp).total_seconds() * 1000)
        if age_ms < 0:
            status = "unusable"
            reason = "future_brti_latest_context"
        elif age_ms > freshness_limit_ms:
            status = "stale"
            reason = "stale_brti_latest_context"
        else:
            status = "usable"
            reason = None
        return BRTILatestContextStatus(
            index_id=index_id,
            status=status,
            reason=reason,
            generated_at=generated_at,
            freshness_limit_ms=freshness_limit_ms,
            age_ms=age_ms,
            context=context,
        )


class BRTILiveCollector:
    def __init__(
        self,
        *,
        database_url: str,
        index_id: str = BRTI_INDEX_ID,
    ):
        self.database_url = database_url
        self.index_id = index_id
        self.event_log = RawEventLog(database_url)
        self.latest_contexts = BRTILatestContextRepository(database_url)

    def ingest_frames(self, frames: Iterable[BRTIWebSocketFrame]) -> BRTIIngestSummary:
        OperationalStateRepository(self.database_url).apply_migrations()
        messages_seen = 0
        control_messages_seen = 0
        accepted = 0
        raw_events_inserted = 0
        latest_context_updates = 0
        stale_latest_drops = 0
        rejections: list[BRTIRejection] = []

        for frame in frames:
            messages_seen += 1
            received_at = _ensure_utc(frame.received_at)
            try:
                message = decode_websocket_message(frame.message)
            except BRTIValidationError as exc:
                rejections.append(
                    BRTIRejection(reason=exc.reason, message=str(exc), received_at=received_at)
                )
                continue

            if message.get("type") != CFBENCHMARKS_VALUE_CHANNEL:
                control_messages_seen += 1
                continue

            try:
                observation = parse_cfbenchmarks_value_message(
                    message,
                    received_at=received_at,
                    expected_index_id=self.index_id,
                )
            except BRTIValidationError as exc:
                rejections.append(
                    BRTIRejection(reason=exc.reason, message=str(exc), received_at=received_at)
                )
                continue

            raw_event = self.event_log.append(
                market_ticker=None,
                source=BRTI_RAW_EVENT_SOURCE,
                source_event_id=observation.source_event_id,
                received_at=observation.received_at,
                source_timestamp=observation.source_timestamp,
                schema_version=BRTI_VALUE_SCHEMA_VERSION,
                payload=observation.raw_payload(),
            )
            accepted += 1
            raw_events_inserted += int(raw_event.inserted)
            latest_updated = self.latest_contexts.upsert_observation(
                observation=observation,
                raw_event=raw_event,
            )
            latest_context_updates += int(latest_updated)
            stale_latest_drops += int(not latest_updated)

        return BRTIIngestSummary(
            source=BRTI_RAW_EVENT_SOURCE,
            index_id=self.index_id,
            messages_seen=messages_seen,
            control_messages_seen=control_messages_seen,
            accepted=accepted,
            rejected=len(rejections),
            raw_events_inserted=raw_events_inserted,
            latest_context_updates=latest_context_updates,
            stale_latest_drops=stale_latest_drops,
            rejections=tuple(rejections),
        )


def build_cfbenchmarks_subscribe_message(
    *,
    index_ids: Sequence[str] = (BRTI_INDEX_ID,),
    message_id: int = 1,
) -> dict[str, Any]:
    return {
        "id": message_id,
        "cmd": "subscribe",
        "params": {
            "channels": [CFBENCHMARKS_VALUE_CHANNEL],
            "index_ids": list(index_ids),
        },
    }


def decode_websocket_message(message: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(message, str):
        try:
            decoded = json.loads(message)
        except json.JSONDecodeError as exc:
            raise BRTIValidationError("malformed_json", "WebSocket message is not JSON") from exc
    elif isinstance(message, Mapping):
        decoded = message
    else:
        raise BRTIValidationError(
            "malformed_message",
            f"WebSocket message must be an object or JSON string: {type(message).__name__}",
        )
    if not isinstance(decoded, Mapping):
        raise BRTIValidationError("malformed_message", "WebSocket message is not an object")
    return decoded


def parse_cfbenchmarks_value_message(
    message: Mapping[str, Any],
    *,
    received_at: datetime,
    expected_index_id: str = BRTI_INDEX_ID,
) -> BRTIObservation:
    received_at = _ensure_utc(received_at)
    if message.get("type") != CFBENCHMARKS_VALUE_CHANNEL:
        raise BRTIValidationError(
            "unsupported_message_type",
            f"unsupported WebSocket message type: {message.get('type')!r}",
        )

    msg = message.get("msg")
    if not isinstance(msg, Mapping):
        raise BRTIValidationError("malformed_payload", "cfbenchmarks_value msg is missing")

    upstream_data = _parse_upstream_data(msg.get("data"))
    data_type = upstream_data.get("type")
    if data_type != "value":
        raise BRTIValidationError(
            "malformed_payload",
            f"cfbenchmarks_value data.type is not value: {data_type!r}",
        )

    index_id = _required_str(msg, "index_id")
    if index_id != expected_index_id:
        raise BRTIValidationError(
            "wrong_index",
            f"expected index_id {expected_index_id}, got {index_id}",
        )

    data_index_id = _required_str(upstream_data, "id")
    if data_index_id != index_id:
        raise BRTIValidationError(
            "malformed_payload",
            f"data.id {data_index_id} does not match msg.index_id {index_id}",
        )

    value = _required_decimal(upstream_data, "value")
    if value <= 0:
        raise BRTIValidationError(
            "non_positive_value",
            f"BRTI value must be positive, got {value}",
        )

    source_timestamp_ms = _required_int(upstream_data, "time")
    source_timestamp = _datetime_from_ms(source_timestamp_ms)
    if source_timestamp > received_at:
        raise BRTIValidationError(
            "future_source_timestamp",
            "BRTI source timestamp is after the local receive timestamp",
        )

    return BRTIObservation(
        index_id=index_id,
        value=value,
        source_timestamp=source_timestamp,
        source_timestamp_ms=source_timestamp_ms,
        received_at=received_at,
        raw_message=message,
        upstream_data=upstream_data,
        sid=_optional_int(message.get("sid")),
        sequence=_optional_int(message.get("seq")),
        upstream_received_at=_optional_ms_datetime(msg.get("received_at")),
        avg_60s=_parse_window_average(msg.get("avg_60s_data"), "avg_60s_data"),
        final_60s=_parse_window_average(
            msg.get("last_60s_windowed_average_15min"),
            "last_60s_windowed_average_15min",
        ),
    )


async def run_live_collector(
    *,
    settings: Settings,
    database_url: str,
    index_id: str = BRTI_INDEX_ID,
    max_messages: int | None = None,
    max_reconnects: int = 3,
) -> BRTIIngestSummary:
    credentials = assert_live_smoke_enabled(settings)
    websocket_url = credentials.websocket_url or DEFAULT_KALSHI_WS_URL
    collector = BRTILiveCollector(database_url=database_url, index_id=index_id)
    aggregate = _MutableIngestAggregate(index_id=index_id)
    attempts = 0

    while True:
        try:
            partial = await _collect_live_once(
                credentials=credentials,
                websocket_url=websocket_url,
                collector=collector,
                index_id=index_id,
                max_messages=None if max_messages is None else max_messages - aggregate.accepted,
            )
            aggregate.add(partial)
            if max_messages is not None and aggregate.accepted >= max_messages:
                return aggregate.summary()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            attempts += 1
            aggregate.rejections.append(
                BRTIRejection(
                    reason="websocket_connection_error",
                    message=str(exc),
                    received_at=datetime.now(UTC),
                )
            )
            if attempts > max_reconnects:
                return aggregate.summary()
            await asyncio.sleep(min(2**attempts, 30))


async def _collect_live_once(
    *,
    credentials: KalshiWebSocketCredentials,
    websocket_url: str,
    collector: BRTILiveCollector,
    index_id: str,
    max_messages: int | None,
) -> BRTIIngestSummary:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("live BRTI collection requires the websockets package") from exc

    headers = signed_kalshi_ws_headers(credentials=credentials, websocket_url=websocket_url)
    subscribe = build_cfbenchmarks_subscribe_message(index_ids=(index_id,))
    aggregate = _MutableIngestAggregate(index_id=index_id)

    async with websockets.connect(websocket_url, additional_headers=headers) as websocket:
        await websocket.send(json.dumps(subscribe))
        async for message in websocket:
            frame = BRTIWebSocketFrame(message=message, received_at=datetime.now(UTC))
            summary = collector.ingest_frames([frame])
            aggregate.add(summary)
            if max_messages is not None and aggregate.accepted >= max_messages:
                break

    return aggregate.summary()


def signed_kalshi_ws_headers(
    *,
    credentials: KalshiWebSocketCredentials,
    websocket_url: str,
) -> dict[str, str]:
    timestamp_ms = str(int(time.time() * 1000))
    path = urlparse(websocket_url).path or "/trade-api/ws/v2"
    signature = sign_kalshi_request(
        private_key=load_private_key(credentials.private_key_path),
        timestamp_ms=timestamp_ms,
        method="GET",
        path=path,
    )
    return {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": credentials.api_key_id,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": signature,
    }


def fixture_brti_frame(
    *,
    index_id: str = BRTI_INDEX_ID,
    source_timestamp: datetime | None = None,
    received_at: datetime | None = None,
    value: str = "68000.12",
) -> BRTIWebSocketFrame:
    receive_time = _ensure_utc(received_at or datetime.now(UTC))
    source_time = _ensure_utc(source_timestamp or (receive_time - timedelta(seconds=1)))
    source_ms = _datetime_to_ms(source_time)
    message = {
        "type": CFBENCHMARKS_VALUE_CHANNEL,
        "sid": 1,
        "seq": source_ms % 1_000_000,
        "msg": {
            "index_id": index_id,
            "received_at": source_ms,
            "data": json.dumps(
                {
                    "type": "value",
                    "id": index_id,
                    "time": source_ms,
                    "value": value,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            "avg_60s_data": {
                "value": f"{Decimal(value):.8f}",
                "window_size": 3,
                "window_start_ts_ms": source_ms - 60_000,
                "window_end_ts_exclusive": source_ms,
            },
        },
    }
    return BRTIWebSocketFrame(message=message, received_at=receive_time)


def build_brti_forward_capture_manifest(
    *,
    database_url: str,
    window_start: datetime,
    window_end: datetime,
    index_id: str = BRTI_INDEX_ID,
    generated_at: datetime | None = None,
    freshness_limit_seconds: float = DEFAULT_BRTI_FRESHNESS_LIMIT_SECONDS,
    gap_threshold_seconds: float = DEFAULT_BRTI_GAP_THRESHOLD_SECONDS,
    code_version: str | None = None,
    config_version: str | None = None,
    private_artifact_refs: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    start = _ensure_utc(window_start)
    end = _ensure_utc(window_end)
    if end <= start:
        raise ValueError("window_end must be after window_start")
    generated = _ensure_utc(generated_at or datetime.now(UTC))
    OperationalStateRepository(database_url).apply_migrations()
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                    raw_event_id,
                    source_event_id,
                    received_at,
                    source_timestamp,
                    schema_version,
                    payload_hash
                from raw_events
                where source = %s
                  and source_timestamp >= %s
                  and source_timestamp < %s
                  and payload->>'index_id' = %s
                order by source_timestamp asc, received_at asc, raw_event_id asc
                """,
                (BRTI_RAW_EVENT_SOURCE, start, end, index_id),
            )
            rows = cursor.fetchall()

    source_times = [_ensure_utc(row["source_timestamp"]) for row in rows]
    received_times = [_ensure_utc(row["received_at"]) for row in rows]
    gaps = [
        {
            "from_source_timestamp": before.isoformat(),
            "to_source_timestamp": after.isoformat(),
            "gap_seconds": round((after - before).total_seconds(), 6),
        }
        for before, after in zip(source_times, source_times[1:])
        if (after - before).total_seconds() > gap_threshold_seconds
    ]
    all_gap_seconds = [
        (after - before).total_seconds()
        for before, after in zip(source_times, source_times[1:])
    ]
    payload_hash_rollup = _payload_hash_rollup(
        [str(row["payload_hash"]) for row in rows]
    )
    latest_source_timestamp = source_times[-1] if source_times else None
    latest_age_seconds = (
        max(0.0, (generated - latest_source_timestamp).total_seconds())
        if latest_source_timestamp is not None
        else None
    )
    return {
        "schema_version": BRTI_FORWARD_CAPTURE_MANIFEST_SCHEMA,
        "generated_at": generated.isoformat(),
        "source_identity": {
            "source": BRTI_RAW_EVENT_SOURCE,
            "channel": CFBENCHMARKS_VALUE_CHANNEL,
            "index_id": index_id,
            "schema_versions": sorted({str(row["schema_version"]) for row in rows}),
        },
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "bounded": True,
            "query_semantics": "source_timestamp >= start and source_timestamp < end",
        },
        "coverage": {
            "observation_count": len(rows),
            "raw_event_count": len(rows),
            "unique_source_event_count": len(
                {str(row["source_event_id"]) for row in rows if row["source_event_id"]}
            ),
            "first_source_timestamp": source_times[0].isoformat()
            if source_times
            else None,
            "last_source_timestamp": latest_source_timestamp.isoformat()
            if latest_source_timestamp
            else None,
            "first_received_at": received_times[0].isoformat()
            if received_times
            else None,
            "last_received_at": received_times[-1].isoformat()
            if received_times
            else None,
            "gap_threshold_seconds": gap_threshold_seconds,
            "gap_count": len(gaps),
            "max_gap_seconds": round(max(all_gap_seconds), 6)
            if all_gap_seconds
            else None,
            "gaps_over_threshold": gaps,
            "staleness": {
                "freshness_limit_seconds": freshness_limit_seconds,
                "latest_age_seconds_at_generation": round(latest_age_seconds, 6)
                if latest_age_seconds is not None
                else None,
                "latest_context_would_be_stale": (
                    latest_age_seconds > freshness_limit_seconds
                    if latest_age_seconds is not None
                    else None
                ),
            },
        },
        "provenance": {
            "payload_hash_rollup_sha256": payload_hash_rollup,
            "raw_event_id_first": str(rows[0]["raw_event_id"]) if rows else None,
            "raw_event_id_last": str(rows[-1]["raw_event_id"]) if rows else None,
            "code_version": code_version,
            "config_version": config_version,
            "private_artifact_refs": dict(private_artifact_refs or {}),
        },
        "public_safety": {
            "raw_brti_ticks_included": False,
            "production_logs_included": False,
            "live_account_order_fill_artifacts_included": False,
            "private_generated_datasets_included": False,
            "proprietary_thresholds_included": False,
        },
        "evaluation_boundary": {
            "historical_brti_backfill_assumed": False,
            "first_serious_evaluation_target": (
                "forward-captured BRTI data after collector launch"
            ),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-brti")
    subparsers = parser.add_subparsers(dest="command", required=True)

    mock_parser = subparsers.add_parser(
        "mock-smoke",
        help="Ingest one deterministic BRTI cfbenchmarks_value frame",
    )
    mock_parser.add_argument("--value", default="68000.12")

    status_parser = subparsers.add_parser("status", help="Show BRTI latest-context status")
    status_parser.add_argument("--index-id", default=BRTI_INDEX_ID)
    status_parser.add_argument(
        "--freshness-seconds",
        type=float,
        default=DEFAULT_BRTI_FRESHNESS_LIMIT_SECONDS,
    )

    live_parser = subparsers.add_parser(
        "live-collect",
        help="Run the credential-gated live BRTI collector",
    )
    live_parser.add_argument("--index-id", default=BRTI_INDEX_ID)
    live_parser.add_argument("--max-messages", type=int, default=None)
    live_parser.add_argument("--max-reconnects", type=int, default=3)

    manifest_parser = subparsers.add_parser(
        "forward-capture-manifest",
        help="Summarize BRTI raw-event forward-capture coverage for a bounded window",
    )
    manifest_parser.add_argument("--start", required=True)
    manifest_parser.add_argument("--end", required=True)
    manifest_parser.add_argument("--index-id", default=BRTI_INDEX_ID)
    manifest_parser.add_argument(
        "--freshness-seconds",
        type=float,
        default=DEFAULT_BRTI_FRESHNESS_LIMIT_SECONDS,
    )
    manifest_parser.add_argument(
        "--gap-threshold-seconds",
        type=float,
        default=DEFAULT_BRTI_GAP_THRESHOLD_SECONDS,
    )
    manifest_parser.add_argument("--code-version", default=None)
    manifest_parser.add_argument("--config-version", default=None)
    manifest_parser.add_argument(
        "--private-artifact-ref",
        action="append",
        default=[],
        help="Private artifact reference as name=value; raw artifacts are not embedded",
    )
    manifest_parser.add_argument("--output", default=None)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    OperationalStateRepository(settings.database_url).apply_migrations()

    if args.command == "mock-smoke":
        summary = BRTILiveCollector(database_url=settings.database_url).ingest_frames(
            [fixture_brti_frame(value=args.value)]
        )
        latest = BRTILatestContextRepository(settings.database_url).get_latest()
        print(
            json.dumps(
                {"ingest": summary.as_dict(), "latest": latest.as_dict()},
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "status":
        status = BRTILatestContextRepository(settings.database_url).get_latest(
            index_id=args.index_id,
            freshness_limit=timedelta(seconds=args.freshness_seconds),
        )
        print(json.dumps(status.as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "live-collect":
        summary = asyncio.run(
            run_live_collector(
                settings=settings,
                database_url=settings.database_url,
                index_id=args.index_id,
                max_messages=args.max_messages,
                max_reconnects=args.max_reconnects,
            )
        )
        print(json.dumps(summary.as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "forward-capture-manifest":
        manifest = build_brti_forward_capture_manifest(
            database_url=settings.database_url,
            window_start=_parse_cli_datetime(args.start),
            window_end=_parse_cli_datetime(args.end),
            index_id=args.index_id,
            freshness_limit_seconds=args.freshness_seconds,
            gap_threshold_seconds=args.gap_threshold_seconds,
            code_version=args.code_version,
            config_version=args.config_version,
            private_artifact_refs=_parse_private_artifact_refs(args.private_artifact_ref),
        )
        encoded = json.dumps(manifest, indent=2, sort_keys=True)
        if args.output:
            Path(args.output).write_text(encoded + "\n", encoding="utf-8")
        else:
            print(encoded)
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


@dataclass
class _MutableIngestAggregate:
    index_id: str
    messages_seen: int = 0
    control_messages_seen: int = 0
    accepted: int = 0
    raw_events_inserted: int = 0
    latest_context_updates: int = 0
    stale_latest_drops: int = 0
    rejections: list[BRTIRejection] = field(default_factory=list)

    def add(self, summary: BRTIIngestSummary) -> None:
        self.messages_seen += summary.messages_seen
        self.control_messages_seen += summary.control_messages_seen
        self.accepted += summary.accepted
        self.raw_events_inserted += summary.raw_events_inserted
        self.latest_context_updates += summary.latest_context_updates
        self.stale_latest_drops += summary.stale_latest_drops
        self.rejections.extend(summary.rejections)

    def summary(self) -> BRTIIngestSummary:
        return BRTIIngestSummary(
            source=BRTI_RAW_EVENT_SOURCE,
            index_id=self.index_id,
            messages_seen=self.messages_seen,
            control_messages_seen=self.control_messages_seen,
            accepted=self.accepted,
            rejected=len(self.rejections),
            raw_events_inserted=self.raw_events_inserted,
            latest_context_updates=self.latest_context_updates,
            stale_latest_drops=self.stale_latest_drops,
            rejections=tuple(self.rejections),
        )


def _latest_context_from_row(row: Mapping[str, Any]) -> BRTILatestContext:
    return BRTILatestContext(
        index_id=str(row["index_id"]),
        value=Decimal(str(row["value"])),
        source_timestamp=_ensure_utc(row["source_timestamp"]),
        source_timestamp_ms=int(row["source_timestamp_ms"]),
        received_at=_ensure_utc(row["received_at"]),
        source_lag_ms=int(row["source_lag_ms"]),
        raw_event_id=str(row["raw_event_id"]),
        source_event_id=str(row["source_event_id"]),
        payload_hash=str(row["payload_hash"]),
        source=str(row["source"]),
        schema_version=str(row["schema_version"]),
        source_sequence=_optional_int(row["source_sequence"]),
        source_sid=_optional_int(row["source_sid"]),
        avg_60s_value=_optional_decimal(row["avg_60s_value"]),
        avg_60s_window_size=_optional_int(row["avg_60s_window_size"]),
        avg_60s_window_start=_optional_datetime(row["avg_60s_window_start"]),
        avg_60s_window_end_exclusive=_optional_datetime(
            row["avg_60s_window_end_exclusive"]
        ),
        final_60s_value=_optional_decimal(row["final_60s_value"]),
        final_60s_window_size=_optional_int(row["final_60s_window_size"]),
        final_60s_window_start=_optional_datetime(row["final_60s_window_start"]),
        final_60s_window_end_exclusive=_optional_datetime(
            row["final_60s_window_end_exclusive"]
        ),
        metadata=row["metadata"] if isinstance(row["metadata"], Mapping) else {},
        updated_at=_ensure_utc(row["updated_at"]),
    )


def _parse_upstream_data(value: Any) -> Mapping[str, Any]:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise BRTIValidationError(
                "malformed_payload",
                "cfbenchmarks_value msg.data is not JSON",
            ) from exc
    elif isinstance(value, Mapping):
        decoded = value
    else:
        raise BRTIValidationError(
            "malformed_payload",
            "cfbenchmarks_value msg.data is missing",
        )
    if not isinstance(decoded, Mapping):
        raise BRTIValidationError("malformed_payload", "cfbenchmarks_value data is not an object")
    return decoded


def _parse_window_average(value: Any, field_name: str) -> WindowAverage | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise BRTIValidationError("malformed_payload", f"{field_name} is not an object")
    average = _required_decimal(value, "value", parent=field_name)
    if average <= 0:
        raise BRTIValidationError("non_positive_value", f"{field_name}.value must be positive")
    window_size = _required_int(value, "window_size", parent=field_name)
    if window_size < 0:
        raise BRTIValidationError("malformed_payload", f"{field_name}.window_size is negative")
    return WindowAverage(
        value=average,
        window_size=window_size,
        window_start=_optional_ms_datetime(value.get("window_start_ts_ms")),
        window_end_exclusive=_optional_ms_datetime(value.get("window_end_ts_exclusive")),
    )


def _required_str(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise BRTIValidationError("malformed_payload", f"missing string field: {key}")
    return value


def _required_int(mapping: Mapping[str, Any], key: str, parent: str | None = None) -> int:
    value = mapping.get(key)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        prefix = f"{parent}." if parent else ""
        raise BRTIValidationError("malformed_payload", f"missing integer field: {prefix}{key}") from exc


def _required_decimal(
    mapping: Mapping[str, Any],
    key: str,
    parent: str | None = None,
) -> Decimal:
    value = mapping.get(key)
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        prefix = f"{parent}." if parent else ""
        raise BRTIValidationError("malformed_payload", f"missing decimal field: {prefix}{key}") from exc


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_utc(value)
    return None


def _optional_ms_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return _datetime_from_ms(int(value))
    except (TypeError, ValueError):
        raise BRTIValidationError("malformed_payload", f"invalid millisecond timestamp: {value!r}")


def _datetime_from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def _datetime_to_ms(value: datetime) -> int:
    return int(_ensure_utc(value).timestamp() * 1000)


def _parse_cli_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid ISO timestamp: {value}") from exc
    return _ensure_utc(parsed)


def _parse_private_artifact_refs(values: Sequence[str]) -> dict[str, str]:
    refs: dict[str, str] = {}
    for index, value in enumerate(values, start=1):
        if "=" in value:
            key, ref = value.split("=", 1)
            refs[key.strip() or f"ref_{index}"] = ref.strip()
        else:
            refs[f"ref_{index}"] = value
    return refs


def _payload_hash_rollup(payload_hashes: Sequence[str]) -> str | None:
    if not payload_hashes:
        return None
    encoded = "\n".join(sorted(payload_hashes)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(child) for child in value]
    return value


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _decimal_or_none(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


if __name__ == "__main__":
    raise SystemExit(main())
