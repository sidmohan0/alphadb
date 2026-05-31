"""Decision-boundary comparison between AlphaDB and the current MVP."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.config import settings_from_env
from alphadb.state.repository import OperationalStateRepository

ComparisonStatus = Literal[
    "match",
    "mismatch",
    "intentional_difference",
    "missing_current_mvp_data",
]

BOUNDARY_FIELDS = (
    "feature_row_id",
    "feature_row_hash",
    "model_id",
    "probability_yes",
    "executable_quotes",
    "selected_ev_dollars",
    "selected_side",
    "skip_reason",
    "risk_status",
    "intended_quantity",
)


@dataclass(frozen=True)
class DecisionBoundaryRecord:
    market_ticker: str
    decision_timestamp: datetime
    feature_row_id: str
    feature_row_hash: str
    model_id: str
    probability_yes: float
    executable_quotes: Mapping[str, float | None]
    selected_ev_dollars: float | None
    selected_side: str | None
    skip_reason: str | None
    risk_status: str
    intended_quantity: int
    source: str

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> DecisionBoundaryRecord:
        timestamp = values["decision_timestamp"]
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return cls(
            market_ticker=str(values["market_ticker"]),
            decision_timestamp=timestamp,
            feature_row_id=str(values["feature_row_id"]),
            feature_row_hash=str(values["feature_row_hash"]),
            model_id=str(values["model_id"]),
            probability_yes=float(values["probability_yes"]),
            executable_quotes=dict(values["executable_quotes"]),
            selected_ev_dollars=optional_float(values.get("selected_ev_dollars")),
            selected_side=values.get("selected_side"),
            skip_reason=values.get("skip_reason"),
            risk_status=str(values["risk_status"]),
            intended_quantity=int(values["intended_quantity"]),
            source=str(values.get("source", "unknown")),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "market_ticker": self.market_ticker,
            "decision_timestamp": self.decision_timestamp.isoformat(),
            "feature_row_id": self.feature_row_id,
            "feature_row_hash": self.feature_row_hash,
            "model_id": self.model_id,
            "probability_yes": self.probability_yes,
            "executable_quotes": dict(self.executable_quotes),
            "selected_ev_dollars": self.selected_ev_dollars,
            "selected_side": self.selected_side,
            "skip_reason": self.skip_reason,
            "risk_status": self.risk_status,
            "intended_quantity": self.intended_quantity,
            "source": self.source,
        }


@dataclass(frozen=True)
class FieldComparison:
    field: str
    alpha_value: Any
    current_mvp_value: Any
    status: Literal["match", "mismatch", "intentional_difference"]
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "alpha_value": self.alpha_value,
            "current_mvp_value": self.current_mvp_value,
            "status": self.status,
            "note": self.note,
        }


@dataclass(frozen=True)
class ShadowComparisonReport:
    comparison_id: str
    market_ticker: str
    decision_timestamp: datetime
    status: ComparisonStatus
    mismatch_count: int
    intentional_difference_count: int
    alpha_controls_live_orders: bool
    comparisons: tuple[FieldComparison, ...]
    alpha: DecisionBoundaryRecord
    current_mvp: DecisionBoundaryRecord | None
    inserted: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "market_ticker": self.market_ticker,
            "decision_timestamp": self.decision_timestamp.isoformat(),
            "status": self.status,
            "mismatch_count": self.mismatch_count,
            "intentional_difference_count": self.intentional_difference_count,
            "alpha_controls_live_orders": self.alpha_controls_live_orders,
            "comparisons": [comparison.as_dict() for comparison in self.comparisons],
            "alpha": self.alpha.as_dict(),
            "current_mvp": None if self.current_mvp is None else self.current_mvp.as_dict(),
            "inserted": self.inserted,
        }


class ShadowComparator:
    def compare(
        self,
        *,
        alpha: DecisionBoundaryRecord,
        current_mvp: DecisionBoundaryRecord | None,
        intentional_differences: Mapping[str, str] | None = None,
    ) -> ShadowComparisonReport:
        intentional_differences = intentional_differences or {}
        if current_mvp is None:
            return ShadowComparisonReport(
                comparison_id=f"shadow_{uuid4().hex[:12]}",
                market_ticker=alpha.market_ticker,
                decision_timestamp=alpha.decision_timestamp,
                status="missing_current_mvp_data",
                mismatch_count=0,
                intentional_difference_count=0,
                alpha_controls_live_orders=False,
                comparisons=(),
                alpha=alpha,
                current_mvp=None,
            )

        comparisons: list[FieldComparison] = []
        for field in BOUNDARY_FIELDS:
            alpha_value = getattr(alpha, field)
            current_value = getattr(current_mvp, field)
            if alpha_value == current_value:
                status: Literal["match", "mismatch", "intentional_difference"] = "match"
                note = None
            elif field in intentional_differences:
                status = "intentional_difference"
                note = intentional_differences[field]
            else:
                status = "mismatch"
                note = None
            comparisons.append(
                FieldComparison(
                    field=field,
                    alpha_value=alpha_value,
                    current_mvp_value=current_value,
                    status=status,
                    note=note,
                )
            )
        mismatch_count = sum(comparison.status == "mismatch" for comparison in comparisons)
        intentional_count = sum(
            comparison.status == "intentional_difference" for comparison in comparisons
        )
        if mismatch_count:
            report_status: ComparisonStatus = "mismatch"
        elif intentional_count:
            report_status = "intentional_difference"
        else:
            report_status = "match"
        return ShadowComparisonReport(
            comparison_id=f"shadow_{uuid4().hex[:12]}",
            market_ticker=alpha.market_ticker,
            decision_timestamp=alpha.decision_timestamp,
            status=report_status,
            mismatch_count=mismatch_count,
            intentional_difference_count=intentional_count,
            alpha_controls_live_orders=False,
            comparisons=tuple(comparisons),
            alpha=alpha,
            current_mvp=current_mvp,
        )


class ShadowComparisonRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def persist(self, report: ShadowComparisonReport) -> ShadowComparisonReport:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into shadow_comparisons (
                        comparison_id,
                        market_ticker,
                        decision_timestamp,
                        status,
                        mismatch_count,
                        intentional_difference_count,
                        alpha_payload,
                        current_mvp_payload,
                        comparisons
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    returning comparison_id
                    """,
                    (
                        report.comparison_id,
                        report.market_ticker,
                        report.decision_timestamp,
                        report.status,
                        report.mismatch_count,
                        report.intentional_difference_count,
                        Jsonb(report.alpha.as_dict()),
                        None if report.current_mvp is None else Jsonb(report.current_mvp.as_dict()),
                        Jsonb([comparison.as_dict() for comparison in report.comparisons]),
                    ),
                )
            connection.commit()
        return report

    def recent(self, *, limit: int = 10) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        comparison_id,
                        market_ticker,
                        decision_timestamp,
                        status,
                        mismatch_count,
                        intentional_difference_count,
                        created_at
                    from shadow_comparisons
                    order by created_at desc, comparison_id desc
                    limit %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def parse_intentional_differences(values: Sequence[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        field, _, note = value.partition("=")
        if not field or not note:
            raise ValueError("intentional differences must use field=note")
        parsed[field] = note
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-shadow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare_parser = subparsers.add_parser("compare", help="Compare AlphaDB and Current MVP JSON")
    compare_parser.add_argument("--alpha-json", required=True)
    compare_parser.add_argument("--current-json", default=None)
    compare_parser.add_argument("--intentional-difference", action="append", default=[])

    status_parser = subparsers.add_parser("status", help="Show recent shadow comparisons")
    status_parser.add_argument("--limit", type=int, default=10)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    OperationalStateRepository(settings.database_url).apply_migrations()
    repository = ShadowComparisonRepository(settings.database_url)

    if args.command == "compare":
        alpha = DecisionBoundaryRecord.from_mapping(json.loads(args.alpha_json))
        current = (
            None
            if args.current_json is None
            else DecisionBoundaryRecord.from_mapping(json.loads(args.current_json))
        )
        report = ShadowComparator().compare(
            alpha=alpha,
            current_mvp=current,
            intentional_differences=parse_intentional_differences(args.intentional_difference),
        )
        print(json.dumps(repository.persist(report).as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "status":
        print(
            json.dumps(
                repository.recent(limit=args.limit),
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return 0

    raise AssertionError(f"unhandled command: {args.command}")
