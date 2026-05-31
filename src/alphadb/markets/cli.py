"""Command-line inspection for registered market specs."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from alphadb.markets.registry import default_market_registry
from alphadb.markets.spec import MarketSpec


def spec_summary_row(spec: MarketSpec) -> dict[str, str | int]:
    return {
        "series": spec.series,
        "underlying": spec.underlying,
        "horizon_minutes": spec.horizon_minutes,
        "external_symbol": spec.feature_config.external_symbol,
        "execution": spec.trading_cutoffs.time_in_force,
    }


def render_market_list(specs: Sequence[MarketSpec]) -> str:
    rows = [spec_summary_row(spec) for spec in specs]
    if not rows:
        return "No market specs registered."

    header = "series underlying horizon_minutes external_symbol execution"
    body = [
        (
            f"{row['series']} {row['underlying']} {row['horizon_minutes']} "
            f"{row['external_symbol']} {row['execution']}"
        )
        for row in rows
    ]
    return "\n".join([header, *body])


def render_market_json(spec: MarketSpec) -> str:
    return json.dumps(spec.model_dump(mode="json"), indent=2, sort_keys=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-markets")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List registered market specs")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect one market spec")
    inspect_parser.add_argument("series", help="Series ticker, e.g. KXBTC15M")
    inspect_parser.add_argument("--json", action="store_true", help="Render the full spec as JSON")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = default_market_registry()

    if args.command == "list":
        print(render_market_list(registry.list()))
        return 0

    if args.command == "inspect":
        spec = registry.get(args.series)
        if args.json:
            print(render_market_json(spec))
        else:
            print(render_market_list([spec]))
        return 0

    raise AssertionError(f"unhandled command: {args.command}")
