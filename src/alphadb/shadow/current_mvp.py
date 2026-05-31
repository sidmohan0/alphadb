"""Import Current MVP decision-boundary exports into AlphaDB vocabulary."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.config import settings_from_env
from alphadb.events.log import canonical_payload_hash
from alphadb.shadow.comparison import DecisionBoundaryRecord
from alphadb.state.repository import OperationalStateRepository

CURRENT_MVP_BOUNDARY_SCHEMA = "current_mvp.decision_boundary.v1"
SECRET_KEY_FRAGMENTS = ("secret", "private_key", "api_key", "password", "token")


class CurrentMvpImportError(ValueError):
    """Raised when a Current MVP decision-boundary export cannot be imported."""


@dataclass(frozen=True)
class CurrentMvpBoundaryImport:
    import_id: str
    boundary: DecisionBoundaryRecord
    schema_version: str
    source_identity: str
    source_hash: str
    record_hash: str
    intentional_differences: Mapping[str, str]
    inserted: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "import_id": self.import_id,
            "schema_version": self.schema_version,
            "source_identity": self.source_identity,
            "source_hash": self.source_hash,
            "record_hash": self.record_hash,
            "intentional_differences": dict(self.intentional_differences),
            "boundary": self.boundary.as_dict(),
            "inserted": self.inserted,
        }


class CurrentMvpBoundaryImporter:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def import_mapping(
        self,
        payload: Mapping[str, Any],
        *,
        source_identity: str = "inline",
        source_hash: str | None = None,
    ) -> CurrentMvpBoundaryImport:
        OperationalStateRepository(self.database_url).apply_migrations()
        reject_secret_fields(payload)
        schema_version = str(payload.get("schema_version") or "")
        if schema_version != CURRENT_MVP_BOUNDARY_SCHEMA:
            raise CurrentMvpImportError(
                f"unsupported Current MVP boundary schema_version: {schema_version!r}"
            )
        boundary_payload = payload.get("boundary") if isinstance(payload.get("boundary"), Mapping) else payload
        try:
            boundary = DecisionBoundaryRecord.from_mapping(
                {**dict(boundary_payload), "source": "current_mvp"}
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CurrentMvpImportError(f"malformed Current MVP boundary record: {exc}") from exc
        record_hash = canonical_payload_hash(boundary.as_dict())
        import_record = CurrentMvpBoundaryImport(
            import_id=f"current_mvp_{uuid4().hex[:12]}",
            boundary=boundary,
            schema_version=schema_version,
            source_identity=source_identity,
            source_hash=source_hash or canonical_payload_hash(payload),
            record_hash=record_hash,
            intentional_differences=dict(payload.get("intentional_differences") or {}),
        )
        return self.persist(import_record, raw_payload=payload)

    def import_file(self, path: str | Path) -> CurrentMvpBoundaryImport:
        path = Path(path).expanduser().resolve()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise CurrentMvpImportError(f"Current MVP boundary file missing: {path}") from exc
        except json.JSONDecodeError as exc:
            raise CurrentMvpImportError(f"Current MVP boundary file is malformed JSON: {path}") from exc
        if not isinstance(payload, Mapping):
            raise CurrentMvpImportError("Current MVP boundary file must contain a JSON object")
        source_hash = canonical_payload_hash(payload)
        return self.import_mapping(payload, source_identity=str(path), source_hash=source_hash)

    def persist(
        self,
        record: CurrentMvpBoundaryImport,
        *,
        raw_payload: Mapping[str, Any],
    ) -> CurrentMvpBoundaryImport:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into current_mvp_decision_boundaries (
                        import_id,
                        market_ticker,
                        decision_timestamp,
                        schema_version,
                        source_identity,
                        source_hash,
                        record_hash,
                        boundary_payload,
                        raw_payload,
                        intentional_differences
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (market_ticker, decision_timestamp, record_hash) do nothing
                    returning import_id
                    """,
                    (
                        record.import_id,
                        record.boundary.market_ticker,
                        record.boundary.decision_timestamp,
                        record.schema_version,
                        record.source_identity,
                        record.source_hash,
                        record.record_hash,
                        Jsonb(record.boundary.as_dict()),
                        Jsonb(dict(raw_payload)),
                        Jsonb(dict(record.intentional_differences)),
                    ),
                )
                inserted = cursor.fetchone() is not None
                if not inserted:
                    cursor.execute(
                        """
                        select import_id
                        from current_mvp_decision_boundaries
                        where market_ticker = %s and decision_timestamp = %s and record_hash = %s
                        """,
                        (
                            record.boundary.market_ticker,
                            record.boundary.decision_timestamp,
                            record.record_hash,
                        ),
                    )
                    existing = cursor.fetchone()
                    if existing is None:
                        raise RuntimeError("Current MVP import conflict neither inserted nor found")
                    record = CurrentMvpBoundaryImport(
                        import_id=str(existing["import_id"]),
                        boundary=record.boundary,
                        schema_version=record.schema_version,
                        source_identity=record.source_identity,
                        source_hash=record.source_hash,
                        record_hash=record.record_hash,
                        intentional_differences=record.intentional_differences,
                        inserted=False,
                    )
            connection.commit()
        return record

    def latest_for_market(
        self,
        *,
        market_ticker: str,
        decision_timestamp: datetime,
    ) -> CurrentMvpBoundaryImport | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from current_mvp_decision_boundaries
                    where market_ticker = %s and decision_timestamp = %s
                    order by created_at desc, import_id desc
                    limit 1
                    """,
                    (market_ticker, decision_timestamp),
                )
                row = cursor.fetchone()
        return None if row is None else row_to_import(row)


def row_to_import(row: Mapping[str, Any]) -> CurrentMvpBoundaryImport:
    values = dict(row)
    values.setdefault("inserted", True)
    return CurrentMvpBoundaryImport(
        import_id=str(values["import_id"]),
        boundary=DecisionBoundaryRecord.from_mapping(values["boundary_payload"]),
        schema_version=str(values["schema_version"]),
        source_identity=str(values["source_identity"]),
        source_hash=str(values["source_hash"]),
        record_hash=str(values["record_hash"]),
        intentional_differences=dict(values["intentional_differences"]),
        inserted=bool(values["inserted"]),
    )


def reject_secret_fields(value: Any, *, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in SECRET_KEY_FRAGMENTS):
                raise CurrentMvpImportError(f"Current MVP import contains forbidden secret field: {key_path}")
            reject_secret_fields(child, path=key_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_secret_fields(child, path=f"{path}[{index}]")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-shadow-current-mvp")
    subparsers = parser.add_subparsers(dest="command", required=True)
    import_parser = subparsers.add_parser("import", help="Import a Current MVP boundary JSON file")
    import_parser.add_argument("path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    if args.command == "import":
        record = CurrentMvpBoundaryImporter(settings.database_url).import_file(args.path)
        print(json.dumps(record.as_dict(), indent=2, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")
