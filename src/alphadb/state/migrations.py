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


MIGRATIONS: tuple[Migration, ...] = (INITIAL_OPERATIONAL_STATE,)
