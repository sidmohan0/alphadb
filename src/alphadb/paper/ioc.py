"""Paper taker-only IOC execution and reconciliation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.config import settings_from_env
from alphadb.state.repository import OperationalStateRepository

PaperOrderStatus = Literal["filled", "partial", "unfilled"]


@dataclass(frozen=True)
class ApprovedOrderIntent:
    order_intent_id: str
    risk_decision_id: str
    market_ticker: str
    side: Literal["yes", "no"]
    limit_price_dollars: float
    quantity: int
    max_cost_dollars: float
    time_in_force: str


@dataclass(frozen=True)
class PaperLiquidity:
    side: Literal["yes", "no"]
    available_price_dollars: float | None
    available_quantity: int
    mark_price_dollars: float | None = None


@dataclass(frozen=True)
class PaperExecutionResult:
    paper_order_id: str
    order_intent_id: str
    market_ticker: str
    side: Literal["yes", "no"]
    status: PaperOrderStatus
    limit_price_dollars: float
    requested_quantity: int
    filled_quantity: int
    fill_price_dollars: float | None
    position_quantity: int
    realized_pnl_dollars: float
    unrealized_pnl_dollars: float
    reconciliation_id: str
    live_orders_sent: int = 0
    inserted: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "paper_order_id": self.paper_order_id,
            "order_intent_id": self.order_intent_id,
            "market_ticker": self.market_ticker,
            "side": self.side,
            "status": self.status,
            "limit_price_dollars": self.limit_price_dollars,
            "requested_quantity": self.requested_quantity,
            "filled_quantity": self.filled_quantity,
            "fill_price_dollars": self.fill_price_dollars,
            "position_quantity": self.position_quantity,
            "realized_pnl_dollars": self.realized_pnl_dollars,
            "unrealized_pnl_dollars": self.unrealized_pnl_dollars,
            "reconciliation_id": self.reconciliation_id,
            "live_orders_sent": self.live_orders_sent,
            "inserted": self.inserted,
        }


class PaperIocExecutor:
    execution_mode = "paper"
    live_order_client = None

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.repository = PaperExecutionRepository(database_url)

    def execute(
        self,
        *,
        order_intent_id: str,
        liquidity: PaperLiquidity,
        executed_at: datetime | None = None,
    ) -> PaperExecutionResult:
        executed_at = executed_at or datetime.now(UTC)
        intent = self.repository.get_approved_order_intent(order_intent_id)
        filled_quantity, status, fill_price = simulate_ioc(intent, liquidity)
        mark_price = liquidity.mark_price_dollars if liquidity.mark_price_dollars is not None else fill_price
        return self.repository.persist_execution(
            intent=intent,
            liquidity=liquidity,
            status=status,
            filled_quantity=filled_quantity,
            fill_price_dollars=fill_price,
            mark_price_dollars=mark_price,
            executed_at=executed_at,
        )


class PaperExecutionRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def get_approved_order_intent(self, order_intent_id: str) -> ApprovedOrderIntent:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        oi.order_intent_id,
                        oi.risk_decision_id,
                        d.market_ticker,
                        oi.side,
                        oi.price,
                        oi.quantity,
                        oi.max_cost_dollars,
                        oi.time_in_force,
                        rd.status as risk_status
                    from order_intents oi
                    join risk_decisions rd on rd.risk_decision_id = oi.risk_decision_id
                    join decisions d on d.decision_id = rd.decision_id
                    where oi.order_intent_id = %s
                    """,
                    (order_intent_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise KeyError(f"unknown order_intent_id: {order_intent_id}")
        if row["risk_status"] != "approved":
            raise ValueError(f"order intent is not risk-approved: {order_intent_id}")
        return ApprovedOrderIntent(
            order_intent_id=str(row["order_intent_id"]),
            risk_decision_id=str(row["risk_decision_id"]),
            market_ticker=str(row["market_ticker"]),
            side=row["side"],
            limit_price_dollars=float(row["price"]),
            quantity=int(row["quantity"]),
            max_cost_dollars=float(row["max_cost_dollars"]),
            time_in_force=str(row["time_in_force"]),
        )

    def persist_execution(
        self,
        *,
        intent: ApprovedOrderIntent,
        liquidity: PaperLiquidity,
        status: PaperOrderStatus,
        filled_quantity: int,
        fill_price_dollars: float | None,
        mark_price_dollars: float | None,
        executed_at: datetime,
    ) -> PaperExecutionResult:
        paper_order_id = f"paper_order_{uuid4().hex[:12]}"
        reconciliation_id = f"recon_{uuid4().hex[:12]}"
        position_quantity = 0
        realized_pnl = Decimal("0")
        unrealized_pnl = Decimal("0")

        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into paper_orders (
                        paper_order_id,
                        order_intent_id,
                        risk_decision_id,
                        market_ticker,
                        side,
                        limit_price,
                        quantity,
                        filled_quantity,
                        status,
                        time_in_force,
                        submitted_at,
                        metadata
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (order_intent_id) do nothing
                    returning paper_order_id
                    """,
                    (
                        paper_order_id,
                        intent.order_intent_id,
                        intent.risk_decision_id,
                        intent.market_ticker,
                        intent.side,
                        intent.limit_price_dollars,
                        intent.quantity,
                        filled_quantity,
                        status,
                        intent.time_in_force,
                        executed_at,
                        Jsonb(
                            {
                                "execution_mode": PaperIocExecutor.execution_mode,
                                "liquidity": liquidity.__dict__,
                            }
                        ),
                    ),
                )
                inserted_row = cursor.fetchone()
                inserted = inserted_row is not None
                if inserted and filled_quantity > 0 and fill_price_dollars is not None:
                    paper_fill_id = f"paper_fill_{uuid4().hex[:12]}"
                    cursor.execute(
                        """
                        insert into paper_fills (
                            paper_fill_id,
                            paper_order_id,
                            market_ticker,
                            side,
                            fill_price,
                            quantity,
                            liquidity_role,
                            filled_at,
                            fee_dollars,
                            metadata
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            paper_fill_id,
                            paper_order_id,
                            intent.market_ticker,
                            intent.side,
                            fill_price_dollars,
                            filled_quantity,
                            "taker",
                            executed_at,
                            0,
                            Jsonb({"paper_order_id": paper_order_id}),
                        ),
                    )
                    position_quantity, realized_pnl, unrealized_pnl = self._upsert_position(
                        cursor=cursor,
                        intent=intent,
                        fill_price_dollars=fill_price_dollars,
                        filled_quantity=filled_quantity,
                        mark_price_dollars=mark_price_dollars,
                        updated_at=executed_at,
                    )
                if inserted:
                    cursor.execute(
                        """
                        insert into paper_reconciliations (
                            reconciliation_id,
                            paper_order_id,
                            status,
                            expected_quantity,
                            filled_quantity,
                            open_quantity,
                            realized_pnl_dollars,
                            unrealized_pnl_dollars,
                            metadata
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            reconciliation_id,
                            paper_order_id,
                            status,
                            intent.quantity,
                            filled_quantity,
                            intent.quantity - filled_quantity,
                            realized_pnl,
                            unrealized_pnl,
                            Jsonb({"execution_mode": PaperIocExecutor.execution_mode}),
                        ),
                    )
                stored = self._fetch_execution(cursor, intent.order_intent_id)
                stored = {**stored, "inserted": inserted}
            connection.commit()
        return row_to_execution_result(stored)

    def list_orders(self) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from paper_orders
                    order by submitted_at desc, paper_order_id desc
                    """
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def list_fills(self) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from paper_fills
                    order by filled_at desc, paper_fill_id desc
                    """
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def list_positions(self) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from paper_positions
                    order by updated_at desc, position_id desc
                    """
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def list_reconciliations(self) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from paper_reconciliations
                    order by created_at desc, reconciliation_id desc
                    """
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _upsert_position(
        self,
        *,
        cursor: psycopg.Cursor,
        intent: ApprovedOrderIntent,
        fill_price_dollars: float,
        filled_quantity: int,
        mark_price_dollars: float | None,
        updated_at: datetime,
    ) -> tuple[int, Decimal, Decimal]:
        fill_price = Decimal(str(fill_price_dollars))
        mark_price = Decimal(str(mark_price_dollars if mark_price_dollars is not None else fill_price))
        cursor.execute(
            """
            select *
            from paper_positions
            where market_ticker = %s and side = %s
            for update
            """,
            (intent.market_ticker, intent.side),
        )
        existing = cursor.fetchone()
        if existing is None:
            position_id = f"position_{uuid4().hex[:12]}"
            quantity = filled_quantity
            avg_price = fill_price
            realized_pnl = Decimal("0")
        else:
            position_id = str(existing["position_id"])
            old_quantity = int(existing["quantity"])
            old_avg = Decimal(str(existing["avg_price"]))
            quantity = old_quantity + filled_quantity
            avg_price = (
                (old_avg * Decimal(old_quantity)) + (fill_price * Decimal(filled_quantity))
            ) / Decimal(quantity)
            realized_pnl = Decimal(str(existing["realized_pnl_dollars"]))
        unrealized_pnl = (mark_price - avg_price) * Decimal(quantity)
        cursor.execute(
            """
            insert into paper_positions (
                position_id,
                market_ticker,
                side,
                quantity,
                avg_price,
                realized_pnl_dollars,
                unrealized_pnl_dollars,
                updated_at,
                metadata
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (market_ticker, side) do update set
                quantity = excluded.quantity,
                avg_price = excluded.avg_price,
                realized_pnl_dollars = excluded.realized_pnl_dollars,
                unrealized_pnl_dollars = excluded.unrealized_pnl_dollars,
                updated_at = excluded.updated_at,
                metadata = excluded.metadata
            """,
            (
                position_id,
                intent.market_ticker,
                intent.side,
                quantity,
                avg_price,
                realized_pnl,
                unrealized_pnl,
                updated_at,
                Jsonb({"execution_mode": PaperIocExecutor.execution_mode}),
            ),
        )
        return quantity, realized_pnl, unrealized_pnl

    def _fetch_execution(
        self,
        cursor: psycopg.Cursor,
        order_intent_id: str,
    ) -> Mapping[str, Any]:
        cursor.execute(
            """
            select
                po.paper_order_id,
                po.order_intent_id,
                po.market_ticker,
                po.side,
                po.status,
                po.limit_price,
                po.quantity,
                po.filled_quantity,
                pf.fill_price,
                coalesce(pp.quantity, 0) as position_quantity,
                pr.realized_pnl_dollars,
                pr.unrealized_pnl_dollars,
                pr.reconciliation_id
            from paper_orders po
            left join paper_fills pf on pf.paper_order_id = po.paper_order_id
            left join paper_positions pp
                on pp.market_ticker = po.market_ticker and pp.side = po.side
            join paper_reconciliations pr on pr.paper_order_id = po.paper_order_id
            where po.order_intent_id = %s
            """,
            (order_intent_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("paper execution neither inserted nor found existing row")
        return row


def simulate_ioc(
    intent: ApprovedOrderIntent,
    liquidity: PaperLiquidity,
) -> tuple[int, PaperOrderStatus, float | None]:
    if liquidity.side != intent.side:
        return 0, "unfilled", None
    if liquidity.available_price_dollars is None or liquidity.available_quantity <= 0:
        return 0, "unfilled", None
    if liquidity.available_price_dollars > intent.limit_price_dollars:
        return 0, "unfilled", None
    filled_quantity = min(intent.quantity, liquidity.available_quantity)
    status: PaperOrderStatus = "filled" if filled_quantity == intent.quantity else "partial"
    return filled_quantity, status, liquidity.available_price_dollars


def row_to_execution_result(row: Mapping[str, Any]) -> PaperExecutionResult:
    values = dict(row)
    fill_price = values.get("fill_price")
    return PaperExecutionResult(
        paper_order_id=str(values["paper_order_id"]),
        order_intent_id=str(values["order_intent_id"]),
        market_ticker=str(values["market_ticker"]),
        side=values["side"],
        status=values["status"],
        limit_price_dollars=float(values["limit_price"]),
        requested_quantity=int(values["quantity"]),
        filled_quantity=int(values["filled_quantity"]),
        fill_price_dollars=None if fill_price is None else float(fill_price),
        position_quantity=int(values["position_quantity"]),
        realized_pnl_dollars=float(values["realized_pnl_dollars"]),
        unrealized_pnl_dollars=float(values["unrealized_pnl_dollars"]),
        reconciliation_id=str(values["reconciliation_id"]),
        inserted=bool(values.get("inserted", True)),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-paper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    execute_parser = subparsers.add_parser("execute", help="Execute one paper IOC order")
    execute_parser.add_argument("--order-intent-id", required=True)
    execute_parser.add_argument("--side", choices=("yes", "no"), required=True)
    execute_parser.add_argument("--available-price-dollars", type=float, default=None)
    execute_parser.add_argument("--available-quantity", type=int, default=0)
    execute_parser.add_argument("--mark-price-dollars", type=float, default=None)

    subparsers.add_parser("status", help="Show paper orders, fills, positions, and PnL")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    OperationalStateRepository(settings.database_url).apply_migrations()
    repository = PaperExecutionRepository(settings.database_url)

    if args.command == "execute":
        result = PaperIocExecutor(settings.database_url).execute(
            order_intent_id=args.order_intent_id,
            liquidity=PaperLiquidity(
                side=args.side,
                available_price_dollars=args.available_price_dollars,
                available_quantity=args.available_quantity,
                mark_price_dollars=args.mark_price_dollars,
            ),
        )
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "status":
        print(
            json.dumps(
                {
                    "orders": repository.list_orders(),
                    "fills": repository.list_fills(),
                    "positions": repository.list_positions(),
                    "reconciliations": repository.list_reconciliations(),
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return 0

    raise AssertionError(f"unhandled command: {args.command}")
