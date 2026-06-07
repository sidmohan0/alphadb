"""Cockpit performance summaries backed by Operational State."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from alphadb.live_runtime import FAIR_VALUE_LIVE_STRATEGY
from alphadb.state.repository import OperationalStateRepository


PERFORMANCE_SCHEMA_VERSION = "alphadb_performance_summary.v1"
DEFAULT_MARKET_SERIES = "KXBTC15M"
PERFORMANCE_STALE_AFTER_SECONDS = 300
DEFAULT_RECENT_RUN_LIMIT = 25
DEFAULT_PAPER_ROW_LIMIT = 500


class PerformanceSummaryRepository:
    """Read-only Operational State projection for Cockpit Performance."""

    def __init__(self, database_url: str):
        self.database_url = database_url

    def summary(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        market_series: str = DEFAULT_MARKET_SERIES,
        recent_limit: int = DEFAULT_RECENT_RUN_LIMIT,
    ) -> dict[str, Any]:
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                config_row = _active_config_row(cursor, strategy=strategy)
                status_rows = _recent_status_rows(
                    cursor,
                    strategy=strategy,
                    limit=recent_limit,
                )
                if strategy == FAIR_VALUE_LIVE_STRATEGY:
                    order_rows = _paper_order_rows(
                        cursor,
                        market_series=market_series,
                        limit=DEFAULT_PAPER_ROW_LIMIT,
                    )
                    fill_rows = _paper_fill_rows(
                        cursor,
                        market_series=market_series,
                        limit=DEFAULT_PAPER_ROW_LIMIT,
                    )
                    position_rows = _paper_position_rows(
                        cursor,
                        market_series=market_series,
                        limit=DEFAULT_PAPER_ROW_LIMIT,
                    )
                else:
                    order_rows = []
                    fill_rows = []
                    position_rows = []
        return build_performance_summary(
            strategy=strategy,
            market_series=market_series,
            generated_at=datetime.now(UTC),
            config_row=config_row,
            status_rows=status_rows,
            order_rows=order_rows,
            fill_rows=fill_rows,
            position_rows=position_rows,
        )


def build_performance_summary(
    *,
    strategy: str,
    market_series: str,
    generated_at: datetime,
    config_row: Mapping[str, Any] | None = None,
    status_rows: Sequence[Mapping[str, Any]] = (),
    order_rows: Sequence[Mapping[str, Any]] = (),
    fill_rows: Sequence[Mapping[str, Any]] = (),
    position_rows: Sequence[Mapping[str, Any]] = (),
    stale_after_seconds: int = PERFORMANCE_STALE_AFTER_SECONDS,
) -> dict[str, Any]:
    rows = [dict(row) for row in status_rows]
    execution = summarize_execution(rows)
    pnl = summarize_pnl(
        order_rows=order_rows,
        fill_rows=fill_rows,
        position_rows=position_rows,
    )
    freshness = summarize_freshness(
        rows,
        generated_at=generated_at,
        stale_after_seconds=stale_after_seconds,
    )
    risk_budget = summarize_risk_budget(rows)
    data_status = _overall_data_status(execution, pnl, freshness)
    return {
        "schema_version": PERFORMANCE_SCHEMA_VERSION,
        "strategy": strategy,
        "market_series": market_series,
        "generated_at_utc": _iso(generated_at),
        "data_status": data_status,
        "data_status_detail": _data_status_detail(data_status, execution, pnl, freshness),
        "config": _config_payload(config_row),
        "freshness": freshness,
        "risk_budget": risk_budget,
        "execution": execution,
        "pnl": pnl,
        "recent_runs": execution["recent_runs"],
    }


def summarize_execution(status_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(row) for row in status_rows]
    counts = {
        "submitted": 0,
        "skipped": 0,
        "rejected": 0,
        "filled": 0,
        "no_fill": 0,
        "unknown": 0,
    }
    skip_reasons: Counter[str] = Counter()

    if rows:
        total_attempts = sum(_int(row.get("recent_attempt_count")) for row in rows)
        if total_attempts:
            counts["submitted"] = sum(_int(row.get("recent_submitted_count")) for row in rows)
            counts["skipped"] = sum(_int(row.get("recent_skipped_count")) for row in rows)
            counts["filled"] = sum(_int(row.get("recent_filled_count")) for row in rows)
            counts["no_fill"] = sum(_int(row.get("recent_no_fill_count")) for row in rows)
            counts["rejected"] = sum(
                1
                for row in rows
                if _text(row.get("latest_attempt_status")) in {"rejected", "error"}
            )
            counts["unknown"] = max(
                0,
                total_attempts
                - counts["submitted"]
                - counts["skipped"]
                - counts["rejected"],
            )
        else:
            for row in rows:
                _add_single_run_execution_count(counts, row)

        for row in rows:
            reason = _skip_reason(row)
            if reason:
                skip_reasons[reason] += 1

    return {
        "data_status": "ok" if rows else "empty",
        "data_status_detail": "Recent live run statuses found."
        if rows
        else "No live run statuses recorded.",
        "counts": counts,
        "skip_reasons": [
            {"reason": reason, "count": count}
            for reason, count in sorted(
                skip_reasons.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
        "recent_runs": [_recent_run_payload(row) for row in rows],
    }


def summarize_pnl(
    *,
    order_rows: Sequence[Mapping[str, Any]] = (),
    fill_rows: Sequence[Mapping[str, Any]] = (),
    position_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    orders = [dict(row) for row in order_rows]
    fills = [dict(row) for row in fill_rows]
    positions = [dict(row) for row in position_rows]
    observations = bool(orders or fills or positions)
    if not observations:
        return {
            "status": "unavailable",
            "status_detail": "No paper execution, fill, or position rows recorded.",
            "settlement_state": "unavailable",
            "fees_status": "unavailable",
            "net_pnl_dollars": None,
            "realized_pnl_dollars": None,
            "unrealized_pnl_dollars": None,
            "fees_dollars": None,
            "unsettled_exposure_dollars": None,
            "filled_contracts": 0,
            "order_count": 0,
            "fill_count": 0,
            "position_count": 0,
            "latest_observed_at_utc": None,
            "reconciliation_counts": {},
        }

    realized = _sum_field(orders, "reconciliation_realized_pnl_dollars")
    unrealized = _sum_field(orders, "reconciliation_unrealized_pnl_dollars")
    if realized is None:
        realized = _sum_field(positions, "realized_pnl_dollars")
    if unrealized is None:
        unrealized = _sum_field(positions, "unrealized_pnl_dollars")

    filled_contracts = _filled_contracts(orders=orders, fills=fills)
    fees = _sum_field(fills, "fee_dollars")
    fees_status = "available" if fills else "unavailable"
    if fees is None and filled_contracts == 0:
        fees = 0.0
        fees_status = "not_applicable"

    settlement_state = _settlement_state(orders=orders, positions=positions)
    unsettled_exposure = _unsettled_exposure(orders=orders, positions=positions)
    net_pnl = None
    if realized is not None and unrealized is not None and fees is not None:
        net_pnl = realized + unrealized - fees

    status = "ok"
    detail = "Paper performance rows are available."
    if net_pnl is None or fees_status == "unavailable" or settlement_state in {
        "partial",
        "unknown",
    }:
        status = "partial"
        detail = "Some PnL, fee, or settlement fields are unavailable."

    return {
        "status": status,
        "status_detail": detail,
        "settlement_state": settlement_state,
        "fees_status": fees_status,
        "net_pnl_dollars": _money(net_pnl),
        "realized_pnl_dollars": _money(realized),
        "unrealized_pnl_dollars": _money(unrealized),
        "fees_dollars": _money(fees),
        "unsettled_exposure_dollars": _money(unsettled_exposure),
        "filled_contracts": filled_contracts,
        "order_count": len(orders),
        "fill_count": len(fills),
        "position_count": len(positions),
        "latest_observed_at_utc": _iso(_latest_observed_at(orders, fills, positions)),
        "reconciliation_counts": dict(
            sorted(
                Counter(_order_reconciliation_status(row) for row in orders).items(),
                key=lambda item: item[0],
            )
        ),
    }


def summarize_freshness(
    status_rows: Sequence[Mapping[str, Any]],
    *,
    generated_at: datetime,
    stale_after_seconds: int = PERFORMANCE_STALE_AFTER_SECONDS,
) -> dict[str, Any]:
    latest = _datetime(status_rows[0].get("generated_at")) if status_rows else None
    if latest is None:
        return {
            "status": "empty",
            "latest_run_generated_at_utc": None,
            "age_seconds": None,
            "stale": False,
            "stale_after_seconds": stale_after_seconds,
        }
    age_seconds = max(0, int((generated_at - latest).total_seconds()))
    stale = age_seconds > stale_after_seconds
    return {
        "status": "stale" if stale else "fresh",
        "latest_run_generated_at_utc": _iso(latest),
        "age_seconds": age_seconds,
        "stale": stale,
        "stale_after_seconds": stale_after_seconds,
    }


def summarize_risk_budget(status_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not status_rows:
        return {
            "status": "unavailable",
            "daily_loss_used_dollars": None,
            "daily_loss_limit_dollars": None,
            "daily_loss_remaining_dollars": None,
            "daily_loss_usage_fraction": None,
            "market_exposure_used_dollars": None,
            "market_exposure_limit_dollars": None,
            "market_exposure_usage_fraction": None,
        }
    latest = status_rows[0]
    daily_used = _float(latest.get("daily_loss_used_dollars"))
    daily_limit = _float(latest.get("daily_loss_limit_dollars"))
    market_used = _float(latest.get("market_exposure_used_dollars"))
    market_limit = _float(latest.get("market_exposure_limit_dollars"))
    return {
        "status": "ok",
        "daily_loss_used_dollars": _money(daily_used),
        "daily_loss_limit_dollars": _money(daily_limit),
        "daily_loss_remaining_dollars": _money(_remaining(daily_limit, daily_used)),
        "daily_loss_usage_fraction": _fraction(daily_used, daily_limit),
        "market_exposure_used_dollars": _money(market_used),
        "market_exposure_limit_dollars": _money(market_limit),
        "market_exposure_usage_fraction": _fraction(market_used, market_limit),
    }


def _active_config_row(
    cursor: psycopg.Cursor,
    *,
    strategy: str,
) -> Mapping[str, Any] | None:
    cursor.execute(
        """
        select
            config_id,
            strategy,
            version,
            is_active,
            max_order_dollars,
            max_market_exposure_dollars,
            max_daily_loss_dollars,
            min_edge,
            min_contract_price,
            max_markets,
            created_at
        from live_runtime_configs
        where strategy = %s
        order by is_active desc, version desc
        limit 1
        """,
        (strategy,),
    )
    return cursor.fetchone()


def _recent_status_rows(
    cursor: psycopg.Cursor,
    *,
    strategy: str,
    limit: int,
) -> list[Mapping[str, Any]]:
    cursor.execute(
        """
        select
            run_id,
            strategy,
            generated_at,
            config_id,
            config_version,
            current_market_ticker,
            decision_outcome,
            selected_side,
            skip_reason,
            latest_attempt_status,
            latest_attempt_reason,
            fill_status,
            daily_loss_used_dollars,
            daily_loss_limit_dollars,
            market_exposure_used_dollars,
            market_exposure_limit_dollars,
            recent_attempt_count,
            recent_submitted_count,
            recent_skipped_count,
            recent_no_fill_count,
            recent_filled_count
        from live_run_statuses
        where strategy = %s
        order by generated_at desc, run_id desc
        limit %s
        """,
        (strategy, limit),
    )
    return cursor.fetchall()


def _paper_order_rows(
    cursor: psycopg.Cursor,
    *,
    market_series: str,
    limit: int,
) -> list[Mapping[str, Any]]:
    cursor.execute(
        """
        select
            po.paper_order_id,
            po.market_ticker,
            po.status,
            po.limit_price,
            po.quantity,
            po.filled_quantity,
            po.submitted_at,
            pr.status as reconciliation_status,
            pr.expected_quantity as reconciliation_expected_quantity,
            pr.filled_quantity as reconciliation_filled_quantity,
            pr.open_quantity as reconciliation_open_quantity,
            pr.realized_pnl_dollars as reconciliation_realized_pnl_dollars,
            pr.unrealized_pnl_dollars as reconciliation_unrealized_pnl_dollars,
            pr.created_at as reconciliation_created_at
        from paper_orders po
        left join paper_reconciliations pr on pr.paper_order_id = po.paper_order_id
        where po.market_ticker = %s or po.market_ticker like %s
        order by po.submitted_at desc, po.paper_order_id desc
        limit %s
        """,
        (market_series, f"{market_series}-%", limit),
    )
    return cursor.fetchall()


def _paper_fill_rows(
    cursor: psycopg.Cursor,
    *,
    market_series: str,
    limit: int,
) -> list[Mapping[str, Any]]:
    cursor.execute(
        """
        select
            paper_fill_id,
            market_ticker,
            quantity,
            fill_price,
            fee_dollars,
            filled_at
        from paper_fills
        where market_ticker = %s or market_ticker like %s
        order by filled_at desc, paper_fill_id desc
        limit %s
        """,
        (market_series, f"{market_series}-%", limit),
    )
    return cursor.fetchall()


def _paper_position_rows(
    cursor: psycopg.Cursor,
    *,
    market_series: str,
    limit: int,
) -> list[Mapping[str, Any]]:
    cursor.execute(
        """
        select
            position_id,
            market_ticker,
            side,
            quantity,
            avg_price,
            realized_pnl_dollars,
            unrealized_pnl_dollars,
            updated_at
        from paper_positions
        where market_ticker = %s or market_ticker like %s
        order by updated_at desc, position_id desc
        limit %s
        """,
        (market_series, f"{market_series}-%", limit),
    )
    return cursor.fetchall()


def _config_payload(row: Mapping[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {
            "status": "missing",
            "config_id": None,
            "version": None,
            "is_active": False,
            "created_at_utc": None,
            "limits": {},
        }
    return {
        "status": "ok" if bool(row.get("is_active")) else "inactive_latest",
        "config_id": _text(row.get("config_id")),
        "version": _int_or_none(row.get("version")),
        "is_active": bool(row.get("is_active")),
        "created_at_utc": _iso(_datetime(row.get("created_at"))),
        "limits": {
            "max_order_dollars": _money(_float(row.get("max_order_dollars"))),
            "max_market_exposure_dollars": _money(
                _float(row.get("max_market_exposure_dollars"))
            ),
            "max_daily_loss_dollars": _money(_float(row.get("max_daily_loss_dollars"))),
            "min_edge": _float(row.get("min_edge")),
            "min_contract_price": _float(row.get("min_contract_price")),
            "max_markets": _int_or_none(row.get("max_markets")),
        },
    }


def _add_single_run_execution_count(counts: dict[str, int], row: Mapping[str, Any]) -> None:
    outcome = _text(row.get("decision_outcome"))
    attempt_status = _text(row.get("latest_attempt_status"))
    fill_status = _text(row.get("fill_status"))
    if outcome == "skipped" or attempt_status == "skipped":
        counts["skipped"] += 1
        return
    if outcome in {"rejected", "error"} or attempt_status in {"rejected", "error"}:
        counts["rejected"] += 1
        return
    if outcome == "submitted" or attempt_status == "submitted":
        counts["submitted"] += 1
        if fill_status == "filled":
            counts["filled"] += 1
        elif fill_status == "no_fill":
            counts["no_fill"] += 1
        elif fill_status in {None, "submitted_fill_unknown"}:
            counts["unknown"] += 1
        return
    if outcome not in {None, "no_recent_run"}:
        counts["unknown"] += 1


def _recent_run_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "run_id": _text(row.get("run_id")),
        "generated_at_utc": _iso(_datetime(row.get("generated_at"))),
        "market_ticker": _text(row.get("current_market_ticker")),
        "decision_outcome": _text(row.get("decision_outcome")),
        "selected_side": _text(row.get("selected_side")),
        "skip_reason": _text(row.get("skip_reason")),
        "attempt_status": _text(row.get("latest_attempt_status")),
        "attempt_reason": _text(row.get("latest_attempt_reason")),
        "fill_status": _text(row.get("fill_status")),
        "config_version": _int_or_none(row.get("config_version")),
        "daily_loss_used_dollars": _money(_float(row.get("daily_loss_used_dollars"))),
        "market_exposure_used_dollars": _money(
            _float(row.get("market_exposure_used_dollars"))
        ),
    }


def _skip_reason(row: Mapping[str, Any]) -> str | None:
    outcome = _text(row.get("decision_outcome"))
    attempt_status = _text(row.get("latest_attempt_status"))
    if outcome != "skipped" and attempt_status != "skipped":
        return None
    return _text(row.get("skip_reason")) or _text(row.get("latest_attempt_reason"))


def _settlement_state(
    *,
    orders: Sequence[Mapping[str, Any]],
    positions: Sequence[Mapping[str, Any]],
) -> str:
    if not orders:
        return "unknown" if positions else "unavailable"
    statuses = {_order_reconciliation_status(row) for row in orders}
    if "unknown" in statuses:
        return "unknown"
    if any(
        _order_reconciliation_status(row) == "partial"
        or (
            _order_reconciliation_status(row) not in {"unfilled", "no_fill"}
            and _int(row.get("reconciliation_open_quantity")) > 0
        )
        for row in orders
    ):
        return "partial"
    return "complete"


def _order_reconciliation_status(row: Mapping[str, Any]) -> str:
    status = _text(row.get("reconciliation_status")) or _text(row.get("status"))
    if status in {"unfilled", "no_fill"}:
        return "unfilled"
    if status in {"filled", "settled", "complete"}:
        return "filled"
    if status == "partial":
        return "partial"
    return "unknown"


def _filled_contracts(
    *,
    orders: Sequence[Mapping[str, Any]],
    fills: Sequence[Mapping[str, Any]],
) -> int:
    if fills:
        return sum(_int(row.get("quantity")) for row in fills)
    return sum(
        _int(row.get("reconciliation_filled_quantity") or row.get("filled_quantity"))
        for row in orders
    )


def _unsettled_exposure(
    *,
    orders: Sequence[Mapping[str, Any]],
    positions: Sequence[Mapping[str, Any]],
) -> float | None:
    exposure_parts: list[float] = []
    position_exposure = sum(
        max(0, _int(row.get("quantity"))) * (_float(row.get("avg_price")) or 0.0)
        for row in positions
    )
    if positions:
        exposure_parts.append(position_exposure)
    partial_open_exposure = sum(
        _int(row.get("reconciliation_open_quantity")) * (_float(row.get("limit_price")) or 0.0)
        for row in orders
        if _order_reconciliation_status(row) == "partial"
    )
    if partial_open_exposure:
        exposure_parts.append(partial_open_exposure)
    if not exposure_parts:
        return None if not orders else 0.0
    return sum(exposure_parts)


def _latest_observed_at(
    orders: Sequence[Mapping[str, Any]],
    fills: Sequence[Mapping[str, Any]],
    positions: Sequence[Mapping[str, Any]],
) -> datetime | None:
    timestamps = [
        _datetime(row.get("submitted_at")) for row in orders if row.get("submitted_at")
    ]
    timestamps.extend(
        _datetime(row.get("reconciliation_created_at"))
        for row in orders
        if row.get("reconciliation_created_at")
    )
    timestamps.extend(_datetime(row.get("filled_at")) for row in fills if row.get("filled_at"))
    timestamps.extend(
        _datetime(row.get("updated_at")) for row in positions if row.get("updated_at")
    )
    parsed = [timestamp for timestamp in timestamps if timestamp is not None]
    return max(parsed) if parsed else None


def _overall_data_status(
    execution: Mapping[str, Any],
    pnl: Mapping[str, Any],
    freshness: Mapping[str, Any],
) -> str:
    if execution.get("data_status") == "empty" and pnl.get("status") == "unavailable":
        return "empty"
    if freshness.get("status") == "stale":
        return "stale"
    if pnl.get("status") in {"partial", "unavailable"}:
        return "partial"
    return "ok"


def _data_status_detail(
    status: str,
    execution: Mapping[str, Any],
    pnl: Mapping[str, Any],
    freshness: Mapping[str, Any],
) -> str:
    if status == "empty":
        return "No live run or paper performance rows recorded."
    if status == "stale":
        return "Latest live run is older than the Performance freshness threshold."
    if status == "partial":
        if execution.get("data_status") == "empty":
            return "Paper performance rows exist but no recent live run rows are recorded."
        return str(pnl.get("status_detail") or "Some performance fields are unavailable.")
    return "Performance data is current."


def _sum_field(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    values = [_float(row.get(key)) for row in rows if row.get(key) is not None]
    if not values:
        return None
    return sum(value for value in values if value is not None)


def _remaining(limit: float | None, used: float | None) -> float | None:
    if limit is None or used is None:
        return None
    return max(0.0, limit - used)


def _fraction(used: float | None, limit: float | None) -> float | None:
    if used is None or limit is None or limit <= 0:
        return None
    return round(used / limit, 6)


def _money(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        text = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
