"""Deterministic decision-time feature rows with no-lookahead evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.config import settings_from_env
from alphadb.events.log import RawEventLog, canonical_payload_hash
from alphadb.model_registry.registry import ModelRegistryRepository, RegisteredModel
from alphadb.state.repository import OperationalStateRepository

REQUIRED_FEATURE_SCHEMAS = (
    "kalshi.market_snapshot.v1",
    "kalshi.orderbook_snapshot.v1",
)


class MissingFeatureEventsError(ValueError):
    """Raised when replayed raw events cannot satisfy a feature-row contract."""


class NoLookaheadViolationError(ValueError):
    """Raised when a feature row would use source data newer than decision time."""


class ModelFeatureCompatibilityError(ValueError):
    """Raised when requested feature/dataset metadata does not match the model record."""


@dataclass(frozen=True)
class FeatureRow:
    feature_row_id: str
    run_id: str
    market_ticker: str
    model_id: str
    decision_timestamp: datetime
    max_source_event_timestamp: datetime
    source_lag_ms: int
    feature_version: str
    calibration_version: str
    dataset_id: str
    feature_values: Mapping[str, Any]
    source_event_ids: tuple[str, ...]
    row_hash: str
    metadata: Mapping[str, Any]
    inserted: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature_row_id": self.feature_row_id,
            "run_id": self.run_id,
            "market_ticker": self.market_ticker,
            "model_id": self.model_id,
            "decision_timestamp": self.decision_timestamp.isoformat(),
            "max_source_event_timestamp": self.max_source_event_timestamp.isoformat(),
            "source_lag_ms": self.source_lag_ms,
            "feature_version": self.feature_version,
            "calibration_version": self.calibration_version,
            "dataset_id": self.dataset_id,
            "feature_values": dict(self.feature_values),
            "source_event_ids": list(self.source_event_ids),
            "row_hash": self.row_hash,
            "metadata": dict(self.metadata),
            "inserted": self.inserted,
        }


class FeatureLedgerRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def upsert_immutable(self, row: FeatureRow) -> FeatureRow:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into feature_rows (
                        feature_row_id,
                        run_id,
                        market_ticker,
                        model_id,
                        decision_timestamp,
                        max_source_event_timestamp,
                        source_lag_ms,
                        feature_version,
                        calibration_version,
                        dataset_id,
                        feature_values,
                        source_event_ids,
                        row_hash,
                        metadata
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (run_id, market_ticker, model_id, decision_timestamp) do nothing
                    returning *
                    """,
                    (
                        row.feature_row_id,
                        row.run_id,
                        row.market_ticker,
                        row.model_id,
                        row.decision_timestamp,
                        row.max_source_event_timestamp,
                        row.source_lag_ms,
                        row.feature_version,
                        row.calibration_version,
                        row.dataset_id,
                        Jsonb(dict(row.feature_values)),
                        list(row.source_event_ids),
                        row.row_hash,
                        Jsonb(dict(row.metadata)),
                    ),
                )
                stored = cursor.fetchone()
                if stored is None:
                    stored = self._fetch_by_identity(cursor, row)
                    if str(stored["row_hash"]) != row.row_hash:
                        raise ValueError("feature row identity already exists with a different row hash")
                    stored = {**stored, "inserted": False}
            connection.commit()
        return row_to_feature_row(stored)

    def list(
        self,
        *,
        run_id: str | None = None,
        market_ticker: str | None = None,
    ) -> list[FeatureRow]:
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
                    select *
                    from feature_rows
                    {where}
                    order by decision_timestamp desc, feature_row_id desc
                    """,
                    params,
                )
                rows = cursor.fetchall()
        return [row_to_feature_row(row) for row in rows]

    def recent_rows(self, *, limit: int = 10) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        feature_row_id,
                        run_id,
                        market_ticker,
                        model_id,
                        decision_timestamp,
                        max_source_event_timestamp,
                        source_lag_ms,
                        feature_version,
                        dataset_id,
                        left(row_hash, 12) as row_hash_prefix
                    from feature_rows
                    order by decision_timestamp desc, feature_row_id desc
                    limit %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _fetch_by_identity(self, cursor: psycopg.Cursor, row: FeatureRow) -> Mapping[str, Any]:
        cursor.execute(
            """
            select *
            from feature_rows
            where
                run_id = %s
                and market_ticker = %s
                and model_id = %s
                and decision_timestamp = %s
            """,
            (row.run_id, row.market_ticker, row.model_id, row.decision_timestamp),
        )
        stored = cursor.fetchone()
        if stored is None:
            raise RuntimeError("feature row conflict neither inserted nor found existing row")
        return stored


class FeatureRowBuilder:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.raw_events = RawEventLog(database_url)
        self.models = ModelRegistryRepository(database_url)
        self.ledger = FeatureLedgerRepository(database_url)

    def build(
        self,
        *,
        run_id: str,
        market_ticker: str,
        model_id: str,
        decision_timestamp: datetime,
        expected_feature_version: str | None = None,
        expected_dataset_id: str | None = None,
    ) -> FeatureRow:
        OperationalStateRepository(self.database_url).apply_migrations()
        decision_timestamp = ensure_utc(decision_timestamp)
        model = self.models.get(model_id)
        assert_model_compatible(
            model,
            expected_feature_version=expected_feature_version,
            expected_dataset_id=expected_dataset_id,
        )
        events = list(self.raw_events.replay_events(run_id=run_id, market_ticker=market_ticker))
        selected_events = latest_required_events(events, REQUIRED_FEATURE_SCHEMAS)
        max_source_event_timestamp = max(event_source_timestamp(event) for event in selected_events)
        if max_source_event_timestamp > decision_timestamp:
            raise NoLookaheadViolationError(
                "max_source_event_timestamp is after decision_timestamp: "
                f"{max_source_event_timestamp.isoformat()} > {decision_timestamp.isoformat()}"
            )
        source_lag_ms = int((decision_timestamp - max_source_event_timestamp).total_seconds() * 1000)
        feature_values = build_kxbtc15m_feature_values(selected_events)
        source_event_ids = tuple(str(event["raw_event_id"]) for event in selected_events)
        row_hash = canonical_payload_hash(
            {
                "run_id": run_id,
                "market_ticker": market_ticker,
                "model_id": model_id,
                "decision_timestamp": decision_timestamp.isoformat(),
                "feature_version": model.feature_version,
                "calibration_version": model.calibration_version,
                "dataset_id": model.dataset_id,
                "feature_values": feature_values,
                "source_event_ids": source_event_ids,
            }
        )

        row = FeatureRow(
            feature_row_id=f"feature_{uuid4().hex[:12]}",
            run_id=run_id,
            market_ticker=market_ticker,
            model_id=model_id,
            decision_timestamp=decision_timestamp,
            max_source_event_timestamp=max_source_event_timestamp,
            source_lag_ms=source_lag_ms,
            feature_version=model.feature_version,
            calibration_version=model.calibration_version,
            dataset_id=model.dataset_id,
            feature_values=feature_values,
            source_event_ids=source_event_ids,
            row_hash=row_hash,
            metadata={
                "model_name": model.model_name,
                "model_version": model.model_version,
                "required_schemas": list(REQUIRED_FEATURE_SCHEMAS),
            },
        )
        return self.ledger.upsert_immutable(row)


def assert_model_compatible(
    model: RegisteredModel,
    *,
    expected_feature_version: str | None,
    expected_dataset_id: str | None,
) -> None:
    if expected_feature_version is not None and model.feature_version != expected_feature_version:
        raise ModelFeatureCompatibilityError(
            f"model feature_version {model.feature_version} != expected {expected_feature_version}"
        )
    if expected_dataset_id is not None and model.dataset_id != expected_dataset_id:
        raise ModelFeatureCompatibilityError(
            f"model dataset_id {model.dataset_id} != expected {expected_dataset_id}"
        )


def latest_required_events(
    events: Sequence[Mapping[str, Any]],
    required_schemas: Sequence[str],
) -> list[Mapping[str, Any]]:
    if not events:
        raise MissingFeatureEventsError("no raw events found for feature row")
    latest_by_schema: dict[str, Mapping[str, Any]] = {}
    for event in events:
        schema = str(event["schema_version"])
        if schema not in required_schemas:
            continue
        current = latest_by_schema.get(schema)
        if current is None or event_sort_key(event) > event_sort_key(current):
            latest_by_schema[schema] = event

    missing = [schema for schema in required_schemas if schema not in latest_by_schema]
    if missing:
        raise MissingFeatureEventsError(f"missing required raw event schemas: {', '.join(missing)}")
    return [latest_by_schema[schema] for schema in required_schemas]


def event_sort_key(event: Mapping[str, Any]) -> tuple[datetime, str]:
    return (event_source_timestamp(event), str(event["raw_event_id"]))


def event_source_timestamp(event: Mapping[str, Any]) -> datetime:
    timestamp = event.get("source_timestamp") or event["received_at"]
    if not isinstance(timestamp, datetime):
        raise ValueError("raw event timestamp must be a datetime")
    return ensure_utc(timestamp)


def build_kxbtc15m_feature_values(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_schema = {str(event["schema_version"]): event for event in events}
    market_payload = dict(by_schema["kalshi.market_snapshot.v1"]["payload"])
    market = dict(market_payload.get("market", {}))
    orderbook_payload = dict(by_schema["kalshi.orderbook_snapshot.v1"]["payload"])
    orderbook = dict(orderbook_payload.get("orderbook", {})).get("orderbook_fp", {})
    yes_levels = orderbook.get("yes_dollars", [])
    no_levels = orderbook.get("no_dollars", [])
    best_yes_bid = first_price(yes_levels)
    best_no_bid = first_price(no_levels)

    values = {
        "yes_bid_dollars": decimal_or_none(market.get("yes_bid_dollars")),
        "yes_ask_dollars": decimal_or_none(market.get("yes_ask_dollars")),
        "no_bid_dollars": decimal_or_none(market.get("no_bid_dollars")),
        "no_ask_dollars": decimal_or_none(market.get("no_ask_dollars")),
        "best_yes_bid_dollars": best_yes_bid,
        "best_no_bid_dollars": best_no_bid,
        "yes_depth_top": first_quantity(yes_levels),
        "no_depth_top": first_quantity(no_levels),
        "orderbook_levels_yes": len(yes_levels),
        "orderbook_levels_no": len(no_levels),
    }
    if best_yes_bid is not None and best_no_bid is not None:
        values["top_bid_sum_dollars"] = float(Decimal(str(best_yes_bid)) + Decimal(str(best_no_bid)))
    return values


def first_price(levels: Sequence[Sequence[Any]]) -> float | None:
    if not levels:
        return None
    return decimal_or_none(levels[0][0])


def first_quantity(levels: Sequence[Sequence[Any]]) -> float | None:
    if not levels:
        return None
    return decimal_or_none(levels[0][1])


def decimal_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)))


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def row_to_feature_row(row: Mapping[str, Any]) -> FeatureRow:
    values = dict(row)
    values.setdefault("inserted", True)
    return FeatureRow(
        feature_row_id=str(values["feature_row_id"]),
        run_id=str(values["run_id"]),
        market_ticker=str(values["market_ticker"]),
        model_id=str(values["model_id"]),
        decision_timestamp=ensure_utc(values["decision_timestamp"]),
        max_source_event_timestamp=ensure_utc(values["max_source_event_timestamp"]),
        source_lag_ms=int(values["source_lag_ms"]),
        feature_version=str(values["feature_version"]),
        calibration_version=str(values["calibration_version"]),
        dataset_id=str(values["dataset_id"]),
        feature_values=dict(values["feature_values"]),
        source_event_ids=tuple(values["source_event_ids"]),
        row_hash=str(values["row_hash"]),
        metadata=dict(values["metadata"]),
        inserted=bool(values["inserted"]),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-features")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser_ = subparsers.add_parser("build-row", help="Build one feature row")
    build_parser_.add_argument("--run-id", required=True)
    build_parser_.add_argument("--market-ticker", required=True)
    build_parser_.add_argument("--model-id", required=True)
    build_parser_.add_argument("--decision-timestamp", required=True)
    build_parser_.add_argument("--expected-feature-version", default=None)
    build_parser_.add_argument("--expected-dataset-id", default=None)

    list_parser = subparsers.add_parser("list", help="List feature rows")
    list_parser.add_argument("--run-id", default=None)
    list_parser.add_argument("--market-ticker", default=None)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    OperationalStateRepository(settings.database_url).apply_migrations()

    if args.command == "build-row":
        row = FeatureRowBuilder(settings.database_url).build(
            run_id=args.run_id,
            market_ticker=args.market_ticker,
            model_id=args.model_id,
            decision_timestamp=datetime.fromisoformat(
                args.decision_timestamp.replace("Z", "+00:00")
            ),
            expected_feature_version=args.expected_feature_version,
            expected_dataset_id=args.expected_dataset_id,
        )
        print(json.dumps(row.as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "list":
        rows = [
            row.as_dict()
            for row in FeatureLedgerRepository(settings.database_url).list(
                run_id=args.run_id,
                market_ticker=args.market_ticker,
            )
        ]
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    raise AssertionError(f"unhandled command: {args.command}")
