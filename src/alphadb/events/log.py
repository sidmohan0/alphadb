"""Append-only raw event log backed by Postgres."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def canonical_payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class RawEventRecord:
    raw_event_id: str
    source: str
    schema_version: str
    payload_hash: str
    inserted: bool

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "raw_event_id": self.raw_event_id,
            "source": self.source,
            "schema_version": self.schema_version,
            "payload_hash": self.payload_hash,
            "inserted": self.inserted,
        }


class RawEventLog:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def append(
        self,
        *,
        source: str,
        schema_version: str,
        payload: Mapping[str, Any],
        run_id: str | None = None,
        market_ticker: str | None = None,
        source_event_id: str | None = None,
        received_at: datetime | None = None,
        source_timestamp: datetime | None = None,
    ) -> RawEventRecord:
        event_id = f"evt_{uuid4().hex}"
        timestamp = received_at or datetime.now(UTC)
        payload_hash = canonical_payload_hash(payload)

        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into raw_events (
                        raw_event_id,
                        run_id,
                        market_ticker,
                        source,
                        source_event_id,
                        received_at,
                        source_timestamp,
                        schema_version,
                        payload_hash,
                        payload
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (source, source_event_id)
                    where source_event_id is not null
                    do nothing
                    returning raw_event_id
                    """,
                    (
                        event_id,
                        run_id,
                        market_ticker,
                        source,
                        source_event_id,
                        timestamp,
                        source_timestamp,
                        schema_version,
                        payload_hash,
                        Jsonb(dict(payload)),
                    ),
                )
                inserted_row = cursor.fetchone()
                inserted = inserted_row is not None
                if inserted_row is None:
                    cursor.execute(
                        """
                        select raw_event_id, payload_hash
                        from raw_events
                        where source = %s and source_event_id = %s
                        """,
                        (source, source_event_id),
                    )
                    existing = cursor.fetchone()
                    if existing is None:
                        raise RuntimeError("raw event insert neither inserted nor found existing row")
                    event_id = str(existing["raw_event_id"])
                    payload_hash = str(existing["payload_hash"])
            connection.commit()

        return RawEventRecord(
            raw_event_id=event_id,
            source=source,
            schema_version=schema_version,
            payload_hash=payload_hash,
            inserted=inserted,
        )

    def replay_events(
        self,
        *,
        run_id: str | None = None,
        market_ticker: str | None = None,
    ) -> Iterable[dict[str, Any]]:
        clauses: list[str] = []
        params: list[str] = []
        if run_id is not None:
            clauses.append("run_id = %s")
            params.append(run_id)
        if market_ticker is not None:
            clauses.append("market_ticker = %s")
            params.append(market_ticker)
        where = f"where {' and '.join(clauses)}" if clauses else ""

        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select
                        raw_event_id,
                        run_id,
                        market_ticker,
                        source,
                        source_event_id,
                        received_at,
                        source_timestamp,
                        schema_version,
                        payload_hash,
                        payload
                    from raw_events
                    {where}
                    order by received_at asc, raw_event_id asc
                    """,
                    params,
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def counts_by_source_schema(self) -> list[dict[str, str | int]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select source, schema_version, count(*)::int as events
                    from raw_events
                    group by source, schema_version
                    order by source, schema_version
                    """
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]
