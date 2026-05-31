"""Small SQL migration runner for early target-platform state."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    version: str
    statements: tuple[str, ...]


INITIAL_OPERATIONAL_STATE = Migration(
    version="0001_operational_state",
    statements=(
        """
        create table if not exists schema_migrations (
            version text primary key,
            applied_at timestamptz not null default now()
        )
        """,
        """
        create table if not exists platform_runs (
            run_id text primary key,
            mode text not null,
            market_series text not null,
            status text not null,
            started_at timestamptz not null,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now()
        )
        """,
        """
        create table if not exists market_instances (
            market_ticker text primary key,
            series text not null,
            open_time timestamptz not null,
            close_time timestamptz not null,
            status text not null,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now()
        )
        """,
        """
        create table if not exists decisions (
            decision_id text primary key,
            run_id text not null references platform_runs(run_id),
            market_ticker text not null references market_instances(market_ticker),
            decision_timestamp timestamptz not null,
            outcome text not null,
            probability_yes numeric,
            selected_side text,
            skip_reason text,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            unique (run_id, market_ticker)
        )
        """,
        """
        create table if not exists risk_decisions (
            risk_decision_id text primary key,
            decision_id text not null unique references decisions(decision_id),
            status text not null,
            reason text,
            payload jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now()
        )
        """,
        """
        create table if not exists order_intents (
            order_intent_id text primary key,
            risk_decision_id text not null unique references risk_decisions(risk_decision_id),
            side text not null,
            price numeric not null,
            quantity integer not null,
            max_cost_dollars numeric not null,
            time_in_force text not null,
            created_at timestamptz not null default now()
        )
        """,
        "create index if not exists decisions_run_id_idx on decisions(run_id)",
        "create index if not exists market_instances_series_idx on market_instances(series)",
    ),
)


RAW_EVENT_LOG = Migration(
    version="0002_raw_event_log",
    statements=(
        """
        create table if not exists raw_events (
            raw_event_id text primary key,
            run_id text references platform_runs(run_id),
            market_ticker text references market_instances(market_ticker),
            source text not null,
            source_event_id text,
            received_at timestamptz not null,
            source_timestamp timestamptz,
            schema_version text not null,
            payload_hash text not null,
            payload jsonb not null,
            created_at timestamptz not null default now()
        )
        """,
        """
        create unique index if not exists raw_events_source_event_id_idx
        on raw_events(source, source_event_id)
        where source_event_id is not null
        """,
        """
        create index if not exists raw_events_replay_order_idx
        on raw_events(run_id, market_ticker, received_at, raw_event_id)
        """,
        """
        create index if not exists raw_events_source_schema_idx
        on raw_events(source, schema_version)
        """,
    ),
)


COLLECTOR_RUNS = Migration(
    version="0003_collector_runs",
    statements=(
        """
        create table if not exists collector_runs (
            collector_run_id text primary key,
            platform_run_id text not null references platform_runs(run_id),
            series text not null,
            source text not null,
            status text not null,
            started_at timestamptz not null,
            finished_at timestamptz,
            markets_discovered integer not null default 0,
            markets_collected integer not null default 0,
            raw_events_written integer not null default 0,
            errors jsonb not null default '[]'::jsonb,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now()
        )
        """,
        """
        create index if not exists collector_runs_series_started_at_idx
        on collector_runs(series, started_at desc)
        """,
        """
        create index if not exists collector_runs_status_idx
        on collector_runs(status)
        """,
    ),
)


MIGRATIONS: tuple[Migration, ...] = (
    INITIAL_OPERATIONAL_STATE,
    RAW_EVENT_LOG,
    COLLECTOR_RUNS,
)
