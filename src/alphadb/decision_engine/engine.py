"""Shared decision engine tracer for replay, shadow, paper, and live modes."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.config import settings_from_env
from alphadb.features.ledger import FeatureLedgerRepository, FeatureRow
from alphadb.markets.registry import default_market_registry
from alphadb.markets.spec import MarketSpec
from alphadb.state.repository import OperationalStateRepository

Side = Literal["yes", "no"]


@dataclass(frozen=True)
class ModelOutput:
    probability_yes: float
    model_id: str
    feature_row_id: str


@dataclass(frozen=True)
class ExecutableQuotes:
    yes_ask_dollars: float | None
    no_ask_dollars: float | None

    @classmethod
    def from_feature_row(cls, row: FeatureRow) -> ExecutableQuotes:
        values = row.feature_values
        return cls(
            yes_ask_dollars=optional_float(values.get("yes_ask_dollars")),
            no_ask_dollars=optional_float(values.get("no_ask_dollars")),
        )


@dataclass(frozen=True)
class DecisionPolicy:
    min_ev_dollars: float
    max_cost_dollars: float
    time_in_force: str

    @classmethod
    def from_spec(cls, spec: MarketSpec) -> DecisionPolicy:
        return cls(
            min_ev_dollars=spec.trading_cutoffs.min_ev,
            max_cost_dollars=spec.risk_config.live_stake_cap_dollars,
            time_in_force=spec.trading_cutoffs.time_in_force,
        )


@dataclass(frozen=True)
class DecisionInput:
    spec: MarketSpec
    feature_row: FeatureRow
    model_output: ModelOutput
    executable_quotes: ExecutableQuotes
    policy: DecisionPolicy


@dataclass(frozen=True)
class SideEvaluation:
    side: Side
    probability: float
    price_dollars: float | None
    fee_dollars: float | None
    ev_dollars: float | None
    valid: bool
    invalid_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "probability": self.probability,
            "price_dollars": self.price_dollars,
            "fee_dollars": self.fee_dollars,
            "ev_dollars": self.ev_dollars,
            "valid": self.valid,
            "invalid_reason": self.invalid_reason,
        }


@dataclass(frozen=True)
class DecisionResult:
    decision_id: str
    run_id: str
    market_ticker: str
    decision_timestamp: datetime
    feature_row_id: str
    model_id: str
    probability_yes: float
    selected_side: Side | None
    selected_ev_dollars: float | None
    selected_price_dollars: float | None
    intended_quantity: int
    max_cost_dollars: float
    outcome: Literal["order_candidate", "skip"]
    skip_reason: str | None
    side_evaluations: tuple[SideEvaluation, ...]
    inserted: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "run_id": self.run_id,
            "market_ticker": self.market_ticker,
            "decision_timestamp": self.decision_timestamp.isoformat(),
            "feature_row_id": self.feature_row_id,
            "model_id": self.model_id,
            "probability_yes": self.probability_yes,
            "selected_side": self.selected_side,
            "selected_ev_dollars": self.selected_ev_dollars,
            "selected_price_dollars": self.selected_price_dollars,
            "intended_quantity": self.intended_quantity,
            "max_cost_dollars": self.max_cost_dollars,
            "outcome": self.outcome,
            "skip_reason": self.skip_reason,
            "side_evaluations": [evaluation.as_dict() for evaluation in self.side_evaluations],
            "inserted": self.inserted,
        }


class DecisionEngine:
    engine_version = "decision_engine.v1"

    def evaluate(self, decision_input: DecisionInput) -> DecisionResult:
        probability_yes = decision_input.model_output.probability_yes
        if probability_yes < 0 or probability_yes > 1:
            raise ValueError("probability_yes must be between 0 and 1")
        yes = evaluate_side(
            side="yes",
            probability=probability_yes,
            price=decision_input.executable_quotes.yes_ask_dollars,
            spec=decision_input.spec,
        )
        no = evaluate_side(
            side="no",
            probability=1 - probability_yes,
            price=decision_input.executable_quotes.no_ask_dollars,
            spec=decision_input.spec,
        )
        valid_sides = [side for side in (yes, no) if side.valid and side.ev_dollars is not None]

        selected_side: Side | None = None
        selected_ev: float | None = None
        selected_price: float | None = None
        intended_quantity = 0
        skip_reason: str | None = None

        if not valid_sides:
            skip_reason = "missing_executable_quote"
        else:
            best = max(
                valid_sides,
                key=lambda side: (
                    side.ev_dollars if side.ev_dollars is not None else float("-inf"),
                    side.side,
                ),
            )
            selected_ev = best.ev_dollars
            selected_price = best.price_dollars
            if selected_ev is None or selected_ev <= decision_input.policy.min_ev_dollars:
                skip_reason = "ev_below_threshold"
            elif selected_price is None:
                skip_reason = "missing_executable_quote"
            else:
                intended_quantity = int(
                    Decimal(str(decision_input.policy.max_cost_dollars))
                    // Decimal(str(selected_price))
                )
                if intended_quantity < 1:
                    skip_reason = "insufficient_size_budget"
                else:
                    selected_side = best.side

        outcome: Literal["order_candidate", "skip"] = (
            "order_candidate" if selected_side is not None else "skip"
        )
        return DecisionResult(
            decision_id=f"dec_{uuid4().hex[:12]}",
            run_id=decision_input.feature_row.run_id,
            market_ticker=decision_input.feature_row.market_ticker,
            decision_timestamp=decision_input.feature_row.decision_timestamp,
            feature_row_id=decision_input.feature_row.feature_row_id,
            model_id=decision_input.model_output.model_id,
            probability_yes=probability_yes,
            selected_side=selected_side,
            selected_ev_dollars=selected_ev,
            selected_price_dollars=selected_price,
            intended_quantity=intended_quantity,
            max_cost_dollars=decision_input.policy.max_cost_dollars,
            outcome=outcome,
            skip_reason=skip_reason,
            side_evaluations=(yes, no),
        )


class DecisionRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def persist(self, result: DecisionResult) -> DecisionResult:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into decisions (
                        decision_id,
                        run_id,
                        market_ticker,
                        decision_timestamp,
                        outcome,
                        probability_yes,
                        selected_side,
                        skip_reason,
                        metadata
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (run_id, market_ticker) do nothing
                    returning *
                    """,
                    (
                        result.decision_id,
                        result.run_id,
                        result.market_ticker,
                        result.decision_timestamp,
                        result.outcome,
                        result.probability_yes,
                        result.selected_side,
                        result.skip_reason,
                        Jsonb(result_metadata(result)),
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    row = self._fetch_by_identity(cursor, result)
                    row = {**row, "inserted": False}
            connection.commit()
        return decision_row_to_result(row)

    def list(self, *, run_id: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[str] = []
        if run_id is not None:
            clauses.append("run_id = %s")
            params.append(run_id)
        where = f"where {' and '.join(clauses)}" if clauses else ""
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select
                        decision_id,
                        run_id,
                        market_ticker,
                        decision_timestamp,
                        outcome,
                        probability_yes,
                        selected_side,
                        skip_reason,
                        metadata
                    from decisions
                    {where}
                    order by decision_timestamp desc, decision_id desc
                    """,
                    params,
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get(self, decision_id: str) -> DecisionResult:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from decisions
                    where decision_id = %s
                    """,
                    (decision_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise KeyError(f"unknown decision_id: {decision_id}")
        return decision_row_to_result(row)

    def _fetch_by_identity(
        self,
        cursor: psycopg.Cursor,
        result: DecisionResult,
    ) -> Mapping[str, Any]:
        cursor.execute(
            """
            select *
            from decisions
            where run_id = %s and market_ticker = %s
            """,
            (result.run_id, result.market_ticker),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("decision conflict neither inserted nor found existing row")
        return row


def evaluate_side(
    *,
    side: Side,
    probability: float,
    price: float | None,
    spec: MarketSpec,
) -> SideEvaluation:
    if price is None:
        return SideEvaluation(
            side=side,
            probability=probability,
            price_dollars=None,
            fee_dollars=None,
            ev_dollars=None,
            valid=False,
            invalid_reason="missing_quote",
        )
    if price <= 0 or price >= 1:
        return SideEvaluation(
            side=side,
            probability=probability,
            price_dollars=price,
            fee_dollars=None,
            ev_dollars=None,
            valid=False,
            invalid_reason="invalid_quote",
        )
    fee = taker_fee_dollars(price, spec)
    ev = probability - price - fee
    return SideEvaluation(
        side=side,
        probability=probability,
        price_dollars=price,
        fee_dollars=fee,
        ev_dollars=ev,
        valid=True,
    )


def taker_fee_dollars(price: float, spec: MarketSpec) -> float:
    price_decimal = Decimal(str(price))
    multiplier = Decimal(str(spec.fee_assumptions.taker_fee_multiplier))
    return float(multiplier * price_decimal * (Decimal("1") - price_decimal))


def result_metadata(result: DecisionResult) -> dict[str, Any]:
    return {
        "engine_version": DecisionEngine.engine_version,
        "feature_row_id": result.feature_row_id,
        "model_id": result.model_id,
        "selected_ev_dollars": result.selected_ev_dollars,
        "selected_price_dollars": result.selected_price_dollars,
        "intended_quantity": result.intended_quantity,
        "max_cost_dollars": result.max_cost_dollars,
        "side_evaluations": [evaluation.as_dict() for evaluation in result.side_evaluations],
    }


def decision_row_to_result(row: Mapping[str, Any]) -> DecisionResult:
    values = dict(row)
    metadata = dict(values["metadata"])
    evaluations = tuple(
        SideEvaluation(
            side=evaluation["side"],
            probability=float(evaluation["probability"]),
            price_dollars=optional_float(evaluation["price_dollars"]),
            fee_dollars=optional_float(evaluation["fee_dollars"]),
            ev_dollars=optional_float(evaluation["ev_dollars"]),
            valid=bool(evaluation["valid"]),
            invalid_reason=evaluation["invalid_reason"],
        )
        for evaluation in metadata["side_evaluations"]
    )
    return DecisionResult(
        decision_id=str(values["decision_id"]),
        run_id=str(values["run_id"]),
        market_ticker=str(values["market_ticker"]),
        decision_timestamp=values["decision_timestamp"],
        feature_row_id=str(metadata["feature_row_id"]),
        model_id=str(metadata["model_id"]),
        probability_yes=float(values["probability_yes"]),
        selected_side=values["selected_side"],
        selected_ev_dollars=optional_float(metadata["selected_ev_dollars"]),
        selected_price_dollars=optional_float(metadata["selected_price_dollars"]),
        intended_quantity=int(metadata["intended_quantity"]),
        max_cost_dollars=float(metadata["max_cost_dollars"]),
        outcome=values["outcome"],
        skip_reason=values["skip_reason"],
        side_evaluations=evaluations,
        inserted=bool(values.get("inserted", True)),
    )


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def build_decision_input(
    *,
    spec: MarketSpec,
    feature_row: FeatureRow,
    probability_yes: float,
    yes_ask_dollars: float | None = None,
    no_ask_dollars: float | None = None,
    policy: DecisionPolicy | None = None,
) -> DecisionInput:
    quotes = ExecutableQuotes.from_feature_row(feature_row)
    if yes_ask_dollars is not None:
        quotes = ExecutableQuotes(yes_ask_dollars=yes_ask_dollars, no_ask_dollars=quotes.no_ask_dollars)
    if no_ask_dollars is not None:
        quotes = ExecutableQuotes(yes_ask_dollars=quotes.yes_ask_dollars, no_ask_dollars=no_ask_dollars)
    return DecisionInput(
        spec=spec,
        feature_row=feature_row,
        model_output=ModelOutput(
            probability_yes=probability_yes,
            model_id=feature_row.model_id,
            feature_row_id=feature_row.feature_row_id,
        ),
        executable_quotes=quotes,
        policy=policy or DecisionPolicy.from_spec(spec),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-decide")
    subparsers = parser.add_subparsers(dest="command", required=True)

    evaluate_parser = subparsers.add_parser("evaluate", help="Evaluate and persist one decision")
    evaluate_parser.add_argument("--feature-row-id", required=True)
    evaluate_parser.add_argument("--probability-yes", type=float, required=True)
    evaluate_parser.add_argument("--series", default="KXBTC15M")
    evaluate_parser.add_argument("--yes-ask-dollars", type=float, default=None)
    evaluate_parser.add_argument("--no-ask-dollars", type=float, default=None)

    list_parser = subparsers.add_parser("list", help="List persisted decisions")
    list_parser.add_argument("--run-id", default=None)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    OperationalStateRepository(settings.database_url).apply_migrations()
    repository = DecisionRepository(settings.database_url)

    if args.command == "evaluate":
        spec = default_market_registry().get(args.series)
        feature_row = FeatureLedgerRepository(settings.database_url).get(args.feature_row_id)
        decision_input = build_decision_input(
            spec=spec,
            feature_row=feature_row,
            probability_yes=args.probability_yes,
            yes_ask_dollars=args.yes_ask_dollars,
            no_ask_dollars=args.no_ask_dollars,
        )
        result = repository.persist(DecisionEngine().evaluate(decision_input))
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "list":
        print(json.dumps(repository.list(run_id=args.run_id), indent=2, sort_keys=True, default=str))
        return 0

    raise AssertionError(f"unhandled command: {args.command}")
