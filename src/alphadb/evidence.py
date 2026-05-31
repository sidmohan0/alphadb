"""Evidence report for one-hour live-data paper readiness."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from alphadb.config import settings_from_env
from alphadb.strategy.state import StrategyRunRepository


@dataclass(frozen=True)
class EvidenceReport:
    run_id: str
    runtime_mode: str
    duration_seconds: int
    counts: Mapping[str, int]
    paper: Mapping[str, Any]
    latency_checkpoints: Mapping[str, float]
    no_lookahead: Mapping[str, Any]
    shadow_parity: Mapping[str, int]
    pass_criteria_met: bool
    failure_reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "runtime_mode": self.runtime_mode,
            "duration_seconds": self.duration_seconds,
            "counts": dict(self.counts),
            "paper": dict(self.paper),
            "latency_checkpoints": dict(self.latency_checkpoints),
            "no_lookahead": dict(self.no_lookahead),
            "shadow_parity": dict(self.shadow_parity),
            "pass_criteria_met": self.pass_criteria_met,
            "failure_reasons": list(self.failure_reasons),
            "alp16_pass_rule": (
                "one continuous hour, no unhandled errors, every eligible instance handled, "
                "and zero unexplained decision-critical mismatches"
            ),
        }


class EvidenceReportBuilder:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.strategy = StrategyRunRepository(database_url)

    def build(
        self,
        *,
        run_id: str,
        observed_end: datetime | None = None,
        minimum_duration_seconds: int = 3600,
    ) -> EvidenceReport:
        run = self._get_run(run_id)
        observed_end = observed_end or self._observed_end(run_id) or datetime.now(UTC)
        duration_seconds = int((observed_end - run["started_at"]).total_seconds())
        counts = self.strategy.counts(run_id=run_id)
        paper = self._paper_summary(run_id)
        latency = self._latency_summary(run_id)
        no_lookahead = self._no_lookahead_summary(run_id)
        shadow = self._shadow_summary(run_id)
        failures = evaluate_failures(
            duration_seconds=duration_seconds,
            minimum_duration_seconds=minimum_duration_seconds,
            counts=counts,
            shadow=shadow,
        )
        return EvidenceReport(
            run_id=run_id,
            runtime_mode=str(run["mode"]),
            duration_seconds=duration_seconds,
            counts=counts,
            paper=paper,
            latency_checkpoints=latency,
            no_lookahead=no_lookahead,
            shadow_parity=shadow,
            pass_criteria_met=not failures,
            failure_reasons=tuple(failures),
        )

    def _get_run(self, run_id: str) -> Mapping[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select run_id, mode, market_series, status, started_at, metadata
                    from platform_runs
                    where run_id = %s
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise KeyError(f"unknown run_id: {run_id}")
        return dict(row)

    def _observed_end(self, run_id: str) -> datetime | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select max(decision_timestamp) as observed_end
                    from strategy_market_outcomes
                    where run_id = %s
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
        return None if row is None or row["observed_end"] is None else row["observed_end"]

    def _paper_summary(self, run_id: str) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        count(distinct po.paper_order_id)::int as paper_orders,
                        count(distinct pf.paper_fill_id)::int as paper_fills,
                        coalesce(sum(pr.realized_pnl_dollars), 0)::float as realized_pnl_dollars,
                        coalesce(sum(pr.unrealized_pnl_dollars), 0)::float as unrealized_pnl_dollars
                    from strategy_market_outcomes smo
                    left join paper_orders po on po.paper_order_id = smo.paper_order_id
                    left join paper_fills pf on pf.paper_order_id = po.paper_order_id
                    left join paper_reconciliations pr on pr.paper_order_id = po.paper_order_id
                    where smo.run_id = %s
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
        return dict(row or {})

    def _latency_summary(self, run_id: str) -> dict[str, float]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select latency_checkpoints
                    from strategy_market_outcomes
                    where run_id = %s
                    """,
                    (run_id,),
                )
                rows = cursor.fetchall()
        totals: dict[str, list[float]] = {}
        for row in rows:
            for key, value in dict(row["latency_checkpoints"]).items():
                totals.setdefault(key, []).append(float(value))
        return {
            f"{key}_avg": round(sum(values) / len(values), 3)
            for key, values in totals.items()
            if values
        }

    def _no_lookahead_summary(self, run_id: str) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        count(*)::int as feature_rows,
                        count(*) filter (
                            where max_source_event_timestamp <= decision_timestamp
                        )::int as no_lookahead_rows,
                        max(source_lag_ms)::int as max_source_lag_ms
                    from feature_rows
                    where run_id = %s
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
        return dict(row or {})

    def _shadow_summary(self, run_id: str) -> dict[str, int]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        count(*) filter (where sc.status = 'match')::int as exact_matches,
                        count(*) filter (where sc.status = 'mismatch')::int as unexplained_mismatches,
                        count(*) filter (
                            where sc.status in ('missing_current_mvp_data', 'missing_alpha_data')
                        )::int as missing_records,
                        count(*) filter (where sc.status = 'intentional_difference')::int
                            as intentional_differences
                    from shadow_comparisons sc
                    where sc.market_ticker in (
                        select market_ticker
                        from strategy_market_outcomes
                        where run_id = %s
                    )
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
        return {key: int(value or 0) for key, value in dict(row or {}).items()}


def evaluate_failures(
    *,
    duration_seconds: int,
    minimum_duration_seconds: int,
    counts: Mapping[str, int],
    shadow: Mapping[str, int],
) -> list[str]:
    failures: list[str] = []
    if duration_seconds < minimum_duration_seconds:
        failures.append("duration_below_one_hour")
    if int(counts.get("errored", 0)) > 0:
        failures.append("unhandled_errors_present")
    scanned = int(counts.get("scanned", counts.get("terminal", 0)))
    terminal = int(counts.get("handled", 0)) + int(counts.get("skipped", 0)) + int(counts.get("errored", 0))
    if scanned <= 0:
        failures.append("no_market_instances_scanned")
    elif terminal < scanned:
        failures.append("missing_handled_outcomes")
    if int(shadow.get("unexplained_mismatches", 0)) > 0:
        failures.append("unexplained_shadow_mismatches")
    if int(shadow.get("missing_records", 0)) > 0:
        failures.append("missing_shadow_records")
    return failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)
    report = subparsers.add_parser("report", help="Build one run evidence report")
    report.add_argument("--run-id", required=True)
    report.add_argument("--observed-end", default=None)
    report.add_argument("--minimum-duration-seconds", type=int, default=3600)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    if args.command == "report":
        observed_end = (
            None
            if args.observed_end is None
            else datetime.fromisoformat(args.observed_end.replace("Z", "+00:00"))
        )
        report = EvidenceReportBuilder(settings.database_url).build(
            run_id=args.run_id,
            observed_end=observed_end,
            minimum_duration_seconds=args.minimum_duration_seconds,
        )
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True, default=str))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")
