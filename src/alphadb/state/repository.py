"""Postgres repository for target-platform operational state."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.markets.spec import MarketSpec
from alphadb.state.migrations import MIGRATIONS
from alphadb.state.models import OperationalCounts, TracerRunRecord

MIGRATION_ADVISORY_LOCK_ID = 3947852101


class OperationalStateRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            yield connection

    def apply_migrations(self) -> list[str]:
        applied: list[str] = []
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select pg_advisory_xact_lock(%s)", (MIGRATION_ADVISORY_LOCK_ID,))
                cursor.execute("select to_regclass('public.schema_migrations') as table_name")
                table_row = cursor.fetchone()
                if table_row is None or table_row["table_name"] is None:
                    applied_versions: set[str] = set()
                else:
                    cursor.execute("select version from schema_migrations order by version")
                    applied_versions = {str(row["version"]) for row in cursor.fetchall()}
                for migration in MIGRATIONS:
                    if migration.version in applied_versions:
                        continue
                    for statement in migration.statements:
                        cursor.execute(statement)
                    cursor.execute(
                        """
                        insert into schema_migrations (version)
                        values (%s)
                        on conflict (version) do nothing
                        """,
                        (migration.version,),
                    )
                    if cursor.rowcount:
                        applied.append(migration.version)
                        applied_versions.add(migration.version)
            connection.commit()
        return applied

    def applied_migrations(self) -> list[str]:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select to_regclass('public.schema_migrations') as table_name")
                table_row = cursor.fetchone()
                if table_row is None or table_row["table_name"] is None:
                    return []
                cursor.execute("select version from schema_migrations order by version")
                return [str(row["version"]) for row in cursor.fetchall()]

    def pending_migrations(self) -> list[str]:
        applied = set(self.applied_migrations())
        return [migration.version for migration in MIGRATIONS if migration.version not in applied]

    def create_tracer_run(
        self,
        spec: MarketSpec,
        *,
        now: datetime | None = None,
    ) -> TracerRunRecord:
        timestamp = now or datetime.now(UTC)
        unique_suffix = uuid4().hex[:12]
        run_id = f"run_{unique_suffix}"
        market_ticker = f"{spec.series}-TRACER-{unique_suffix}"
        decision_id = f"dec_{unique_suffix}"
        risk_decision_id = f"risk_{unique_suffix}"
        order_intent_id = f"intent_{unique_suffix}"
        close_time = timestamp + timedelta(minutes=spec.horizon_minutes)

        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into platform_runs (
                        run_id, mode, market_series, status, started_at, metadata
                    )
                    values (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        "tracer",
                        spec.series,
                        "completed",
                        timestamp,
                        Jsonb({"spec_version": spec.spec_version}),
                    ),
                )
                cursor.execute(
                    """
                    insert into market_instances (
                        market_ticker, series, open_time, close_time, status, metadata
                    )
                    values (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        market_ticker,
                        spec.series,
                        timestamp,
                        close_time,
                        "tracer",
                        Jsonb({"horizon_minutes": spec.horizon_minutes}),
                    ),
                )
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
                    """,
                    (
                        decision_id,
                        run_id,
                        market_ticker,
                        timestamp,
                        "order_intent",
                        0.55,
                        "yes",
                        None,
                        Jsonb({"source": "operational_state_tracer"}),
                    ),
                )
                cursor.execute(
                    """
                    insert into risk_decisions (
                        risk_decision_id, decision_id, status, reason, payload
                    )
                    values (%s, %s, %s, %s, %s)
                    """,
                    (
                        risk_decision_id,
                        decision_id,
                        "approved",
                        "tracer",
                        Jsonb({"stake_cap_dollars": spec.risk_config.live_stake_cap_dollars}),
                    ),
                )
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
                        order_intent_id,
                        risk_decision_id,
                        "yes",
                        0.49,
                        1,
                        spec.risk_config.live_stake_cap_dollars,
                        spec.trading_cutoffs.time_in_force,
                    ),
                )
            connection.commit()

        return TracerRunRecord(
            run_id=run_id,
            market_ticker=market_ticker,
            decision_id=decision_id,
            risk_decision_id=risk_decision_id,
            order_intent_id=order_intent_id,
        )

    def get_run_summary(self, run_id: str) -> dict[str, str | int]:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        r.run_id,
                        r.mode,
                        r.market_series,
                        r.status,
                        count(distinct d.decision_id)::int as decisions,
                        count(distinct rd.risk_decision_id)::int as risk_decisions,
                        count(distinct oi.order_intent_id)::int as order_intents
                    from platform_runs r
                    left join decisions d on d.run_id = r.run_id
                    left join risk_decisions rd on rd.decision_id = d.decision_id
                    left join order_intents oi on oi.risk_decision_id = rd.risk_decision_id
                    where r.run_id = %s
                    group by r.run_id
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise KeyError(f"unknown run: {run_id}")
        return dict(row)

    def counts(self) -> OperationalCounts:
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        (select count(*)::int from platform_runs) as runs,
                        (select count(*)::int from market_instances) as market_instances,
                        (select count(*)::int from decisions) as decisions,
                        (select count(*)::int from risk_decisions) as risk_decisions,
                        (select count(*)::int from order_intents) as order_intents
                    """
                )
                row = cursor.fetchone()
        if row is None:
            raise RuntimeError("operational state count query returned no rows")
        return OperationalCounts(
            runs=int(row["runs"]),
            market_instances=int(row["market_instances"]),
            decisions=int(row["decisions"]),
            risk_decisions=int(row["risk_decisions"]),
            order_intents=int(row["order_intents"]),
        )
