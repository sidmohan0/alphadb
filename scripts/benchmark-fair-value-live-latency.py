#!/usr/bin/env python3
"""Benchmark fair-value live-job hot-path latency with safe defaults."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from alphadb.collectors.coinbase import FixtureCoinbaseClient
from alphadb.collectors.kalshi_rest import FixtureKalshiRestClient
from alphadb.config import settings_from_env
from alphadb.live_runtime import MARKET_CONTEXT_SOURCES
from alphadb.model_evaluation import fair_value_live_job
from alphadb.model_evaluation.fair_value_live_job import (
    FairValueLiveTradingJob,
    FairValueLiveTradingJobConfig,
)

BENCHMARK_SCHEMA_VERSION = "alphadb_fair_value_live_latency_benchmark.v1"
DEFAULT_OUTPUT_ROOT = Path("artifacts/fair-value-live-latency-benchmark")
DEFAULT_TARGET_P95_SECONDS = 45.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="benchmark-fair-value-live-latency",
        description=(
            "Run repeated fair-value live trading-job cycles and summarize hot-path latency. "
            "Defaults are fixture-only and never submit live orders."
        ),
    )
    parser.add_argument("--iterations", type=positive_int, default=30)
    parser.add_argument("--warmup", type=non_negative_int, default=5)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--target-p95-seconds", type=float, default=DEFAULT_TARGET_P95_SECONDS)
    parser.add_argument("--source", choices=("fixture", "kalshi-public"), default="fixture")
    parser.add_argument(
        "--coinbase-source",
        choices=("fixture", "coinbase-live"),
        default="fixture",
    )
    parser.add_argument(
        "--market-context-source",
        choices=MARKET_CONTEXT_SOURCES,
        default="coinbase_primary",
    )
    parser.add_argument("--max-markets", type=positive_int, default=1)
    parser.add_argument("--min-edge", type=float, default=0.0)
    parser.add_argument("--min-contract-price", type=float, default=0.25)
    parser.add_argument("--max-order-dollars", type=float, default=5.0)
    parser.add_argument("--max-ticker-exposure-dollars", type=float, default=5.0)
    parser.add_argument("--max-daily-loss-dollars", type=float, default=50.0)
    parser.add_argument("--quote-stale-seconds", type=positive_int, default=15)
    parser.add_argument("--coinbase-feature-stale-seconds", type=positive_int, default=90)
    parser.add_argument(
        "--now",
        default=None,
        help="ISO UTC-ish base timestamp for deterministic runs.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.target_p95_seconds <= 0:
        raise SystemExit("--target-p95-seconds must be positive")

    base_now = parse_datetime(args.now) if args.now else datetime.now(UTC).replace(microsecond=0)
    output_root = args.output_root
    output_root.mkdir(parents=True, exist_ok=True)

    settings_env = dict(os.environ)
    settings_env.update(
        {
            "ALPHADB_RUNTIME_MODE": "fixture",
            "ALPHADB_ENABLE_LIVE_ORDERS": "0",
            "ALPHADB_HUMAN_CUTOVER_APPROVED": "0",
        }
    )
    settings = settings_from_env(settings_env)

    original_make_kalshi_client = fair_value_live_job.make_kalshi_client
    original_make_coinbase_client = fair_value_live_job.make_coinbase_client
    current_now = {"value": base_now}

    def make_kalshi_client(source: str, settings: Any):
        if source == "fixture":
            return FixtureKalshiRestClient(
                markets=benchmark_markets(current_now["value"], args.max_markets),
                orderbooks=benchmark_orderbooks(args.max_markets),
            )
        return original_make_kalshi_client(source, settings)

    def make_coinbase_client(source: str):
        if source == "fixture":
            return FixtureCoinbaseClient(candles=benchmark_candles(current_now["value"]))
        return original_make_coinbase_client(source)

    fair_value_live_job.make_kalshi_client = make_kalshi_client
    fair_value_live_job.make_coinbase_client = make_coinbase_client
    try:
        samples = []
        total_runs = args.warmup + args.iterations
        for index in range(total_runs):
            run_now = base_now + timedelta(seconds=index)
            current_now["value"] = run_now
            sample = run_once(
                args=args,
                settings=settings,
                now=run_now,
                measured=index >= args.warmup,
            )
            samples.append(sample)
    finally:
        fair_value_live_job.make_kalshi_client = original_make_kalshi_client
        fair_value_live_job.make_coinbase_client = original_make_coinbase_client

    measured = [sample for sample in samples if sample["measured"]]
    summary = build_summary(
        args=args,
        base_now=base_now,
        samples=samples,
        measured=measured,
    )
    output_path = args.output or output_root / "benchmark-summary.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def run_once(
    *,
    args: argparse.Namespace,
    settings: Any,
    now: datetime,
    measured: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    manifest = FairValueLiveTradingJob(
        config=FairValueLiveTradingJobConfig(
            output_root=args.output_root,
            source=args.source,
            coinbase_source=args.coinbase_source,
            market_context_source=args.market_context_source,
            max_markets=args.max_markets,
            min_edge=args.min_edge,
            min_contract_price=args.min_contract_price,
            max_order_dollars=args.max_order_dollars,
            max_ticker_exposure_dollars=args.max_ticker_exposure_dollars,
            max_daily_loss_dollars=args.max_daily_loss_dollars,
            submit_live_orders=False,
            runtime_config_source="cli",
            quote_stale_seconds=args.quote_stale_seconds,
            coinbase_feature_stale_seconds=args.coinbase_feature_stale_seconds,
        ),
        settings=settings,
    ).run(now=now)
    wall_seconds = time.perf_counter() - started
    timing = as_mapping(manifest.get("timing"))
    selected_decision = as_mapping(manifest.get("selected_decision"))
    runtime_controls = as_mapping(manifest.get("runtime_controls"))
    return {
        "measured": measured,
        "run_id": manifest.get("run_id"),
        "generated_at": manifest.get("generated_at"),
        "wall_seconds": round(wall_seconds, 6),
        "manifest_total_elapsed_seconds": timing.get("total_elapsed_seconds"),
        "phase_seconds": dict(as_mapping(timing.get("phase_seconds"))),
        "quote_to_submit_seconds": timing.get("quote_to_submit_seconds"),
        "decision": selected_decision.get("decision"),
        "reason": selected_decision.get("reason"),
        "orders_placed": runtime_controls.get("orders_placed"),
        "live_orders_enabled": runtime_controls.get("live_orders_enabled"),
        "manifest_path": as_mapping(
            as_mapping(manifest.get("artifacts")).get("manifest")
        ).get("path"),
    }


def build_summary(
    *,
    args: argparse.Namespace,
    base_now: datetime,
    samples: Sequence[Mapping[str, Any]],
    measured: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    wall = [float(sample["wall_seconds"]) for sample in measured]
    manifest_total = [
        float(sample["manifest_total_elapsed_seconds"])
        for sample in measured
        if sample.get("manifest_total_elapsed_seconds") is not None
    ]
    target_p95 = float(args.target_p95_seconds)
    p95_wall = percentile(wall, 95)
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": (
            "fair_value_live_trading_job_"
            f"{args.source}_{args.coinbase_source}_no_live_orders"
        ),
        "safety": {
            "submit_live_orders": False,
            "runtime_mode": "fixture",
            "runtime_config_source": "cli",
            "s3_upload": False,
        },
        "config": {
            "base_now": base_now.isoformat(),
            "iterations": args.iterations,
            "warmup": args.warmup,
            "source": args.source,
            "coinbase_source": args.coinbase_source,
            "market_context_source": args.market_context_source,
            "max_markets": args.max_markets,
            "min_edge": args.min_edge,
            "min_contract_price": args.min_contract_price,
            "max_order_dollars": args.max_order_dollars,
            "max_ticker_exposure_dollars": args.max_ticker_exposure_dollars,
            "max_daily_loss_dollars": args.max_daily_loss_dollars,
            "quote_stale_seconds": args.quote_stale_seconds,
            "coinbase_feature_stale_seconds": args.coinbase_feature_stale_seconds,
            "output_root": str(args.output_root),
        },
        "target": {
            "p95_runtime_seconds_lt": target_p95,
            "passes": p95_wall is not None and p95_wall < target_p95,
        },
        "wall_seconds": stats(wall),
        "manifest_total_elapsed_seconds": stats(manifest_total),
        "phase_seconds": phase_stats(measured),
        "counts": {
            "samples": len(samples),
            "measured_samples": len(measured),
            "warmup_samples": len(samples) - len(measured),
            "orders_placed": sum(int(sample.get("orders_placed") or 0) for sample in measured),
            "live_orders_enabled_count": sum(
                1 for sample in measured if sample.get("live_orders_enabled") is True
            ),
        },
        "decision_reasons": reason_counts(measured),
        "sample_runs": list(measured[-min(5, len(measured)) :]),
        "artifact_retention": {
            "run_artifacts_kept": True,
            "summary_path": str(args.output or args.output_root / "benchmark-summary.json"),
            "run_artifacts_root": str(args.output_root),
        },
    }


def benchmark_markets(now: datetime, max_markets: int) -> list[Mapping[str, Any]]:
    markets = []
    for index in range(max_markets):
        ticker = f"KXBTC15M-BENCH-{index:02d}"
        threshold = 100.0 + (index * 0.1)
        markets.append(
            {
                "ticker": ticker,
                "series_ticker": "KXBTC15M",
                "event_ticker": f"KXBTC15M-BENCH-{index:02d}-EVENT",
                "status": "open",
                "open_time": (now - timedelta(minutes=10)).isoformat(),
                "close_time": (now + timedelta(minutes=5)).isoformat(),
                "updated_time": (now - timedelta(seconds=1)).isoformat(),
                "title": f"Bitcoin above ${threshold:.2f}?",
                "payout_threshold": f"{threshold:.2f}",
                "yes_bid_dollars": "0.4800",
                "yes_ask_dollars": "0.5200",
                "no_bid_dollars": "0.4700",
                "no_ask_dollars": "0.5300",
            }
        )
    return markets


def benchmark_orderbooks(max_markets: int) -> dict[str, Mapping[str, Any]]:
    return {
        f"KXBTC15M-BENCH-{index:02d}": {
            "orderbook_fp": {
                "yes_dollars": [["0.4800", "14.00"], ["0.4700", "9.00"]],
                "no_dollars": [["0.4700", "11.00"], ["0.4600", "8.00"]],
            }
        }
        for index in range(max_markets)
    }


def benchmark_candles(now: datetime, count: int = 60) -> list[Sequence[Any]]:
    start = now - timedelta(minutes=count - 1)
    candles: list[Sequence[Any]] = []
    for index in range(count):
        timestamp = start + timedelta(minutes=index)
        close = 101.0 + index * 0.002
        open_ = close - 0.01
        high = close + 0.02
        low = close - 0.03
        volume = 1.0 + index * 0.01
        candles.append([int(timestamp.timestamp()), low, high, open_, close, volume])
    return candles


def phase_stats(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    phases = sorted(
        {
            phase
            for sample in samples
            for phase in as_mapping(sample.get("phase_seconds")).keys()
        }
    )
    return {
        phase: stats(
            [
                float(as_mapping(sample.get("phase_seconds")).get(phase) or 0.0)
                for sample in samples
            ]
        )
        for phase in phases
    }


def reason_counts(samples: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    reasons = sorted(
        {str(sample.get("reason") or sample.get("decision") or "") for sample in samples}
    )
    return [
        {
            "reason": reason,
            "count": sum(
                1
                for sample in samples
                if str(sample.get("reason") or sample.get("decision") or "") == reason
            ),
        }
        for reason in reasons
    ]


def stats(values: Sequence[float]) -> dict[str, float | int | None]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {
            "count": 0,
            "min": None,
            "mean": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "max": None,
            "stdev": None,
        }
    return {
        "count": len(ordered),
        "min": round(ordered[0], 6),
        "mean": round(statistics.fmean(ordered), 6),
        "p50": percentile(ordered, 50),
        "p90": percentile(ordered, 90),
        "p95": percentile(ordered, 95),
        "p99": percentile(ordered, 99),
        "max": round(ordered[-1], 6),
        "stdev": round(statistics.stdev(ordered), 6) if len(ordered) > 1 else 0.0,
    }


def percentile(values: Sequence[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return round(ordered[0], 6)
    rank = (len(ordered) - 1) * pct / 100.0
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = rank - lower_index
    value = ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction
    return round(value, 6)


def parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid --now timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


if __name__ == "__main__":
    raise SystemExit(main())
