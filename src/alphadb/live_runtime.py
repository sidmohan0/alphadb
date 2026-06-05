"""Dashboard-owned runtime config and live status projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.state.repository import OperationalStateRepository


FAIR_VALUE_LIVE_STRATEGY = "fair_value_live"
MAX_SCAN_MARKETS = 500


@dataclass(frozen=True)
class LiveRuntimeConfig:
    max_order_dollars: float
    max_market_exposure_dollars: float
    max_daily_loss_dollars: float
    min_edge: float
    max_markets: int

    def validate(self) -> "LiveRuntimeConfig":
        if self.max_order_dollars <= 0:
            raise ValueError("max_order_dollars must be positive")
        if self.max_market_exposure_dollars <= 0:
            raise ValueError("max_market_exposure_dollars must be positive")
        if self.max_daily_loss_dollars <= 0:
            raise ValueError("max_daily_loss_dollars must be positive")
        if self.min_edge < 0:
            raise ValueError("min_edge must be non-negative")
        if self.min_edge > 1:
            raise ValueError("min_edge must be no greater than 1")
        if self.max_markets < 1:
            raise ValueError("max_markets must be at least 1")
        if self.max_markets > MAX_SCAN_MARKETS:
            raise ValueError(f"max_markets must be no greater than {MAX_SCAN_MARKETS}")
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_order_dollars": self.max_order_dollars,
            "max_market_exposure_dollars": self.max_market_exposure_dollars,
            "max_daily_loss_dollars": self.max_daily_loss_dollars,
            "min_edge": self.min_edge,
            "max_markets": self.max_markets,
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        current: "LiveRuntimeConfig | None" = None,
    ) -> "LiveRuntimeConfig":
        base = current or DEFAULT_FAIR_VALUE_LIVE_CONFIG
        config = cls(
            max_order_dollars=_float_payload(
                payload,
                "max_order_dollars",
                default=base.max_order_dollars,
            ),
            max_market_exposure_dollars=_float_payload(
                payload,
                "max_market_exposure_dollars",
                "max_ticker_exposure_dollars",
                default=base.max_market_exposure_dollars,
            ),
            max_daily_loss_dollars=_float_payload(
                payload,
                "max_daily_loss_dollars",
                default=base.max_daily_loss_dollars,
            ),
            min_edge=_float_payload(payload, "min_edge", default=base.min_edge),
            max_markets=_int_payload(payload, "max_markets", default=base.max_markets),
        )
        return config.validate()


DEFAULT_FAIR_VALUE_LIVE_CONFIG = LiveRuntimeConfig(
    max_order_dollars=5.0,
    max_market_exposure_dollars=5.0,
    max_daily_loss_dollars=50.0,
    min_edge=0.0,
    max_markets=20,
)


@dataclass(frozen=True)
class LiveRuntimeConfigRevision:
    config_id: str
    strategy: str
    version: int
    is_active: bool
    config: LiveRuntimeConfig
    created_by: str
    created_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "strategy": self.strategy,
            "version": self.version,
            "is_active": self.is_active,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            **self.config.as_dict(),
        }

    def manifest_snapshot(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "strategy": self.strategy,
            "version": self.version,
            "snapshot": self.config.as_dict(),
            "created_at": self.created_at.isoformat(),
        }


class LiveRuntimeConfigRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def seed_defaults(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        created_by: str = "system",
    ) -> LiveRuntimeConfigRevision:
        OperationalStateRepository(self.database_url).apply_migrations()
        active = self.get_active_config(strategy=strategy, apply_migrations=False)
        if active is not None:
            return active
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute("lock table live_runtime_configs in exclusive mode")
                cursor.execute(
                    """
                    select *
                    from live_runtime_configs
                    where strategy = %s and is_active
                    order by version desc
                    limit 1
                    """,
                    (strategy,),
                )
                row = cursor.fetchone()
                if row is None:
                    row = self._insert_revision(
                        cursor,
                        strategy=strategy,
                        config=DEFAULT_FAIR_VALUE_LIVE_CONFIG,
                        created_by=created_by,
                    )
            connection.commit()
        return _config_revision_from_row(row)

    def get_active_config(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        apply_migrations: bool = True,
    ) -> LiveRuntimeConfigRevision | None:
        if apply_migrations:
            OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from live_runtime_configs
                    where strategy = %s and is_active
                    order by version desc
                    limit 1
                    """,
                    (strategy,),
                )
                row = cursor.fetchone()
        return None if row is None else _config_revision_from_row(row)

    def save_config(
        self,
        config: LiveRuntimeConfig,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        created_by: str = "dashboard",
    ) -> LiveRuntimeConfigRevision:
        config.validate()
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute("lock table live_runtime_configs in exclusive mode")
                cursor.execute(
                    """
                    update live_runtime_configs
                    set is_active = false
                    where strategy = %s and is_active
                    """,
                    (strategy,),
                )
                row = self._insert_revision(
                    cursor,
                    strategy=strategy,
                    config=config,
                    created_by=created_by,
                )
            connection.commit()
        return _config_revision_from_row(row)

    def recent_revisions(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        limit: int = 5,
    ) -> list[LiveRuntimeConfigRevision]:
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from live_runtime_configs
                    where strategy = %s
                    order by version desc
                    limit %s
                    """,
                    (strategy, limit),
                )
                rows = cursor.fetchall()
        return [_config_revision_from_row(row) for row in rows]

    def _insert_revision(
        self,
        cursor: psycopg.Cursor,
        *,
        strategy: str,
        config: LiveRuntimeConfig,
        created_by: str,
    ) -> Mapping[str, Any]:
        cursor.execute(
            "select coalesce(max(version), 0) + 1 as next_version from live_runtime_configs where strategy = %s",
            (strategy,),
        )
        version_row = cursor.fetchone()
        version = int(version_row["next_version"] if version_row else 1)
        config_id = f"live_cfg_{uuid4().hex[:12]}"
        snapshot = config.as_dict()
        cursor.execute(
            """
            insert into live_runtime_configs (
                config_id,
                strategy,
                version,
                is_active,
                max_order_dollars,
                max_market_exposure_dollars,
                max_daily_loss_dollars,
                min_edge,
                max_markets,
                snapshot,
                created_by
            )
            values (%s, %s, %s, true, %s, %s, %s, %s, %s, %s, %s)
            returning *
            """,
            (
                config_id,
                strategy,
                version,
                config.max_order_dollars,
                config.max_market_exposure_dollars,
                config.max_daily_loss_dollars,
                config.min_edge,
                config.max_markets,
                Jsonb(snapshot),
                created_by,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("runtime config insert returned no row")
        return row


@dataclass(frozen=True)
class LiveRunStatus:
    run_id: str | None
    strategy: str
    generated_at: datetime | None
    config_id: str | None
    config_version: int | None
    live_orders_enabled: bool
    current_market_ticker: str | None
    decision_outcome: str
    selected_side: str | None
    skip_reason: str | None
    latest_attempt_status: str | None
    latest_attempt_reason: str | None
    fill_status: str | None
    daily_loss_used_dollars: float
    daily_loss_limit_dollars: float
    market_exposure_used_dollars: float
    market_exposure_limit_dollars: float
    recent_attempt_count: int
    recent_submitted_count: int
    recent_skipped_count: int
    recent_no_fill_count: int
    recent_filled_count: int
    summary: Mapping[str, Any]
    recent_attempts: Sequence[Mapping[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "strategy": self.strategy,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "config_id": self.config_id,
            "config_version": self.config_version,
            "live_orders_enabled": self.live_orders_enabled,
            "current_market_ticker": self.current_market_ticker,
            "decision_outcome": self.decision_outcome,
            "selected_side": self.selected_side,
            "skip_reason": self.skip_reason,
            "latest_attempt_status": self.latest_attempt_status,
            "latest_attempt_reason": self.latest_attempt_reason,
            "fill_status": self.fill_status,
            "daily_loss_used_dollars": self.daily_loss_used_dollars,
            "daily_loss_limit_dollars": self.daily_loss_limit_dollars,
            "market_exposure_used_dollars": self.market_exposure_used_dollars,
            "market_exposure_limit_dollars": self.market_exposure_limit_dollars,
            "recent_attempt_count": self.recent_attempt_count,
            "recent_submitted_count": self.recent_submitted_count,
            "recent_skipped_count": self.recent_skipped_count,
            "recent_no_fill_count": self.recent_no_fill_count,
            "recent_filled_count": self.recent_filled_count,
            "summary": dict(self.summary),
            "recent_attempts": [dict(attempt) for attempt in self.recent_attempts],
        }


class LiveRunStatusRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def persist(self, status: LiveRunStatus) -> LiveRunStatus:
        if status.run_id is None or status.generated_at is None:
            raise ValueError("persisted live run status requires run_id and generated_at")
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into live_run_statuses (
                        run_id,
                        strategy,
                        generated_at,
                        config_id,
                        config_version,
                        live_orders_enabled,
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
                        recent_filled_count,
                        summary,
                        recent_attempts,
                        updated_at
                    )
                    values (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
                    )
                    on conflict (run_id) do update set
                        strategy = excluded.strategy,
                        generated_at = excluded.generated_at,
                        config_id = excluded.config_id,
                        config_version = excluded.config_version,
                        live_orders_enabled = excluded.live_orders_enabled,
                        current_market_ticker = excluded.current_market_ticker,
                        decision_outcome = excluded.decision_outcome,
                        selected_side = excluded.selected_side,
                        skip_reason = excluded.skip_reason,
                        latest_attempt_status = excluded.latest_attempt_status,
                        latest_attempt_reason = excluded.latest_attempt_reason,
                        fill_status = excluded.fill_status,
                        daily_loss_used_dollars = excluded.daily_loss_used_dollars,
                        daily_loss_limit_dollars = excluded.daily_loss_limit_dollars,
                        market_exposure_used_dollars = excluded.market_exposure_used_dollars,
                        market_exposure_limit_dollars = excluded.market_exposure_limit_dollars,
                        recent_attempt_count = excluded.recent_attempt_count,
                        recent_submitted_count = excluded.recent_submitted_count,
                        recent_skipped_count = excluded.recent_skipped_count,
                        recent_no_fill_count = excluded.recent_no_fill_count,
                        recent_filled_count = excluded.recent_filled_count,
                        summary = excluded.summary,
                        recent_attempts = excluded.recent_attempts,
                        updated_at = now()
                    """,
                    (
                        status.run_id,
                        status.strategy,
                        status.generated_at,
                        status.config_id,
                        status.config_version,
                        status.live_orders_enabled,
                        status.current_market_ticker,
                        status.decision_outcome,
                        status.selected_side,
                        status.skip_reason,
                        status.latest_attempt_status,
                        status.latest_attempt_reason,
                        status.fill_status,
                        status.daily_loss_used_dollars,
                        status.daily_loss_limit_dollars,
                        status.market_exposure_used_dollars,
                        status.market_exposure_limit_dollars,
                        status.recent_attempt_count,
                        status.recent_submitted_count,
                        status.recent_skipped_count,
                        status.recent_no_fill_count,
                        status.recent_filled_count,
                        Jsonb(dict(status.summary)),
                        Jsonb([dict(attempt) for attempt in status.recent_attempts]),
                    ),
                )
            connection.commit()
        return status

    def latest_status(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
    ) -> LiveRunStatus:
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from live_run_statuses
                    where strategy = %s
                    order by generated_at desc, run_id desc
                    limit 1
                    """,
                    (strategy,),
                )
                row = cursor.fetchone()
        return no_recent_live_run_status(strategy=strategy) if row is None else _status_from_row(row)

    def recent_details(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        run_id,
                        generated_at,
                        current_market_ticker,
                        decision_outcome,
                        latest_attempt_status,
                        latest_attempt_reason,
                        fill_status,
                        recent_attempt_count
                    from live_run_statuses
                    where strategy = %s
                    order by generated_at desc, run_id desc
                    limit %s
                    """,
                    (strategy, limit),
                )
                rows = cursor.fetchall()
        return [_json_ready(dict(row)) for row in rows]


def build_fair_value_live_status(
    *,
    manifest: Mapping[str, Any],
    attempts_payload: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
) -> LiveRunStatus:
    attempts = [
        dict(attempt)
        for attempt in attempts_payload.get("attempts", [])
        if isinstance(attempt, Mapping)
    ]
    latest_attempt = attempts[-1] if attempts else {}
    latest_market = _text(latest_attempt.get("market_ticker"))
    latest_side = _text(latest_attempt.get("side")) or _text(
        _mapping(latest_attempt.get("decision")).get("side")
    )
    latest_status = _text(latest_attempt.get("status"))
    latest_reason = _text(latest_attempt.get("reason"))
    reconciliation_rows = [
        dict(row) for row in reconciliation.get("rows", []) if isinstance(row, Mapping)
    ]
    latest_reconciliation = _matching_reconciliation(latest_attempt, reconciliation_rows)
    config = _mapping(manifest.get("runtime_config"))
    runtime_controls = _mapping(manifest.get("runtime_controls"))
    snapshot = _mapping(config.get("snapshot"))
    daily_limit = _float(
        snapshot.get("max_daily_loss_dollars"),
        default=_float(runtime_controls.get("max_daily_loss_dollars"), default=0.0),
    )
    exposure_limit = _float(
        snapshot.get("max_market_exposure_dollars"),
        default=_float(
            runtime_controls.get("max_market_exposure_dollars"),
            default=_float(runtime_controls.get("max_ticker_exposure_dollars"), default=0.0),
        ),
    )
    daily_used = _daily_loss_usage(reconciliation_rows)
    market_used = _market_exposure_for(latest_market, reconciliation)
    fill_status = _fill_status(latest_attempt, latest_reconciliation)
    decision_outcome = _decision_outcome(latest_status, manifest)
    return LiveRunStatus(
        run_id=_text(manifest.get("run_id")),
        strategy=FAIR_VALUE_LIVE_STRATEGY,
        generated_at=_datetime(manifest.get("generated_at")) or datetime.now(UTC),
        config_id=_text(config.get("config_id")),
        config_version=_optional_int(config.get("version")),
        live_orders_enabled=bool(runtime_controls.get("live_orders_enabled")),
        current_market_ticker=latest_market,
        decision_outcome=decision_outcome,
        selected_side=latest_side if decision_outcome in {"submitted", "rejected", "error"} else None,
        skip_reason=latest_reason if decision_outcome == "skipped" else None,
        latest_attempt_status=latest_status,
        latest_attempt_reason=latest_reason,
        fill_status=fill_status,
        daily_loss_used_dollars=daily_used,
        daily_loss_limit_dollars=daily_limit,
        market_exposure_used_dollars=market_used,
        market_exposure_limit_dollars=exposure_limit,
        recent_attempt_count=len(attempts),
        recent_submitted_count=sum(1 for attempt in attempts if attempt.get("status") == "submitted"),
        recent_skipped_count=sum(1 for attempt in attempts if attempt.get("status") == "skipped"),
        recent_no_fill_count=sum(
            1 for row in reconciliation_rows if row.get("settlement_status") == "no_fill"
        ),
        recent_filled_count=sum(
            1 for row in reconciliation_rows if int(row.get("filled_contracts") or 0) > 0
        ),
        summary={
            "counts": dict(_mapping(manifest.get("counts"))),
            "report_summary": dict(_mapping(manifest.get("report_summary"))),
            "runtime_controls": {
                key: runtime_controls.get(key)
                for key in (
                    "submit_live_orders_requested",
                    "live_orders_enabled",
                    "orders_placed",
                    "filled_contracts",
                )
            },
        },
        recent_attempts=_recent_attempt_rows(attempts, reconciliation_rows),
    )


def no_recent_live_run_status(*, strategy: str = FAIR_VALUE_LIVE_STRATEGY) -> LiveRunStatus:
    return LiveRunStatus(
        run_id=None,
        strategy=strategy,
        generated_at=None,
        config_id=None,
        config_version=None,
        live_orders_enabled=False,
        current_market_ticker=None,
        decision_outcome="no_recent_run",
        selected_side=None,
        skip_reason=None,
        latest_attempt_status=None,
        latest_attempt_reason=None,
        fill_status=None,
        daily_loss_used_dollars=0.0,
        daily_loss_limit_dollars=0.0,
        market_exposure_used_dollars=0.0,
        market_exposure_limit_dollars=0.0,
        recent_attempt_count=0,
        recent_submitted_count=0,
        recent_skipped_count=0,
        recent_no_fill_count=0,
        recent_filled_count=0,
        summary={},
        recent_attempts=[],
    )


def _config_revision_from_row(row: Mapping[str, Any]) -> LiveRuntimeConfigRevision:
    return LiveRuntimeConfigRevision(
        config_id=str(row["config_id"]),
        strategy=str(row["strategy"]),
        version=int(row["version"]),
        is_active=bool(row["is_active"]),
        config=LiveRuntimeConfig(
            max_order_dollars=float(row["max_order_dollars"]),
            max_market_exposure_dollars=float(row["max_market_exposure_dollars"]),
            max_daily_loss_dollars=float(row["max_daily_loss_dollars"]),
            min_edge=float(row["min_edge"]),
            max_markets=int(row["max_markets"]),
        ).validate(),
        created_by=str(row["created_by"]),
        created_at=_datetime(row["created_at"]) or datetime.now(UTC),
    )


def _status_from_row(row: Mapping[str, Any]) -> LiveRunStatus:
    return LiveRunStatus(
        run_id=str(row["run_id"]),
        strategy=str(row["strategy"]),
        generated_at=_datetime(row["generated_at"]),
        config_id=_text(row.get("config_id")),
        config_version=_optional_int(row.get("config_version")),
        live_orders_enabled=bool(row["live_orders_enabled"]),
        current_market_ticker=_text(row.get("current_market_ticker")),
        decision_outcome=str(row["decision_outcome"]),
        selected_side=_text(row.get("selected_side")),
        skip_reason=_text(row.get("skip_reason")),
        latest_attempt_status=_text(row.get("latest_attempt_status")),
        latest_attempt_reason=_text(row.get("latest_attempt_reason")),
        fill_status=_text(row.get("fill_status")),
        daily_loss_used_dollars=float(row["daily_loss_used_dollars"]),
        daily_loss_limit_dollars=float(row["daily_loss_limit_dollars"]),
        market_exposure_used_dollars=float(row["market_exposure_used_dollars"]),
        market_exposure_limit_dollars=float(row["market_exposure_limit_dollars"]),
        recent_attempt_count=int(row["recent_attempt_count"]),
        recent_submitted_count=int(row["recent_submitted_count"]),
        recent_skipped_count=int(row["recent_skipped_count"]),
        recent_no_fill_count=int(row["recent_no_fill_count"]),
        recent_filled_count=int(row["recent_filled_count"]),
        summary=dict(row["summary"]),
        recent_attempts=[dict(attempt) for attempt in row["recent_attempts"]],
    )


def _matching_reconciliation(
    attempt: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    attempt_id = attempt.get("attempt_id")
    if attempt_id is not None:
        for row in rows:
            if row.get("attempt_id") == attempt_id:
                return row
    return rows[-1] if rows else {}


def _recent_attempt_rows(
    attempts: Sequence[Mapping[str, Any]],
    reconciliation_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for attempt in attempts[-10:]:
        reconciliation = _matching_reconciliation(attempt, reconciliation_rows)
        rows.append(
            {
                "submitted_at": attempt.get("submitted_at"),
                "market_ticker": attempt.get("market_ticker"),
                "status": attempt.get("status"),
                "reason": attempt.get("reason"),
                "side": attempt.get("side"),
                "fill_status": _fill_status(attempt, reconciliation),
                "filled_contracts": reconciliation.get("filled_contracts", attempt.get("fill_count")),
                "order_id": attempt.get("order_id"),
            }
        )
    return rows


def _decision_outcome(status: str | None, manifest: Mapping[str, Any]) -> str:
    if status in {"submitted", "skipped", "rejected", "error"}:
        return status
    counts = _mapping(manifest.get("counts"))
    if int(counts.get("live_attempts") or 0) == 0:
        if int(counts.get("replay_trades") or 0) == 0:
            return "skipped"
        return "no_live_attempt"
    return "unknown"


def _fill_status(
    attempt: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
) -> str | None:
    status = attempt.get("status")
    if status == "skipped":
        return "not_submitted"
    if int(reconciliation.get("filled_contracts") or attempt.get("fill_count") or 0) > 0:
        return "filled"
    if reconciliation.get("settlement_status") == "no_fill":
        return "no_fill"
    if status == "submitted":
        return "submitted_fill_unknown"
    return None if not status else str(status)


def _daily_loss_usage(rows: Sequence[Mapping[str, Any]]) -> float:
    usage = 0.0
    for row in rows:
        if int(row.get("filled_contracts") or 0) <= 0:
            continue
        if row.get("settlement_status") == "settled":
            usage += max(0.0, -float(row.get("pnl_dollars") or 0.0))
        else:
            usage += float(row.get("max_loss_dollars") or 0.0)
    return round(usage, 6)


def _market_exposure_for(
    ticker: str | None,
    reconciliation: Mapping[str, Any],
) -> float:
    if not ticker:
        return 0.0
    report = _mapping(reconciliation.get("per_market_exposure"))
    markets = report.get("markets", [])
    if not isinstance(markets, list):
        return 0.0
    for row in markets:
        if isinstance(row, Mapping) and row.get("market_ticker") == ticker:
            return _float(row.get("exposure_dollars"), default=0.0)
    return 0.0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _float(value: Any, *, default: float) -> float:
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _float_payload(payload: Mapping[str, Any], *keys: str, default: float) -> float:
    for key in keys:
        if key in payload:
            return _float(payload[key], default=default)
    return default


def _int_payload(payload: Mapping[str, Any], key: str, *, default: int) -> int:
    if key not in payload:
        return default
    try:
        return int(payload[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _json_ready(row: Mapping[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, Decimal):
            result[key] = float(value)
        else:
            result[key] = value
    return result
