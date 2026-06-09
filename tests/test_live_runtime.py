from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest

from alphadb.config import settings_from_env
from alphadb.live_runtime import (
    DEFAULT_EXPENSIVE_YES_LIVE_CONFIG,
    DEFAULT_FAIR_VALUE_LIVE_CONFIG,
    EXPENSIVE_YES_LIVE_STRATEGY,
    LiveRunStatusRepository,
    LiveRuntimeConfig,
    LiveRuntimeConfigRepository,
    build_fair_value_live_status,
    no_recent_live_run_status,
)
from alphadb.state.repository import OperationalStateRepository


def repository_or_skip() -> LiveRuntimeConfigRepository:
    database_url = settings_from_env().database_url
    repository = OperationalStateRepository(database_url)
    try:
        with repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    repository.apply_migrations()
    return LiveRuntimeConfigRepository(database_url)


def test_runtime_config_repository_seeds_reads_saves_and_lists_history() -> None:
    strategy = f"test_strategy_{uuid4().hex[:8]}"
    repository = repository_or_skip()

    seeded = repository.seed_defaults(strategy=strategy)
    active = repository.get_active_config(strategy=strategy)
    saved = repository.save_config(
        LiveRuntimeConfig(
            max_order_dollars=2.5,
            max_market_exposure_dollars=3.5,
            max_daily_loss_dollars=12.0,
            min_edge=0.05,
            max_markets=7,
            min_contract_price=0.25,
            market_context_source="brti_primary",
        ),
        strategy=strategy,
    )
    history = repository.recent_revisions(strategy=strategy, limit=5)

    assert seeded.version == 1
    assert seeded.config == DEFAULT_FAIR_VALUE_LIVE_CONFIG
    assert active is not None
    assert active.config_id == seeded.config_id
    assert saved.version == 2
    assert saved.config.max_market_exposure_dollars == 3.5
    assert saved.config.min_contract_price == 0.25
    assert saved.config.market_context_source == "brti_primary"
    assert saved.manifest_snapshot()["snapshot"]["market_context_source"] == "brti_primary"
    assert [revision.version for revision in history] == [2, 1]
    assert history[0].is_active is True
    assert history[1].is_active is False


def test_expensive_yes_runtime_config_defaults_are_strategy_specific() -> None:
    strategy = f"{EXPENSIVE_YES_LIVE_STRATEGY}_{uuid4().hex[:8]}"
    repository = repository_or_skip()

    seeded = repository.seed_defaults(strategy=strategy)
    fair_value_seeded = repository.seed_defaults(strategy=f"fair_{uuid4().hex[:8]}")

    assert seeded.config == DEFAULT_EXPENSIVE_YES_LIVE_CONFIG
    assert seeded.config.min_contract_price == 0.65
    assert seeded.config.max_order_dollars == 1.0
    assert seeded.config.max_market_exposure_dollars == 1.0
    assert seeded.config.max_daily_loss_dollars == 10.0
    assert seeded.config.max_markets == 10
    assert fair_value_seeded.config == DEFAULT_FAIR_VALUE_LIVE_CONFIG


def test_runtime_config_validation_blocks_malformed_values() -> None:
    with pytest.raises(ValueError, match="max_order_dollars"):
        LiveRuntimeConfig(
            max_order_dollars=0,
            max_market_exposure_dollars=3.5,
            max_daily_loss_dollars=12.0,
            min_edge=0.05,
            max_markets=7,
        ).validate()
    with pytest.raises(ValueError, match="max_markets"):
        LiveRuntimeConfig.from_payload({"max_markets": 0})
    with pytest.raises(ValueError, match="min_contract_price"):
        LiveRuntimeConfig.from_payload({"min_contract_price": 1.01})
    with pytest.raises(ValueError, match="market_context_source"):
        LiveRuntimeConfig.from_payload({"market_context_source": "brti"})


def test_live_status_summary_covers_submitted_no_fill_skipped_and_no_recent() -> None:
    manifest = {
        "run_id": "fv_live_status",
        "generated_at": "2026-06-04T15:00:00+00:00",
        "runtime_config": {
            "config_id": "cfg_1",
            "version": 3,
            "snapshot": {
                "max_order_dollars": 5.0,
                "max_market_exposure_dollars": 5.0,
                "max_daily_loss_dollars": 50.0,
                "min_edge": 0.0,
                "min_contract_price": 0.25,
                "max_markets": 20,
            },
        },
        "runtime_controls": {"live_orders_enabled": True, "orders_placed": 1},
        "market_context": {
            "market_context_source": "brti_primary",
            "external_close_source": "brti_latest_context",
        },
        "counts": {"live_attempts": 1, "replay_trades": 1},
        "live_edge_attribution": {
            "attribution_class": "threshold_drag",
            "edge": 0.03,
            "edge_shortfall": 0.02,
        },
        "candidate_live_edge_attributions": [
            {"attribution_class": "quote_freshness_suspect", "edge": 0.2}
        ],
    }
    submitted = build_fair_value_live_status(
        manifest=manifest,
        attempts_payload={
            "attempts": [
                {
                    "attempt_id": "attempt_1",
                    "submitted_at": "2026-06-04T15:00:00+00:00",
                    "market_ticker": "KXBTC15M-TEST",
                    "side": "yes",
                    "status": "submitted",
                    "reason": "submitted",
                }
            ]
        },
        reconciliation={
            "rows": [
                {
                    "attempt_id": "attempt_1",
                    "market_ticker": "KXBTC15M-TEST",
                    "filled_contracts": 0,
                    "settlement_status": "no_fill",
                }
            ],
            "per_market_exposure": {"markets": []},
        },
    )
    expensive = build_fair_value_live_status(
        manifest={
            **manifest,
            "run_id": "expensive_yes_live_status",
            "strategy": EXPENSIVE_YES_LIVE_STRATEGY,
            "runtime_config": {
                "config_id": "cfg_expensive",
                "version": 1,
                "strategy": EXPENSIVE_YES_LIVE_STRATEGY,
                "snapshot": {"min_contract_price": 0.65},
            },
            "runtime_controls": {
                "strategy": EXPENSIVE_YES_LIVE_STRATEGY,
                "live_orders_enabled": False,
                "orders_placed": 0,
            },
        },
        attempts_payload={
            "attempts": [
                {
                    "attempt_id": "attempt_expensive",
                    "submitted_at": "2026-06-04T15:00:00+00:00",
                    "market_ticker": "KXBTC15M-EXPENSIVE",
                    "side": "yes",
                    "status": "skipped",
                    "reason": "submit_live_orders_false",
                    "decision": {
                        "decision": "trade",
                        "side": "yes",
                        "observed_yes_ask": 0.7,
                        "yes_ask_threshold": 0.65,
                        "intended_contracts": 1,
                    },
                    "market_exposure": {"intended_contracts": 1, "sized_contracts": 1},
                    "max_loss_dollars": 0.70147,
                }
            ]
        },
        reconciliation={"rows": [], "per_market_exposure": {"markets": []}},
    )
    skipped = build_fair_value_live_status(
        manifest={**manifest, "run_id": "fv_live_skipped"},
        attempts_payload={
            "attempts": [
                {
                    "attempt_id": "attempt_2",
                    "submitted_at": "2026-06-04T15:01:00+00:00",
                    "market_ticker": "KXBTC15M-TEST",
                    "side": "yes",
                    "status": "skipped",
                    "reason": "daily_loss_cap_reached",
                    "live_edge_attribution": {
                        "attribution_class": "threshold_drag",
                        "edge": 0.03,
                    },
                }
            ]
        },
        reconciliation={"rows": [], "per_market_exposure": {"markets": []}},
    )
    no_recent = no_recent_live_run_status()

    assert submitted.decision_outcome == "submitted"
    assert submitted.fill_status == "no_fill"
    assert submitted.recent_no_fill_count == 1
    assert skipped.decision_outcome == "skipped"
    assert skipped.skip_reason == "daily_loss_cap_reached"
    assert skipped.selected_side == "yes"
    assert skipped.summary["live_edge_attribution"]["attribution_class"] == "threshold_drag"
    assert "candidate_live_edge_attributions" not in skipped.summary
    assert submitted.summary["market_context"]["market_context_source"] == "brti_primary"
    assert skipped.recent_attempts[0]["live_edge_attribution"]["edge"] == 0.03
    assert expensive.strategy == EXPENSIVE_YES_LIVE_STRATEGY
    assert expensive.recent_attempts[0]["observed_yes_ask"] == 0.7
    assert expensive.recent_attempts[0]["yes_ask_threshold"] == 0.65
    assert expensive.recent_attempts[0]["sized_contracts"] == 1
    assert expensive.recent_attempts[0]["max_loss_dollars"] == 0.70147
    assert no_recent.decision_outcome == "no_recent_run"


def test_live_status_recent_attempt_rows_keep_last_50() -> None:
    attempts = [
        {
            "submitted_at": f"2026-06-04T15:{minute:02d}:00+00:00",
            "market_ticker": f"KXBTC15M-{minute:02d}",
            "status": "skipped",
            "reason": "edge_below_min",
        }
        for minute in range(60)
    ]

    status = build_fair_value_live_status(
        manifest={
            "run_id": "fv_live_recent_attempt_limit",
            "generated_at": "2026-06-04T16:00:00+00:00",
            "runtime_config": {"snapshot": {}},
            "runtime_controls": {},
            "counts": {"live_attempts": len(attempts)},
        },
        attempts_payload={"attempts": attempts},
        reconciliation={"rows": []},
    )

    assert status.recent_attempt_count == 60
    assert len(status.recent_attempts) == 50
    assert status.recent_attempts[0]["market_ticker"] == "KXBTC15M-10"
    assert status.recent_attempts[-1]["market_ticker"] == "KXBTC15M-59"


def test_live_status_prefers_live_risk_day_accounting_over_full_history() -> None:
    status = build_fair_value_live_status(
        manifest={
            "run_id": "fv_live_status_daily_accounting",
            "generated_at": "2026-06-05T07:00:10+00:00",
            "runtime_config": {
                "config_id": "cfg_1",
                "version": 3,
                "snapshot": {
                    "max_market_exposure_dollars": 5.0,
                    "max_daily_loss_dollars": 50.0,
                },
            },
            "runtime_controls": {
                "live_orders_enabled": True,
                "daily_loss_accounting": {
                    "live_risk_day": "2026-06-05",
                    "timezone": "America/Los_Angeles",
                    "daily_loss_used_dollars": 0.41,
                },
            },
            "counts": {"live_attempts": 1, "replay_trades": 1},
        },
        attempts_payload={
            "attempts": [
                {
                    "attempt_id": "attempt_today",
                    "submitted_at": "2026-06-05T07:00:10+00:00",
                    "market_ticker": "KXBTC15M-TODAY",
                    "side": "yes",
                    "status": "submitted",
                    "reason": "submitted",
                }
            ]
        },
        reconciliation={
            "rows": [
                {
                    "attempt_id": "attempt_yesterday",
                    "market_ticker": "KXBTC15M-YESTERDAY",
                    "filled_contracts": 1,
                    "settlement_status": "unsettled",
                    "max_loss_dollars": 49.5,
                },
                {
                    "attempt_id": "attempt_today",
                    "market_ticker": "KXBTC15M-TODAY",
                    "filled_contracts": 1,
                    "settlement_status": "unsettled",
                    "max_loss_dollars": 0.41,
                },
            ],
            "per_market_exposure": {"markets": []},
        },
    )

    assert status.daily_loss_used_dollars == 0.41
    assert status.summary["daily_loss_accounting"]["live_risk_day"] == "2026-06-05"
    assert status.summary["full_history_daily_loss_used_dollars"] == 49.91


def test_live_status_surfaces_refresh_blocked_classification() -> None:
    status = build_fair_value_live_status(
        manifest={
            "run_id": "fv_live_status_refresh_blocked",
            "generated_at": "2026-06-05T07:00:10+00:00",
            "runtime_config": {"config_id": "cfg_1", "version": 3, "snapshot": {}},
            "runtime_controls": {
                "live_orders_enabled": True,
                "daily_loss_accounting": {"daily_loss_used_dollars": 0.41},
            },
            "live_risk_admission_state": {
                "status": "blocked",
                "reason": "unresolved_pending_reservation",
                "blocked_reason": "unresolved_pending_reservation",
                "pending_reservation_count": 1,
                "pending_reservation_ids": ["res_blocked"],
            },
            "live_risk_refresh": {
                "status": "blocked",
                "reason": "unresolved_pending_reservation",
                "lookup_count": 1,
                "unresolved_reservation_ids": ["res_blocked"],
                "state_version_after": 4,
            },
            "counts": {"live_attempts": 1, "replay_trades": 1},
        },
        attempts_payload={
            "attempts": [
                {
                    "attempt_id": "attempt_blocked",
                    "market_ticker": "KXBTC15M-BLOCKED",
                    "side": "yes",
                    "status": "skipped",
                    "reason": "unresolved_pending_reservation",
                }
            ]
        },
        reconciliation={"rows": [], "per_market_exposure": {"markets": []}},
    )

    assert status.skip_reason == "unresolved_pending_reservation"
    assert status.summary["live_risk_refresh"]["status"] == "blocked"
    assert status.summary["risk_state_classification"] == (
        "blocked_unresolved_pending_reservation"
    )


def test_live_run_status_repository_persists_dashboard_ready_summary() -> None:
    database_url = settings_from_env().database_url
    repository_or_skip()
    status_repository = LiveRunStatusRepository(database_url)
    status = build_fair_value_live_status(
        manifest={
            "run_id": f"fv_live_{uuid4().hex[:8]}",
            "generated_at": datetime.now(UTC).isoformat(),
            "runtime_config": {"config_id": "cfg_test", "version": 1, "snapshot": {}},
            "runtime_controls": {"live_orders_enabled": False},
            "counts": {"live_attempts": 0, "replay_trades": 0},
        },
        attempts_payload={"attempts": []},
        reconciliation={"rows": [], "per_market_exposure": {"markets": []}},
    )

    persisted = status_repository.persist(status)
    latest = status_repository.latest_status()

    assert persisted.run_id == status.run_id
    assert latest.run_id == status.run_id
    assert latest.decision_outcome == "skipped"
