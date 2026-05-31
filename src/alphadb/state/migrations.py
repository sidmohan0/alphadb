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


MODEL_REGISTRY = Migration(
    version="0004_model_registry",
    statements=(
        """
        create table if not exists model_registry_records (
            model_id text primary key,
            series text not null,
            model_name text not null,
            model_version text not null,
            artifact_uri text not null,
            artifact_sha256 text not null
                check (artifact_sha256 ~ '^[a-f0-9]{64}$'),
            feature_version text not null,
            calibration_version text not null,
            dataset_id text not null,
            promotion_state text not null
                check (promotion_state in (
                    'candidate',
                    'shadow',
                    'paper',
                    'live',
                    'archived',
                    'rejected'
                )),
            report_uri text,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique (series, model_name, model_version)
        )
        """,
        """
        create index if not exists model_registry_series_state_idx
        on model_registry_records(series, promotion_state)
        """,
        """
        create index if not exists model_registry_dataset_idx
        on model_registry_records(dataset_id)
        """,
    ),
)


FEATURE_ROWS = Migration(
    version="0005_feature_rows",
    statements=(
        """
        create table if not exists feature_rows (
            feature_row_id text primary key,
            run_id text not null references platform_runs(run_id),
            market_ticker text not null references market_instances(market_ticker),
            model_id text not null references model_registry_records(model_id),
            decision_timestamp timestamptz not null,
            max_source_event_timestamp timestamptz not null,
            source_lag_ms bigint not null check (source_lag_ms >= 0),
            feature_version text not null,
            calibration_version text not null,
            dataset_id text not null,
            feature_values jsonb not null,
            source_event_ids text[] not null,
            row_hash text not null,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            unique (run_id, market_ticker, model_id, decision_timestamp)
        )
        """,
        """
        create index if not exists feature_rows_run_market_idx
        on feature_rows(run_id, market_ticker)
        """,
        """
        create index if not exists feature_rows_model_idx
        on feature_rows(model_id)
        """,
    ),
)


PAPER_EXECUTION = Migration(
    version="0006_paper_execution",
    statements=(
        """
        create table if not exists paper_orders (
            paper_order_id text primary key,
            order_intent_id text not null unique references order_intents(order_intent_id),
            risk_decision_id text not null references risk_decisions(risk_decision_id),
            market_ticker text not null references market_instances(market_ticker),
            side text not null check (side in ('yes', 'no')),
            limit_price numeric not null,
            quantity integer not null,
            filled_quantity integer not null default 0,
            status text not null,
            time_in_force text not null,
            submitted_at timestamptz not null,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now()
        )
        """,
        """
        create table if not exists paper_fills (
            paper_fill_id text primary key,
            paper_order_id text not null references paper_orders(paper_order_id),
            market_ticker text not null references market_instances(market_ticker),
            side text not null check (side in ('yes', 'no')),
            fill_price numeric not null,
            quantity integer not null,
            liquidity_role text not null,
            filled_at timestamptz not null,
            fee_dollars numeric not null default 0,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now()
        )
        """,
        """
        create table if not exists paper_positions (
            position_id text primary key,
            market_ticker text not null references market_instances(market_ticker),
            side text not null check (side in ('yes', 'no')),
            quantity integer not null,
            avg_price numeric not null,
            realized_pnl_dollars numeric not null default 0,
            unrealized_pnl_dollars numeric not null default 0,
            updated_at timestamptz not null,
            metadata jsonb not null default '{}'::jsonb,
            unique (market_ticker, side)
        )
        """,
        """
        create table if not exists paper_reconciliations (
            reconciliation_id text primary key,
            paper_order_id text not null unique references paper_orders(paper_order_id),
            status text not null,
            expected_quantity integer not null,
            filled_quantity integer not null,
            open_quantity integer not null,
            realized_pnl_dollars numeric not null default 0,
            unrealized_pnl_dollars numeric not null default 0,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now()
        )
        """,
        "create index if not exists paper_orders_market_idx on paper_orders(market_ticker)",
        "create index if not exists paper_fills_market_idx on paper_fills(market_ticker)",
    ),
)


SHADOW_COMPARISONS = Migration(
    version="0007_shadow_comparisons",
    statements=(
        """
        create table if not exists shadow_comparisons (
            comparison_id text primary key,
            market_ticker text not null,
            decision_timestamp timestamptz not null,
            status text not null,
            mismatch_count integer not null,
            intentional_difference_count integer not null,
            alpha_payload jsonb not null,
            current_mvp_payload jsonb,
            comparisons jsonb not null,
            created_at timestamptz not null default now()
        )
        """,
        """
        create index if not exists shadow_comparisons_market_time_idx
        on shadow_comparisons(market_ticker, decision_timestamp desc)
        """,
        """
        create index if not exists shadow_comparisons_status_idx
        on shadow_comparisons(status)
        """,
    ),
)


MIGRATIONS: tuple[Migration, ...] = (
    INITIAL_OPERATIONAL_STATE,
    RAW_EVENT_LOG,
    COLLECTOR_RUNS,
    MODEL_REGISTRY,
    FEATURE_ROWS,
    PAPER_EXECUTION,
    SHADOW_COMPARISONS,
)
