"""Curated Data Explorer views and Lab evidence helpers."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from alphadb.state.repository import OperationalStateRepository


MAX_ROWS = 500
DEFAULT_ROWS = 100


@dataclass(frozen=True)
class DataView:
    name: str
    label: str
    table_name: str
    columns: tuple[str, ...]
    default_sort: str
    description: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "columns": list(self.columns),
            "default_sort": self.default_sort,
            "description": self.description,
        }


@dataclass(frozen=True)
class DataQuery:
    view: DataView
    filters: Mapping[str, Any]
    sort: Mapping[str, Any]
    limit: int

    def fingerprint_payload(self, *, schema: Sequence[Mapping[str, Any]], row_count: int) -> dict[str, Any]:
        return {
            "view_name": self.view.name,
            "filters": dict(self.filters),
            "sort": dict(self.sort),
            "limit": self.limit,
            "schema": [dict(row) for row in schema],
            "row_count": row_count,
        }


DATA_VIEWS: tuple[DataView, ...] = (
    DataView(
        "decisions",
        "Decisions",
        "decisions",
        (
            "decision_id",
            "run_id",
            "market_ticker",
            "decision_timestamp",
            "outcome",
            "probability_yes",
            "selected_side",
            "skip_reason",
            "created_at",
        ),
        "decision_timestamp",
        "Authoritative trade or skip decisions by market instance.",
    ),
    DataView(
        "feature_rows",
        "Feature Rows",
        "feature_rows",
        (
            "feature_row_id",
            "run_id",
            "market_ticker",
            "model_id",
            "decision_timestamp",
            "feature_version",
            "calibration_version",
            "dataset_id",
            "row_hash",
            "created_at",
        ),
        "decision_timestamp",
        "Decision-time feature rows with no-lookahead provenance.",
    ),
    DataView(
        "raw_events",
        "Raw Events",
        "raw_events",
        (
            "raw_event_id",
            "run_id",
            "market_ticker",
            "source",
            "source_event_id",
            "received_at",
            "source_timestamp",
            "schema_version",
            "payload_hash",
            "created_at",
        ),
        "received_at",
        "Append-only market, feature, and execution event log.",
    ),
    DataView(
        "risk_decisions",
        "Risk Decisions",
        "risk_decisions",
        ("risk_decision_id", "decision_id", "status", "reason", "created_at"),
        "created_at",
        "Risk-gate result for each accepted decision.",
    ),
    DataView(
        "order_intents",
        "Order Intents",
        "order_intents",
        (
            "order_intent_id",
            "risk_decision_id",
            "side",
            "price",
            "quantity",
            "max_cost_dollars",
            "time_in_force",
            "created_at",
        ),
        "created_at",
        "Orders the shared decision engine wanted to submit.",
    ),
    DataView(
        "paper_orders",
        "Paper Orders",
        "paper_orders",
        (
            "paper_order_id",
            "order_intent_id",
            "risk_decision_id",
            "market_ticker",
            "side",
            "limit_price",
            "quantity",
            "filled_quantity",
            "status",
            "time_in_force",
            "submitted_at",
            "created_at",
        ),
        "submitted_at",
        "Paper execution orders.",
    ),
    DataView(
        "paper_fills",
        "Paper Fills",
        "paper_fills",
        (
            "paper_fill_id",
            "paper_order_id",
            "market_ticker",
            "side",
            "fill_price",
            "quantity",
            "liquidity_role",
            "filled_at",
            "fee_dollars",
            "created_at",
        ),
        "filled_at",
        "Paper execution fills.",
    ),
    DataView(
        "live_order_attempts",
        "Live Order Attempts",
        "live_order_attempts",
        (
            "live_order_attempt_id",
            "order_intent_id",
            "risk_decision_id",
            "strategy",
            "live_risk_day",
            "reservation_id",
            "market_ticker",
            "client_order_id",
            "runtime_mode",
            "status",
            "guard_reason",
            "submitted_at",
            "exchange_order_id",
            "exchange_status",
            "exchange_http_status",
            "exchange_error_class",
            "fill_count",
            "remaining_count",
            "created_at",
        ),
        "created_at",
        "Gated-live order submission attempts.",
    ),
    DataView(
        "model_registry",
        "Model Registry",
        "model_registry_records",
        (
            "model_id",
            "series",
            "model_name",
            "model_version",
            "feature_version",
            "calibration_version",
            "dataset_id",
            "promotion_state",
            "created_at",
            "updated_at",
        ),
        "updated_at",
        "Approved and candidate model artifacts.",
    ),
    DataView(
        "strategy_outcomes",
        "Strategy Outcomes",
        "strategy_market_outcomes",
        (
            "outcome_id",
            "run_id",
            "market_ticker",
            "decision_timestamp",
            "status",
            "reason",
            "decision_id",
            "risk_decision_id",
            "paper_order_id",
            "created_at",
            "updated_at",
        ),
        "updated_at",
        "Per-instance strategy outcomes for tracer, paper, shadow, and live flows.",
    ),
    DataView(
        "live_run_statuses",
        "Live Run Statuses",
        "live_run_statuses",
        (
            "run_id",
            "strategy",
            "generated_at",
            "current_market_ticker",
            "decision_outcome",
            "selected_side",
            "skip_reason",
            "latest_attempt_status",
            "fill_status",
            "recent_attempt_count",
            "created_at",
            "updated_at",
        ),
        "generated_at",
        "Latest live operation status projections.",
    ),
)

DATA_VIEW_MAP = {view.name: view for view in DATA_VIEWS}
FILTER_COLUMNS = (
    "run_id",
    "market_ticker",
    "status",
    "outcome",
    "source",
    "strategy",
    "model_id",
    "dataset_id",
    "promotion_state",
    "decision_outcome",
)


class DashboardDataExplorerRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def list_views(self) -> list[dict[str, Any]]:
        return [view.as_dict() for view in DATA_VIEWS]

    def query_view(
        self,
        view_name: str,
        *,
        filters: Mapping[str, Any] | None = None,
        sort: Mapping[str, Any] | None = None,
        limit: int = DEFAULT_ROWS,
    ) -> dict[str, Any]:
        query = build_data_query(view_name, filters=filters or {}, sort=sort or {}, limit=limit)
        sql, params = _select_sql(query)
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = [json_ready(dict(row)) for row in cursor.fetchall()]
        schema = _schema_for(query.view)
        return {
            "view": query.view.as_dict(),
            "filters": dict(query.filters),
            "sort": dict(query.sort),
            "limit": query.limit,
            "schema": schema,
            "rows": rows,
            "row_count": len(rows),
        }

    def evidence_from_view(
        self,
        *,
        view_name: str,
        filters: Mapping[str, Any] | None = None,
        sort: Mapping[str, Any] | None = None,
        limit: int = DEFAULT_ROWS,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.query_view(view_name, filters=filters or {}, sort=sort or {}, limit=limit)
        view = DATA_VIEW_MAP[view_name]
        query = DataQuery(
            view=view,
            filters=result["filters"],
            sort=result["sort"],
            limit=int(result["limit"]),
        )
        schema = result["schema"]
        row_count = int(result["row_count"])
        query_hash = _query_hash(query.fingerprint_payload(schema=schema, row_count=row_count))
        return {
            "evidence_id": f"evid_{query_hash[:12]}",
            "source": "data_explorer",
            "view_name": view.name,
            "view_label": view.label,
            "filters": dict(result["filters"]),
            "sort": dict(result["sort"]),
            "row_limit": query.limit,
            "row_count": row_count,
            "schema": schema,
            "query_hash": query_hash,
            "rows_preview": result["rows"][:10],
            "metadata": dict(metadata or {}),
            "created_at": datetime.now(UTC).isoformat(),
        }

    def export_view(
        self,
        view_name: str,
        *,
        export_format: str,
        filters: Mapping[str, Any] | None = None,
        sort: Mapping[str, Any] | None = None,
        limit: int = DEFAULT_ROWS,
    ) -> dict[str, Any]:
        result = self.query_view(view_name, filters=filters or {}, sort=sort or {}, limit=limit)
        export_format = export_format.lower()
        if export_format == "json":
            body = json.dumps(result["rows"], sort_keys=True, indent=2, default=str)
            content_type = "application/json"
        elif export_format == "csv":
            body = _rows_to_csv(result["schema"], result["rows"])
            content_type = "text/csv"
        else:
            raise ValueError("export format must be csv or json")
        return {
            "view_name": view_name,
            "format": export_format,
            "content_type": content_type,
            "row_count": result["row_count"],
            "body": body,
        }


def build_data_query(
    view_name: str,
    *,
    filters: Mapping[str, Any],
    sort: Mapping[str, Any],
    limit: int,
) -> DataQuery:
    view = DATA_VIEW_MAP.get(view_name)
    if view is None:
        raise KeyError(f"unknown data view: {view_name}")
    clean_filters = _clean_filters(view, filters)
    clean_sort = _clean_sort(view, sort)
    return DataQuery(
        view=view,
        filters=clean_filters,
        sort=clean_sort,
        limit=_bounded_limit(limit),
    )


def _select_sql(query: DataQuery) -> tuple[str, tuple[Any, ...]]:
    column_sql = ", ".join(query.view.columns)
    where_parts: list[str] = []
    params: list[Any] = []
    for key, value in query.filters.items():
        if key in FILTER_COLUMNS and key in query.view.columns:
            where_parts.append(f"{key} = %s")
            params.append(value)
        elif key == "created_after" and "created_at" in query.view.columns:
            where_parts.append("created_at >= %s")
            params.append(value)
        elif key == "created_before" and "created_at" in query.view.columns:
            where_parts.append("created_at <= %s")
            params.append(value)
        elif key == "decision_after" and "decision_timestamp" in query.view.columns:
            where_parts.append("decision_timestamp >= %s")
            params.append(value)
        elif key == "decision_before" and "decision_timestamp" in query.view.columns:
            where_parts.append("decision_timestamp <= %s")
            params.append(value)
    where_sql = f" where {' and '.join(where_parts)}" if where_parts else ""
    sort_column = str(query.sort["column"])
    direction = str(query.sort["direction"])
    sql = (
        f"select {column_sql} from {query.view.table_name}{where_sql} "
        f"order by {sort_column} {direction}, {query.view.columns[0]} desc limit %s"
    )
    params.append(query.limit)
    return sql, tuple(params)


def _clean_filters(view: DataView, filters: Mapping[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in filters.items():
        if value is None or value == "":
            continue
        if key in FILTER_COLUMNS and key not in view.columns:
            continue
        if key in FILTER_COLUMNS or key in {
            "created_after",
            "created_before",
            "decision_after",
            "decision_before",
        }:
            clean[key] = value
    return clean


def _clean_sort(view: DataView, sort: Mapping[str, Any]) -> dict[str, Any]:
    column = str(sort.get("column") or view.default_sort)
    if column not in view.columns:
        column = view.default_sort
    direction = str(sort.get("direction") or "desc").lower()
    if direction not in {"asc", "desc"}:
        direction = "desc"
    return {"column": column, "direction": direction}


def _schema_for(view: DataView) -> list[dict[str, Any]]:
    return [{"name": column, "type": "unknown"} for column in view.columns]


def _rows_to_csv(schema: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]) -> str:
    output = io.StringIO()
    fieldnames = [str(column["name"]) for column in schema]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key) for key in fieldnames})
    return output.getvalue()


def _query_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit or DEFAULT_ROWS), MAX_ROWS))


def json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [json_ready(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
