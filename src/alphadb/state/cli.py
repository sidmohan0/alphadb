"""Command-line tools for target-platform operational state."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from alphadb.config import settings_from_env
from alphadb.markets.registry import default_market_registry
from alphadb.state.repository import OperationalStateRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-state")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("migrate", help="Apply operational state migrations")
    subparsers.add_parser("counts", help="Show operational state record counts")

    tracer_parser = subparsers.add_parser("create-tracer", help="Create a complete tracer run")
    tracer_parser.add_argument("--series", default="KXBTC15M")

    show_parser = subparsers.add_parser("show-run", help="Show one run summary")
    show_parser.add_argument("run_id")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    repository = OperationalStateRepository(settings.database_url)

    if args.command == "migrate":
        applied = repository.apply_migrations()
        print(json.dumps({"applied_migrations": applied}, indent=2, sort_keys=True))
        return 0

    if args.command == "counts":
        print(json.dumps(repository.counts().as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "create-tracer":
        spec = default_market_registry().get(args.series)
        repository.apply_migrations()
        print(json.dumps(repository.create_tracer_run(spec).as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "show-run":
        print(json.dumps(repository.get_run_summary(args.run_id), indent=2, sort_keys=True))
        return 0

    raise AssertionError(f"unhandled command: {args.command}")
