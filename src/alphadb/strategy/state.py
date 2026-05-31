"""Persisted strategy-run state for handled market outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.config import settings_from_env
from alphadb.runtime import RuntimeMode, evaluate_runtime_guard, settings_with_overrides
from alphadb.state.repository import OperationalStateRepository

StrategyOutcomeStatus = Literal["handled", "skipped", "error"]


@dataclass(frozen=True)
class StrategyRunRecord:
    run_id: str
    runtime_mode: str
    market_series: str
    started_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "runtime_mode": self.runtime_mode,
            "market_series": self.market_series,
            "started_at": self.started_at.isoformat(),
        }


@dataclass(frozen=True)
class StrategyMarketOutcome:
    outcome_id: str
    run_id: str
    market_ticker: str
    decision_timestamp: datetime
    status: StrategyOutcomeStatus
    reason: str | None = None
    decision_id: str | None = None
    risk_decision_id: str | None = None
    paper_order_id: str | None = None
    latency_checkpoints: Mapping[str, float] | None = None
    metadata: Mapping[str, Any] | None = None
    inserted: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "run_id": self.run_id,
            "market_ticker": self.market_ticker,
            "decision_timestamp": self.decision_timestamp.isoformat(),
            "status": self.status,
            "reason": self.reason,
            "decision_id": self.decision_id,
            "risk_decision_id": self.risk_decision_id,
            "paper_order_id": self.paper_order_id,
            "latency_checkpoints": dict(self.latency_checkpoints or {}),
            "metadata": dict(self.metadata or {}),
            "inserted": self.inserted,
        }


class StrategyRunRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def start_run(
        self,
        *,
        market_series: str,
        runtime_mode: RuntimeMode | str,
        started_at: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> StrategyRunRecord:
        OperationalStateRepository(self.database_url).apply_migrations()
        started_at = started_at or datetime.now(UTC)
        mode = RuntimeMode(str(runtime_mode))
        guard = evaluate_runtime_guard(
            settings_with_overrides(settings_from_env(), {"runtime_mode": mode.value})
        )
        run_id = f"run_{uuid4().hex[:12]}"
        payload = {
            "runner": "alphadb.strategy",
            "guard": guard.as_dict(),
            **dict(metadata or {}),
        }
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into platform_runs (
                        run_id, mode, market_series, status, started_at, metadata
                    )
                    values (%s, %s, %s, %s, %s, %s)
                    """,
                    (run_id, mode.value, market_series, "running", started_at, Jsonb(payload)),
                )
            connection.commit()
        return StrategyRunRecord(
            run_id=run_id,
            runtime_mode=mode.value,
            market_series=market_series,
            started_at=started_at,
        )

    def finish_run(
        self,
        *,
        run_id: str,
        status: str,
        metadata_patch: Mapping[str, Any] | None = None,
    ) -> None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                if metadata_patch:
                    cursor.execute(
                        """
                        update platform_runs
                        set
                            status = %s,
                            metadata = metadata || %s::jsonb
                        where run_id = %s
                        """,
                        (status, Jsonb(dict(metadata_patch)), run_id),
                    )
                else:
                    cursor.execute(
                        "update platform_runs set status = %s where run_id = %s",
                        (status, run_id),
                    )
            connection.commit()

    def record_outcome(self, outcome: StrategyMarketOutcome) -> StrategyMarketOutcome:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into strategy_market_outcomes (
                        outcome_id,
                        run_id,
                        market_ticker,
                        decision_timestamp,
                        status,
                        reason,
                        decision_id,
                        risk_decision_id,
                        paper_order_id,
                        latency_checkpoints,
                        metadata
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (run_id, market_ticker) do nothing
                    returning *
                    """,
                    (
                        outcome.outcome_id,
                        outcome.run_id,
                        outcome.market_ticker,
                        outcome.decision_timestamp,
                        outcome.status,
                        outcome.reason,
                        outcome.decision_id,
                        outcome.risk_decision_id,
                        outcome.paper_order_id,
                        Jsonb(dict(outcome.latency_checkpoints or {})),
                        Jsonb(dict(outcome.metadata or {})),
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    cursor.execute(
                        """
                        select *, false as inserted
                        from strategy_market_outcomes
                        where run_id = %s and market_ticker = %s
                        """,
                        (outcome.run_id, outcome.market_ticker),
                    )
                    row = cursor.fetchone()
                else:
                    row = {**row, "inserted": True}
            connection.commit()
        if row is None:
            raise RuntimeError("strategy outcome neither inserted nor found existing row")
        return row_to_outcome(row)

    def get_outcome(
        self,
        *,
        run_id: str,
        market_ticker: str,
    ) -> StrategyMarketOutcome | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from strategy_market_outcomes
                    where run_id = %s and market_ticker = %s
                    """,
                    (run_id, market_ticker),
                )
                row = cursor.fetchone()
        return None if row is None else row_to_outcome(row)

    def latest_outcomes(self, *, run_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if run_id is not None:
            clauses.append("smo.run_id = %s")
            params.append(run_id)
        where = f"where {' and '.join(clauses)}" if clauses else ""
        params.append(limit)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select
                        smo.outcome_id,
                        smo.run_id,
                        pr.mode as runtime_mode,
                        smo.market_ticker,
                        smo.decision_timestamp,
                        smo.status,
                        smo.reason,
                        d.selected_side,
                        d.skip_reason,
                        d.metadata->>'selected_ev_dollars' as selected_ev_dollars,
                        rd.status as risk_status,
                        rd.reason as risk_reason,
                        po.status as paper_status,
                        po.filled_quantity,
                        prc.realized_pnl_dollars,
                        prc.unrealized_pnl_dollars,
                        smo.latency_checkpoints,
                        smo.metadata
                    from strategy_market_outcomes smo
                    join platform_runs pr on pr.run_id = smo.run_id
                    left join decisions d on d.decision_id = smo.decision_id
                    left join risk_decisions rd on rd.risk_decision_id = smo.risk_decision_id
                    left join paper_orders po on po.paper_order_id = smo.paper_order_id
                    left join paper_reconciliations prc on prc.paper_order_id = po.paper_order_id
                    {where}
                    order by smo.updated_at desc, smo.outcome_id desc
                    limit %s
                    """,
                    params,
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def counts(self, *, run_id: str | None = None) -> dict[str, int]:
        clauses: list[str] = []
        params: list[Any] = []
        if run_id is not None:
            clauses.append("smo.run_id = %s")
            params.append(run_id)
        where = f"where {' and '.join(clauses)}" if clauses else ""
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select
                        count(*)::int as terminal,
                        count(*) filter (where smo.status = 'handled')::int as handled,
                        count(*) filter (where smo.status = 'skipped')::int as skipped,
                        count(*) filter (where smo.status = 'error')::int as errored,
                        count(*) filter (where d.outcome = 'order_candidate')::int as selected,
                        count(*) filter (where rd.status = 'denied')::int as risk_denied,
                        count(*) filter (where po.status = 'filled')::int as paper_filled,
                        (
                            select count(*)::int
                            from live_order_attempts
                            where status = 'rejected'
                        ) as rejected
                    from strategy_market_outcomes smo
                    left join decisions d on d.decision_id = smo.decision_id
                    left join risk_decisions rd on rd.risk_decision_id = smo.risk_decision_id
                    left join paper_orders po on po.paper_order_id = smo.paper_order_id
                    {where}
                    """,
                    params,
                )
                row = cursor.fetchone()
        if row is None:
            return {}
        result = {key: int(row[key]) for key in row}
        if run_id is not None:
            result.update(self._metadata_counts(run_id))
        return result

    def latest_run(self) -> dict[str, Any] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select run_id, mode, market_series, status, started_at, metadata, created_at
                    from platform_runs
                    where metadata->>'runner' = 'alphadb.strategy'
                    order by created_at desc, run_id desc
                    limit 1
                    """
                )
                row = cursor.fetchone()
        return None if row is None else dict(row)

    def _metadata_counts(self, run_id: str) -> dict[str, int]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "select metadata from platform_runs where run_id = %s",
                    (run_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return {}
        metadata = dict(row["metadata"])
        latest_counts = metadata.get("latest_counts")
        if not isinstance(latest_counts, Mapping):
            return {}
        return {
            key: int(value)
            for key, value in latest_counts.items()
            if isinstance(value, int) or (isinstance(value, str) and value.isdigit())
        }


def row_to_outcome(row: Mapping[str, Any]) -> StrategyMarketOutcome:
    values = dict(row)
    values.setdefault("inserted", True)
    return StrategyMarketOutcome(
        outcome_id=str(values["outcome_id"]),
        run_id=str(values["run_id"]),
        market_ticker=str(values["market_ticker"]),
        decision_timestamp=values["decision_timestamp"],
        status=values["status"],
        reason=values["reason"],
        decision_id=values["decision_id"],
        risk_decision_id=values["risk_decision_id"],
        paper_order_id=values["paper_order_id"],
        latency_checkpoints=dict(values["latency_checkpoints"]),
        metadata=dict(values["metadata"]),
        inserted=bool(values["inserted"]),
    )


def fresh_outcome(
    *,
    run_id: str,
    market_ticker: str,
    decision_timestamp: datetime,
    status: StrategyOutcomeStatus,
    reason: str | None = None,
    decision_id: str | None = None,
    risk_decision_id: str | None = None,
    paper_order_id: str | None = None,
    latency_checkpoints: Mapping[str, float] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> StrategyMarketOutcome:
    return StrategyMarketOutcome(
        outcome_id=f"outcome_{uuid4().hex[:12]}",
        run_id=run_id,
        market_ticker=market_ticker,
        decision_timestamp=decision_timestamp,
        status=status,
        reason=reason,
        decision_id=decision_id,
        risk_decision_id=risk_decision_id,
        paper_order_id=paper_order_id,
        latency_checkpoints=latency_checkpoints or {},
        metadata=metadata or {},
    )
