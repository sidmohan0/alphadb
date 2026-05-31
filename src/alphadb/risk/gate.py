"""Fail-closed risk gate and sizing tracer."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.config import settings_from_env
from alphadb.decision_engine.engine import DecisionRepository, DecisionResult
from alphadb.markets.registry import default_market_registry
from alphadb.markets.spec import MarketSpec
from alphadb.state.repository import OperationalStateRepository

RiskStatus = Literal["approved", "denied"]


@dataclass(frozen=True)
class RiskPolicy:
    max_daily_loss_dollars: float
    per_trade_max_cost_dollars: float
    fail_closed: bool
    time_in_force: str

    @classmethod
    def from_spec(cls, spec: MarketSpec) -> RiskPolicy:
        return cls(
            max_daily_loss_dollars=spec.risk_config.max_daily_loss_dollars,
            per_trade_max_cost_dollars=spec.risk_config.live_stake_cap_dollars,
            fail_closed=True,
            time_in_force=spec.trading_cutoffs.time_in_force,
        )


@dataclass(frozen=True)
class RiskState:
    trading_day: date
    realized_pnl_dollars: float


@dataclass(frozen=True)
class OrderIntentDraft:
    order_intent_id: str
    side: str
    price_dollars: float
    quantity: int
    max_cost_dollars: float
    time_in_force: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_intent_id": self.order_intent_id,
            "side": self.side,
            "price_dollars": self.price_dollars,
            "quantity": self.quantity,
            "max_cost_dollars": self.max_cost_dollars,
            "time_in_force": self.time_in_force,
        }


@dataclass(frozen=True)
class RiskDecisionResult:
    risk_decision_id: str
    decision_id: str
    status: RiskStatus
    reason: str | None
    order_intent: OrderIntentDraft | None
    payload: Mapping[str, Any]
    inserted: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk_decision_id": self.risk_decision_id,
            "decision_id": self.decision_id,
            "status": self.status,
            "reason": self.reason,
            "order_intent": None if self.order_intent is None else self.order_intent.as_dict(),
            "payload": dict(self.payload),
            "inserted": self.inserted,
        }


class RiskGate:
    gate_version = "risk_gate.v1"

    def evaluate(
        self,
        *,
        decision: DecisionResult,
        policy: RiskPolicy,
        state: RiskState | None,
    ) -> RiskDecisionResult:
        payload: dict[str, Any] = {
            "gate_version": self.gate_version,
            "market_ticker": decision.market_ticker,
            "run_id": decision.run_id,
            "policy": {
                "max_daily_loss_dollars": policy.max_daily_loss_dollars,
                "per_trade_max_cost_dollars": policy.per_trade_max_cost_dollars,
                "fail_closed": policy.fail_closed,
            },
        }

        if state is None:
            if policy.fail_closed:
                return denied(decision, "missing_risk_state", payload)
            state = RiskState(trading_day=date.today(), realized_pnl_dollars=0.0)
        payload["state"] = {
            "trading_day": state.trading_day.isoformat(),
            "realized_pnl_dollars": state.realized_pnl_dollars,
        }

        realized_loss = max(0.0, -state.realized_pnl_dollars)
        if realized_loss >= policy.max_daily_loss_dollars:
            return denied(decision, "daily_loss_limit", payload)
        if decision.outcome != "order_candidate":
            return denied(decision, "decision_skip", payload)
        if decision.selected_side is None or decision.selected_price_dollars is None:
            return denied(decision, "missing_order_candidate", payload)

        quantity = risk_sized_quantity(
            decision_quantity=decision.intended_quantity,
            selected_price_dollars=decision.selected_price_dollars,
            per_trade_max_cost_dollars=policy.per_trade_max_cost_dollars,
        )
        if quantity < 1:
            return denied(decision, "per_trade_limit", payload)

        max_cost = float(Decimal(str(quantity)) * Decimal(str(decision.selected_price_dollars)))
        payload["sizing"] = {
            "decision_quantity": decision.intended_quantity,
            "approved_quantity": quantity,
            "selected_price_dollars": decision.selected_price_dollars,
            "max_cost_dollars": max_cost,
        }
        return RiskDecisionResult(
            risk_decision_id=f"risk_{uuid4().hex[:12]}",
            decision_id=decision.decision_id,
            status="approved",
            reason=None,
            order_intent=OrderIntentDraft(
                order_intent_id=f"intent_{uuid4().hex[:12]}",
                side=decision.selected_side,
                price_dollars=decision.selected_price_dollars,
                quantity=quantity,
                max_cost_dollars=max_cost,
                time_in_force=policy.time_in_force,
            ),
            payload=payload,
        )


class RiskDecisionRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def persist(self, result: RiskDecisionResult) -> RiskDecisionResult:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into risk_decisions (
                        risk_decision_id, decision_id, status, reason, payload
                    )
                    values (%s, %s, %s, %s, %s)
                    on conflict (decision_id) do nothing
                    returning *
                    """,
                    (
                        result.risk_decision_id,
                        result.decision_id,
                        result.status,
                        result.reason,
                        Jsonb(dict(result.payload)),
                    ),
                )
                row = cursor.fetchone()
                inserted = row is not None
                if row is not None and result.order_intent is not None:
                    cursor.execute(
                        """
                        insert into order_intents (
                            order_intent_id,
                            risk_decision_id,
                            side,
                            price,
                            quantity,
                            max_cost_dollars,
                            time_in_force
                        )
                        values (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            result.order_intent.order_intent_id,
                            result.risk_decision_id,
                            result.order_intent.side,
                            result.order_intent.price_dollars,
                            result.order_intent.quantity,
                            result.order_intent.max_cost_dollars,
                            result.order_intent.time_in_force,
                        ),
                    )
                stored = self._fetch_by_decision_id(cursor, result.decision_id)
                stored = {**stored, "inserted": inserted}
            connection.commit()
        return row_to_risk_decision(stored)

    def list(self, *, decision_id: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[str] = []
        if decision_id is not None:
            clauses.append("rd.decision_id = %s")
            params.append(decision_id)
        where = f"where {' and '.join(clauses)}" if clauses else ""
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select
                        rd.risk_decision_id,
                        rd.decision_id,
                        d.run_id,
                        d.market_ticker,
                        rd.status,
                        rd.reason,
                        rd.payload,
                        oi.order_intent_id,
                        oi.side,
                        oi.price,
                        oi.quantity,
                        oi.max_cost_dollars,
                        oi.time_in_force
                    from risk_decisions rd
                    join decisions d on d.decision_id = rd.decision_id
                    left join order_intents oi on oi.risk_decision_id = rd.risk_decision_id
                    {where}
                    order by rd.created_at desc, rd.risk_decision_id desc
                    """,
                    params,
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _fetch_by_decision_id(
        self,
        cursor: psycopg.Cursor,
        decision_id: str,
    ) -> Mapping[str, Any]:
        cursor.execute(
            """
            select
                rd.*,
                oi.order_intent_id,
                oi.side,
                oi.price,
                oi.quantity,
                oi.max_cost_dollars,
                oi.time_in_force
            from risk_decisions rd
            left join order_intents oi on oi.risk_decision_id = rd.risk_decision_id
            where rd.decision_id = %s
            """,
            (decision_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("risk decision conflict neither inserted nor found existing row")
        return row


def denied(
    decision: DecisionResult,
    reason: str,
    payload: Mapping[str, Any],
) -> RiskDecisionResult:
    return RiskDecisionResult(
        risk_decision_id=f"risk_{uuid4().hex[:12]}",
        decision_id=decision.decision_id,
        status="denied",
        reason=reason,
        order_intent=None,
        payload=payload,
    )


def risk_sized_quantity(
    *,
    decision_quantity: int,
    selected_price_dollars: float,
    per_trade_max_cost_dollars: float,
) -> int:
    if selected_price_dollars <= 0:
        return 0
    budget_quantity = int(
        Decimal(str(per_trade_max_cost_dollars)) // Decimal(str(selected_price_dollars))
    )
    return min(decision_quantity, budget_quantity)


def row_to_risk_decision(row: Mapping[str, Any]) -> RiskDecisionResult:
    values = dict(row)
    order_intent = None
    if values.get("order_intent_id") is not None:
        order_intent = OrderIntentDraft(
            order_intent_id=str(values["order_intent_id"]),
            side=str(values["side"]),
            price_dollars=float(values["price"]),
            quantity=int(values["quantity"]),
            max_cost_dollars=float(values["max_cost_dollars"]),
            time_in_force=str(values["time_in_force"]),
        )
    return RiskDecisionResult(
        risk_decision_id=str(values["risk_decision_id"]),
        decision_id=str(values["decision_id"]),
        status=values["status"],
        reason=values["reason"],
        order_intent=order_intent,
        payload=dict(values["payload"]),
        inserted=bool(values.get("inserted", True)),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-risk")
    subparsers = parser.add_subparsers(dest="command", required=True)

    evaluate_parser = subparsers.add_parser("evaluate", help="Evaluate and persist risk decision")
    evaluate_parser.add_argument("--decision-id", required=True)
    evaluate_parser.add_argument("--series", default="KXBTC15M")
    evaluate_parser.add_argument("--realized-pnl-dollars", type=float, default=0.0)
    evaluate_parser.add_argument("--trading-day", default=None)

    list_parser = subparsers.add_parser("list", help="List risk decisions")
    list_parser.add_argument("--decision-id", default=None)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    OperationalStateRepository(settings.database_url).apply_migrations()
    repository = RiskDecisionRepository(settings.database_url)

    if args.command == "evaluate":
        spec = default_market_registry().get(args.series)
        trading_day = date.fromisoformat(args.trading_day) if args.trading_day else date.today()
        decision = DecisionRepository(settings.database_url).get(args.decision_id)
        result = RiskGate().evaluate(
            decision=decision,
            policy=RiskPolicy.from_spec(spec),
            state=RiskState(
                trading_day=trading_day,
                realized_pnl_dollars=args.realized_pnl_dollars,
            ),
        )
        print(json.dumps(repository.persist(result).as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "list":
        print(
            json.dumps(
                repository.list(decision_id=args.decision_id),
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return 0

    raise AssertionError(f"unhandled command: {args.command}")
