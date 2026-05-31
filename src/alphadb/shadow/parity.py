"""Shadow parity runner between AlphaDB and imported Current MVP boundaries."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row

from alphadb.config import settings_from_env
from alphadb.shadow.comparison import (
    DecisionBoundaryRecord,
    ShadowComparator,
    ShadowComparisonRepository,
    ShadowComparisonReport,
)
from alphadb.shadow.current_mvp import CurrentMvpBoundaryImporter
from alphadb.state.repository import OperationalStateRepository


class AlphaBoundaryMissingError(KeyError):
    """Raised when AlphaDB has no persisted decision boundary for a market."""


class AlphaBoundaryRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def get_for_outcome(
        self,
        *,
        run_id: str,
        market_ticker: str,
    ) -> DecisionBoundaryRecord:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        smo.market_ticker,
                        smo.decision_timestamp,
                        fr.feature_row_id,
                        fr.row_hash as feature_row_hash,
                        fr.model_id,
                        fr.feature_values,
                        fr.metadata as feature_metadata,
                        d.probability_yes,
                        d.selected_side,
                        d.skip_reason,
                        d.metadata as decision_metadata,
                        rd.status as risk_status,
                        coalesce(oi.quantity, 0) as intended_quantity,
                        smo.latency_checkpoints
                    from strategy_market_outcomes smo
                    join decisions d on d.decision_id = smo.decision_id
                    join feature_rows fr on fr.feature_row_id = d.metadata->>'feature_row_id'
                    left join risk_decisions rd on rd.risk_decision_id = smo.risk_decision_id
                    left join order_intents oi on oi.risk_decision_id = rd.risk_decision_id
                    where smo.run_id = %s and smo.market_ticker = %s
                    order by smo.updated_at desc
                    limit 1
                    """,
                    (run_id, market_ticker),
                )
                row = cursor.fetchone()
        if row is None:
            raise AlphaBoundaryMissingError(f"missing AlphaDB outcome: {run_id} {market_ticker}")
        return row_to_alpha_boundary(row)


class ShadowParityRunner:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.alpha_boundaries = AlphaBoundaryRepository(database_url)
        self.current_imports = CurrentMvpBoundaryImporter(database_url)
        self.comparisons = ShadowComparisonRepository(database_url)

    def compare_boundaries(
        self,
        *,
        alpha: DecisionBoundaryRecord | None,
        current_mvp: DecisionBoundaryRecord | None,
        intentional_differences: Mapping[str, str] | None = None,
    ) -> ShadowComparisonReport:
        OperationalStateRepository(self.database_url).apply_migrations()
        report = ShadowComparator().compare(
            alpha=alpha,
            current_mvp=current_mvp,
            intentional_differences=intentional_differences or {},
        )
        return self.comparisons.persist(report)

    def compare_market(
        self,
        *,
        run_id: str,
        market_ticker: str,
        intentional_differences: Mapping[str, str] | None = None,
    ) -> ShadowComparisonReport:
        OperationalStateRepository(self.database_url).apply_migrations()
        alpha: DecisionBoundaryRecord | None
        try:
            alpha = self.alpha_boundaries.get_for_outcome(run_id=run_id, market_ticker=market_ticker)
        except AlphaBoundaryMissingError:
            alpha = None
        current = None
        if alpha is not None:
            imported = self.current_imports.latest_for_market(
                market_ticker=alpha.market_ticker,
                decision_timestamp=alpha.decision_timestamp,
            )
            current = None if imported is None else imported.boundary
            if imported is not None and not intentional_differences:
                intentional_differences = imported.intentional_differences
        report = ShadowComparator().compare(
            alpha=alpha,
            current_mvp=current,
            intentional_differences=intentional_differences or {},
        )
        return self.comparisons.persist(report)


def row_to_alpha_boundary(row: Mapping[str, Any]) -> DecisionBoundaryRecord:
    decision_metadata = dict(row["decision_metadata"])
    feature_metadata = dict(row["feature_metadata"])
    evaluations = {
        item["side"]: item for item in decision_metadata.get("side_evaluations", [])
        if isinstance(item, Mapping)
    }
    return DecisionBoundaryRecord.from_mapping(
        {
            "market_ticker": row["market_ticker"],
            "decision_timestamp": row["decision_timestamp"],
            "feature_row_id": row["feature_row_id"],
            "feature_row_hash": row["feature_row_hash"],
            "model_id": row["model_id"],
            "model_artifact_sha256": feature_metadata.get("model_artifact_sha256"),
            "probability_yes": row["probability_yes"],
            "executable_quotes": {
                "yes_ask_dollars": dict(row["feature_values"]).get("yes_ask_dollars"),
                "no_ask_dollars": dict(row["feature_values"]).get("no_ask_dollars"),
            },
            "yes_ev_dollars": optional_float(evaluations.get("yes", {}).get("ev_dollars")),
            "no_ev_dollars": optional_float(evaluations.get("no", {}).get("ev_dollars")),
            "selected_ev_dollars": decision_metadata.get("selected_ev_dollars"),
            "selected_side": row["selected_side"],
            "skip_reason": row["skip_reason"],
            "risk_status": row["risk_status"] or "missing",
            "intended_quantity": row["intended_quantity"],
            "feature_values": dict(row["feature_values"]),
            "timing_metadata": {"latency_checkpoints": dict(row["latency_checkpoints"])},
            "source": "alphadb",
        }
    )


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-shadow-parity")
    subparsers = parser.add_subparsers(dest="command", required=True)
    compare = subparsers.add_parser("compare-market", help="Compare one AlphaDB outcome to imported Current MVP boundary")
    compare.add_argument("--run-id", required=True)
    compare.add_argument("--market-ticker", required=True)
    compare.add_argument("--intentional-difference", action="append", default=[])
    return parser


def parse_intentional(values: Sequence[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        field, _, note = value.partition("=")
        if not field or not note:
            raise ValueError("intentional differences must use field=note")
        parsed[field] = note
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    if args.command == "compare-market":
        report = ShadowParityRunner(settings.database_url).compare_market(
            run_id=args.run_id,
            market_ticker=args.market_ticker,
            intentional_differences=parse_intentional(args.intentional_difference),
        )
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True, default=str))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")
