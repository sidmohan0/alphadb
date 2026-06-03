"""CLI for external signal research datasets."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from os import environ
from pathlib import Path

from alphadb.config import Settings, settings_from_env
from alphadb.external_signals.x_api import (
    FixtureXCountsClient,
    HttpXCountsClient,
    XCostBudget,
    collect_x_counts_dataset,
    estimate_x_counts_cost,
    generate_minimal_x_features,
    load_x_counts_rows,
    load_x_manifest,
    load_x_query_catalog,
    materialize_x_signal_features,
    parse_utc,
    write_json,
)
from alphadb.model_evaluation.io import load_json, load_tabular_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-external-signals")
    subparsers = parser.add_subparsers(dest="command", required=True)

    estimate = subparsers.add_parser("x-estimate", help="Estimate X counts collection cost")
    add_common_x_args(estimate)
    estimate.add_argument("--output", default=None)

    download = subparsers.add_parser("x-download", help="Download X counts data live")
    add_common_x_args(download)
    download.add_argument("--output-root", default=None)
    download.add_argument("--allow-partial", action="store_true")
    download.add_argument("--dataset-id", default=None)
    download.add_argument("--output", default=None)

    build = subparsers.add_parser("x-build-dataset", help="Build an X counts research dataset")
    add_common_x_args(build)
    build.add_argument("--source", choices=("fixture", "x-api-live"), default="fixture")
    build.add_argument("--output-root", default=None)
    build.add_argument("--allow-partial", action="store_true")
    build.add_argument("--fixture", default=None)
    build.add_argument("--dataset-id", default=None)
    build.add_argument("--output", default=None)

    materialize = subparsers.add_parser(
        "x-materialize-features",
        help="Join X counts features onto decision-time rows",
    )
    materialize.add_argument("--decision-rows", required=True)
    materialize.add_argument("--counts", required=True)
    materialize.add_argument("--manifest", required=True)
    materialize.add_argument("--output", required=True)

    features = subparsers.add_parser(
        "x-generate-features",
        help="Generate minimal X count features from rows and counts",
    )
    features.add_argument("--rows", required=True)
    features.add_argument("--counts", required=True)
    features.add_argument("--output", required=True)
    features.add_argument("--windows", default="5m,15m,1h")

    return parser


def add_common_x_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--market", default="KXBTC15M")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--catalog", default=None)
    parser.add_argument("--categories", default=None)
    parser.add_argument("--daily-cap-usd", type=float, default=None)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env(env_with_dotenv())

    if args.command == "x-estimate":
        report = build_estimate_from_args(args, settings).as_dict()
        write_or_print(report, args.output)
        return 0 if report["budget_status"] == "approved" else 2

    if args.command == "x-download":
        result = collect_x_counts_dataset(
            market=args.market,
            start=parse_utc(args.start),
            end=parse_utc(args.end),
            output_root=args.output_root or settings.x_api_default_output_root,
            budget=budget_from_args(args, settings),
            client=HttpXCountsClient(
                bearer_token=settings.x_api_bearer_token,
                base_url=settings.x_api_base_url,
            ),
            catalog=load_x_query_catalog(args.catalog),
            categories=parse_categories(args.categories),
            source_mode="x_api_live",
            dataset_id=args.dataset_id,
            allow_partial=args.allow_partial,
        )
        write_or_print(result.as_dict(), args.output)
        return 0

    if args.command == "x-build-dataset":
        catalog = load_x_query_catalog(args.catalog)
        budget = budget_from_args(args, settings)
        categories = parse_categories(args.categories)
        source_mode = "x_api_live" if args.source == "x-api-live" else "fixture"
        if args.fixture:
            fixture_payload = load_json(Path(args.fixture))
            payloads = fixture_payload.get("payloads", fixture_payload)
            if not isinstance(payloads, dict):
                raise ValueError("X fixture file must contain a payload mapping")
            client = FixtureXCountsClient(payloads)
        elif source_mode == "fixture":
            client = FixtureXCountsClient()
        else:
            client = HttpXCountsClient(
                bearer_token=settings.x_api_bearer_token,
                base_url=settings.x_api_base_url,
            )
        result = collect_x_counts_dataset(
            market=args.market,
            start=parse_utc(args.start),
            end=parse_utc(args.end),
            output_root=args.output_root or settings.x_api_default_output_root,
            budget=budget,
            client=client,
            catalog=catalog,
            categories=categories,
            source_mode=source_mode,
            dataset_id=args.dataset_id,
            allow_partial=args.allow_partial,
        )
        write_or_print(result.as_dict(), args.output)
        return 0

    if args.command == "x-materialize-features":
        rows = materialize_x_signal_features(
            load_tabular_rows(Path(args.decision_rows)),
            load_x_counts_rows(args.counts),
            load_x_manifest(args.manifest),
        )
        write_json(Path(args.output), {"rows": rows})
        return 0

    if args.command == "x-generate-features":
        rows = generate_minimal_x_features(
            load_tabular_rows(Path(args.rows)),
            load_x_counts_rows(args.counts),
            windows_seconds=parse_windows(args.windows),
        )
        write_rows(Path(args.output), rows)
        print(
            json.dumps(
                {
                    "row_count": len(rows),
                    "output": args.output,
                    "windows": args.windows,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


def build_estimate_from_args(args: argparse.Namespace, settings: Settings):
    return estimate_x_counts_cost(
        market=args.market,
        start=parse_utc(args.start),
        end=parse_utc(args.end),
        budget=budget_from_args(args, settings),
        catalog=load_x_query_catalog(args.catalog),
        categories=parse_categories(args.categories),
    )


def budget_from_args(args: argparse.Namespace, settings: Settings) -> XCostBudget | None:
    daily = first_not_none(args.daily_cap_usd, settings.x_api_daily_cap_usd)
    if daily is None:
        return None
    return XCostBudget(
        daily_cap_usd=float(daily),
    )


def parse_categories(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_windows(value: str) -> list[int]:
    windows: list[int] = []
    for raw in value.split(","):
        part = raw.strip().lower()
        if not part:
            continue
        if part.endswith("m"):
            windows.append(int(part[:-1]) * 60)
        elif part.endswith("h"):
            windows.append(int(part[:-1]) * 3600)
        elif part.endswith("d"):
            windows.append(int(part[:-1]) * 86_400)
        else:
            windows.append(int(part))
    if not windows:
        raise ValueError("at least one feature window is required")
    return windows


def first_not_none(*values):
    for value in values:
        if value is not None:
            return value
    return None


def env_with_dotenv(path: str | Path = ".env") -> dict[str, str]:
    values = dict(environ)
    env_path = Path(path)
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key or key in values:
            continue
        values[key] = normalize_env_value(value)
    return values


def normalize_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def write_or_print(payload: dict, output: str | None) -> None:
    if output:
        write_json(Path(output), payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def write_rows(path: Path, rows: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        import pandas as pd  # type: ignore[import-not-found]

        pd.DataFrame(rows).to_parquet(path, index=False)
        return
    if suffix == ".json":
        path.write_text(json.dumps({"rows": rows}, indent=2, sort_keys=True, default=str), encoding="utf-8")
        return
    if suffix == ".jsonl":
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        return
    raise ValueError(f"unsupported output suffix: {path.suffix}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
