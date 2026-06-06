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


STRATEGY_RUNTIME = Migration(
    version="0008_strategy_runtime",
    statements=(
        """
        create table if not exists strategy_market_outcomes (
            outcome_id text primary key,
            run_id text not null references platform_runs(run_id),
            market_ticker text not null references market_instances(market_ticker),
            decision_timestamp timestamptz not null,
            status text not null,
            reason text,
            decision_id text references decisions(decision_id),
            risk_decision_id text references risk_decisions(risk_decision_id),
            paper_order_id text references paper_orders(paper_order_id),
            latency_checkpoints jsonb not null default '{}'::jsonb,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique (run_id, market_ticker)
        )
        """,
        """
        create table if not exists current_mvp_decision_boundaries (
            import_id text primary key,
            market_ticker text not null,
            decision_timestamp timestamptz not null,
            schema_version text not null,
            source_identity text not null,
            source_hash text not null,
            record_hash text not null,
            boundary_payload jsonb not null,
            raw_payload jsonb not null,
            intentional_differences jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            unique (market_ticker, decision_timestamp, record_hash)
        )
        """,
        """
        create table if not exists live_order_attempts (
            live_order_attempt_id text primary key,
            order_intent_id text references order_intents(order_intent_id),
            risk_decision_id text,
            market_ticker text,
            runtime_mode text not null,
            status text not null,
            guard_reason text,
            request_payload jsonb not null default '{}'::jsonb,
            response_payload jsonb,
            created_at timestamptz not null default now()
        )
        """,
        "alter table shadow_comparisons alter column alpha_payload drop not null",
        """
        create index if not exists strategy_market_outcomes_run_status_idx
        on strategy_market_outcomes(run_id, status)
        """,
        """
        create index if not exists strategy_market_outcomes_updated_idx
        on strategy_market_outcomes(updated_at desc)
        """,
        """
        create index if not exists current_mvp_boundaries_lookup_idx
        on current_mvp_decision_boundaries(market_ticker, decision_timestamp desc)
        """,
        """
        create index if not exists live_order_attempts_status_idx
        on live_order_attempts(status, created_at desc)
        """,
    ),
)


LIVE_RUNTIME_CONFIG = Migration(
    version="0009_live_runtime_config",
    statements=(
        """
        create table if not exists live_runtime_configs (
            config_id text primary key,
            strategy text not null,
            version integer not null check (version >= 1),
            is_active boolean not null default true,
            max_order_dollars numeric not null check (max_order_dollars > 0),
            max_market_exposure_dollars numeric not null
                check (max_market_exposure_dollars > 0),
            max_daily_loss_dollars numeric not null check (max_daily_loss_dollars > 0),
            min_edge numeric not null check (min_edge >= 0),
            min_contract_price numeric not null default 0.25
                check (min_contract_price >= 0 and min_contract_price <= 1),
            max_markets integer not null check (max_markets >= 1),
            snapshot jsonb not null default '{}'::jsonb,
            created_by text not null default 'dashboard',
            created_at timestamptz not null default now(),
            unique (strategy, version)
        )
        """,
        """
        create unique index if not exists live_runtime_configs_active_idx
        on live_runtime_configs(strategy)
        where is_active
        """,
        """
        create index if not exists live_runtime_configs_strategy_created_idx
        on live_runtime_configs(strategy, created_at desc)
        """,
    ),
)


LIVE_RUN_STATUS = Migration(
    version="0010_live_run_status",
    statements=(
        """
        create table if not exists live_run_statuses (
            run_id text primary key,
            strategy text not null,
            generated_at timestamptz not null,
            config_id text,
            config_version integer,
            live_orders_enabled boolean not null default false,
            current_market_ticker text,
            decision_outcome text not null,
            selected_side text,
            skip_reason text,
            latest_attempt_status text,
            latest_attempt_reason text,
            fill_status text,
            daily_loss_used_dollars numeric not null default 0,
            daily_loss_limit_dollars numeric not null default 0,
            market_exposure_used_dollars numeric not null default 0,
            market_exposure_limit_dollars numeric not null default 0,
            recent_attempt_count integer not null default 0,
            recent_submitted_count integer not null default 0,
            recent_skipped_count integer not null default 0,
            recent_no_fill_count integer not null default 0,
            recent_filled_count integer not null default 0,
            summary jsonb not null default '{}'::jsonb,
            recent_attempts jsonb not null default '[]'::jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """,
        """
        create index if not exists live_run_statuses_strategy_generated_idx
        on live_run_statuses(strategy, generated_at desc)
        """,
    ),
)


AGENT_FIRST_DASHBOARD = Migration(
    version="0011_agent_first_dashboard",
    statements=(
        """
        create table if not exists dashboard_strategies (
            strategy_id text primary key,
            name text not null,
            brief text not null default '',
            spec jsonb not null default '{}'::jsonb,
            status text not null check (status in ('draft', 'active', 'archived')),
            promotion_stage text not null default 'draft',
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """,
        """
        create table if not exists lab_entries (
            lab_entry_id text primary key,
            title text not null,
            hypothesis text not null default '',
            brief text not null default '',
            status text not null default 'active',
            verdict text check (verdict in ('continue', 'revise', 'kill') or verdict is null),
            blockers jsonb not null default '[]'::jsonb,
            evidence jsonb not null default '[]'::jsonb,
            strategy jsonb not null default '{}'::jsonb,
            runs jsonb not null default '[]'::jsonb,
            notes jsonb not null default '[]'::jsonb,
            insights jsonb not null default '[]'::jsonb,
            metrics jsonb not null default '{}'::jsonb,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """,
        """
        alter table lab_entries
        add column if not exists blockers jsonb not null default '[]'::jsonb
        """,
        """
        alter table lab_entries
        add column if not exists evidence jsonb not null default '[]'::jsonb
        """,
        """
        alter table lab_entries
        add column if not exists strategy jsonb not null default '{}'::jsonb
        """,
        """
        alter table lab_entries
        add column if not exists runs jsonb not null default '[]'::jsonb
        """,
        """
        alter table lab_entries
        add column if not exists notes jsonb not null default '[]'::jsonb
        """,
        """
        alter table lab_entries
        add column if not exists insights jsonb not null default '[]'::jsonb
        """,
        """
        do $$
        begin
            if exists (
                select 1
                from information_schema.columns
                where table_schema = 'public'
                  and table_name = 'lab_entries'
                  and column_name = 'kind'
            ) then
                alter table lab_entries alter column kind set default 'experiment';
            end if;
        end
        $$;
        """,
        """
        create index if not exists dashboard_strategies_updated_idx
        on dashboard_strategies(updated_at desc)
        """,
        """
        create index if not exists lab_entries_status_updated_idx
        on lab_entries(status, updated_at desc)
        """,
    ),
)


LIVE_RUNTIME_MIN_CONTRACT_PRICE = Migration(
    version="0012_live_runtime_min_contract_price",
    statements=(
        """
        alter table live_runtime_configs
        add column if not exists min_contract_price numeric not null default 0.25
            check (min_contract_price >= 0 and min_contract_price <= 1)
        """,
        """
        update live_runtime_configs
        set snapshot = coalesce(snapshot, '{}'::jsonb)
            || jsonb_build_object('min_contract_price', min_contract_price)
        where not (coalesce(snapshot, '{}'::jsonb) ? 'min_contract_price')
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
    STRATEGY_RUNTIME,
    LIVE_RUNTIME_CONFIG,
    LIVE_RUN_STATUS,
    AGENT_FIRST_DASHBOARD,
    LIVE_RUNTIME_MIN_CONTRACT_PRICE,
)
