"""Command-line tools for raw event logs."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from alphadb.config import settings_from_env
from alphadb.events.log import RawEventLog
from alphadb.state.repository import OperationalStateRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-events")
    subparsers = parser.add_subparsers(dest="command", required=True)

    append_parser = subparsers.add_parser("append-demo", help="Append one demo raw event")
    append_parser.add_argument("--source", default="demo")
    append_parser.add_argument("--schema-version", default="demo.v1")

    subparsers.add_parser("counts", help="Show raw event counts by source/schema")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    OperationalStateRepository(settings.database_url).apply_migrations()
    event_log = RawEventLog(settings.database_url)

    if args.command == "append-demo":
        record = event_log.append(
            source=args.source,
            schema_version=args.schema_version,
            payload={"event": "demo"},
        )
        print(json.dumps(record.as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "counts":
        print(json.dumps(event_log.counts_by_source_schema(), indent=2, sort_keys=True))
        return 0

    raise AssertionError(f"unhandled command: {args.command}")
