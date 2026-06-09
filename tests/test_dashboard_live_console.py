from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from alphadb.dashboard import app as dashboard_app
from alphadb.config import settings_from_env
from alphadb.dashboard.app import DASHBOARD_HTML, DashboardService
from alphadb.health import ComponentHealth, HealthReport, HealthStatus
from alphadb.live_runtime import (
    DEFAULT_EXPENSIVE_YES_LIVE_CONFIG,
    DEFAULT_FAIR_VALUE_LIVE_CONFIG,
    EXPENSIVE_YES_LIVE_STRATEGY,
    FAIR_VALUE_LIVE_STRATEGY,
    LiveRunStatus,
    LiveRuntimeConfig,
    LiveRuntimeConfigRevision,
    no_recent_live_run_status,
)
from alphadb.live_risk import LiveRiskAdmissionState


def ok_health(_) -> HealthReport:
    return HealthReport(
        service="alphadb",
        environment="local",
        generated_at_utc=datetime(2026, 6, 4, 15, tzinfo=UTC),
        components=(ComponentHealth("postgres", HealthStatus.OK, "connection ok"),),
    )


@dataclass
class FakeConfigRepository:
    database_url: str

    active: LiveRuntimeConfigRevision | None = None
    history: list[LiveRuntimeConfigRevision] | None = None

    def __post_init__(self) -> None:
        if self.active is None:
            self.active = revision(
                1,
                LiveRuntimeConfig(5.0, 5.0, 50.0, 0.0, 20),
                strategy=FAIR_VALUE_LIVE_STRATEGY,
            )
        if self.history is None:
            self.history = [self.active]
        self.by_strategy: dict[str, list[LiveRuntimeConfigRevision]] = {
            self.active.strategy: list(self.history)
        }

    def seed_defaults(self, *, strategy: str):
        if strategy not in self.by_strategy:
            config = (
                DEFAULT_EXPENSIVE_YES_LIVE_CONFIG
                if strategy == EXPENSIVE_YES_LIVE_STRATEGY
                else DEFAULT_FAIR_VALUE_LIVE_CONFIG
            )
            self.by_strategy[strategy] = [revision(1, config, strategy=strategy)]
        return self.by_strategy[strategy][0]

    def recent_revisions(self, *, strategy: str, limit: int):
        self.seed_defaults(strategy=strategy)
        return list(self.by_strategy[strategy])[:limit]

    def save_config(self, config: LiveRuntimeConfig, *, strategy: str, created_by: str):
        current = self.seed_defaults(strategy=strategy)
        saved = revision(current.version + 1, config, strategy=strategy)
        self.by_strategy[strategy] = [saved, *self.by_strategy.get(strategy, [])]
        if strategy == FAIR_VALUE_LIVE_STRATEGY:
            self.history = self.by_strategy[strategy]
            self.active = saved
        return saved


@dataclass
class FakeStatusRepository:
    database_url: str
    status: LiveRunStatus = no_recent_live_run_status()
    recent: list[dict[str, Any]] | None = None

    def latest_status(self, *, strategy: str) -> LiveRunStatus:
        if strategy == self.status.strategy:
            return self.status
        return no_recent_live_run_status(strategy=strategy)

    def recent_details(self, *, strategy: str, limit: int) -> list[dict[str, Any]]:
        if strategy != self.status.strategy:
            return []
        return list(self.recent or [])


@dataclass
class FakeLiveRiskRepository:
    database_url: str
    state: LiveRiskAdmissionState | None = None

    def get_state(self, *, strategy: str, live_risk_day):
        if self.state and self.state.strategy == strategy and self.state.live_risk_day == live_risk_day:
            return self.state
        return None

    def upsert_state(
        self,
        *,
        strategy: str,
        live_risk_day,
        daily_loss_used_dollars: float = 0.0,
        open_exposure_dollars: float = 0.0,
        pending_exposure_dollars: float = 0.0,
        per_market_exposure_dollars=None,
        pending_reservations=None,
        updated_at=None,
        status: str = "active",
        metadata=None,
    ):
        version = (self.state.version + 1) if self.state else 1
        self.state = LiveRiskAdmissionState(
            strategy=strategy,
            live_risk_day=live_risk_day,
            daily_loss_used_dollars=daily_loss_used_dollars,
            open_exposure_dollars=open_exposure_dollars,
            pending_exposure_dollars=pending_exposure_dollars,
            per_market_exposure_dollars=per_market_exposure_dollars or {},
            pending_reservations=pending_reservations or {},
            updated_at=updated_at or datetime(2026, 6, 4, 15, tzinfo=UTC),
            version=version,
            status=status,
            metadata=metadata or {},
        )
        return self.state


def revision(
    version: int,
    config: LiveRuntimeConfig,
    *,
    strategy: str,
) -> LiveRuntimeConfigRevision:
    return LiveRuntimeConfigRevision(
        config_id=f"cfg_{version}",
        strategy=strategy,
        version=version,
        is_active=True,
        config=config,
        created_by="dashboard",
        created_at=datetime(2026, 6, 4, 15, version, tzinfo=UTC),
    )


def service(
    repository: FakeConfigRepository,
    *,
    status: LiveRunStatus | None = None,
    recent: list[dict[str, Any]] | None = None,
    live_risk_repository: FakeLiveRiskRepository | None = None,
) -> DashboardService:
    risk_repository = live_risk_repository or FakeLiveRiskRepository(
        "postgresql://example.test/alphadb"
    )
    return DashboardService(
        settings=settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"}),
        config_repository_factory=lambda database_url: repository,
        status_repository_factory=lambda database_url: FakeStatusRepository(
            database_url,
            status=status or no_recent_live_run_status(),
            recent=recent,
        ),
        live_risk_repository_factory=lambda database_url: risk_repository,
        health_collector=ok_health,
        portfolio_balance_provider=lambda settings: {
            "status": "ok",
            "source": "kalshi",
            "portfolio_balance_dollars": 123.45,
            "cash_dollars": 67.89,
            "assets_dollars": 55.56,
            "observed_at_utc": "2026-06-04T15:00:00+00:00",
            "stale": False,
            "detail": None,
        },
    )


def test_dashboard_primary_route_is_live_first_and_not_a_table_dump() -> None:
    assert "Live Operator Console" in DASHBOARD_HTML
    assert "Runtime Config" in DASHBOARD_HTML
    assert "Min contract price" in DASHBOARD_HTML
    assert "Recent Attempts" in DASHBOARD_HTML
    assert "<th>Edge</th>" in DASHBOARD_HTML
    assert "<th>Min</th>" in DASHBOARD_HTML
    assert "<th>Gap</th>" in DASHBOARD_HTML
    assert "live_edge_attribution" in DASHBOARD_HTML
    assert "colspan='9'" in DASHBOARD_HTML
    assert "status.live_orders_enabled" in DASHBOARD_HTML
    assert "live runner active" in DASHBOARD_HTML
    assert (
        'data.runtime_guard?.can_submit_live_orders ? "live orders enabled"' not in DASHBOARD_HTML
    )
    assert "runtime_guard" not in DASHBOARD_HTML
    assert ">Research<" not in DASHBOARD_HTML
    assert ">Registry<" not in DASHBOARD_HTML
    assert ">Artifacts<" not in DASHBOARD_HTML
    assert "Data Store Counts" not in DASHBOARD_HTML
    assert "Market Universe" not in DASHBOARD_HTML


def test_live_payload_does_not_expose_dashboard_process_guard() -> None:
    repository = FakeConfigRepository("postgresql://example.test/alphadb")
    dashboard = service(repository)

    payload = dashboard.live_payload()

    assert "runtime_guard" not in payload
    assert payload["live_status"]["strategy"] == "fair_value_live"
    assert "summary" not in payload["live_status"]
    assert payload["portfolio_balance"]["portfolio_balance_dollars"] == 123.45
    assert payload["portfolio_balance"]["cash_dollars"] == 67.89
    assert payload["portfolio_balance"]["assets_dollars"] == 55.56


def test_strategy_operator_ledger_payload_returns_ordered_sparse_rows() -> None:
    repository = FakeConfigRepository("postgresql://example.test/alphadb")
    status = replace(
        no_recent_live_run_status(),
        run_id="fv_live_20260604T150000Z",
        generated_at=datetime(2026, 6, 4, 15, tzinfo=UTC),
        live_orders_enabled=True,
        decision_outcome="skipped",
        skip_reason="edge_below_min",
        latest_attempt_status="skipped",
        latest_attempt_reason="edge_below_min",
    )
    dashboard = service(repository, status=status)

    payload = dashboard.strategy_operator_ledger_payload()
    rows = payload["rows"]

    assert payload["schema_version"] == "strategy_operator_ledger/v1"
    assert [row["strategy_id"] for row in rows] == [
        FAIR_VALUE_LIVE_STRATEGY,
        EXPENSIVE_YES_LIVE_STRATEGY,
    ]
    assert rows[0]["display_name"] == "Fair-value live"
    assert rows[0]["health"] == "healthy"
    assert rows[0]["health_detail"] == "Latest run skipped: edge_below_min"
    assert rows[0]["live_state"] == "enabled"
    assert rows[0]["data_state"] == "available"
    assert rows[0]["latest_run_id"] == "fv_live_20260604T150000Z"
    assert rows[0]["latest_decision"]["outcome"] == "skipped"
    assert rows[0]["latest_decision"]["reason"] == "edge_below_min"
    assert rows[0]["risk_summary"]["state"] == "available"
    assert rows[0]["context_summary"]["active_source"] == "coinbase_primary"
    assert rows[0]["active_config"]["strategy"] == FAIR_VALUE_LIVE_STRATEGY
    assert rows[1]["display_name"] == "Expensive YES guarded live run"
    assert rows[1]["health"] == "unknown"
    assert rows[1]["health_detail"] == "No live run status recorded."
    assert rows[1]["live_state"] == "no_recent_run"
    assert rows[1]["data_state"] == "sparse"
    assert rows[1]["latest_run_id"] is None
    assert rows[1]["latest_decision"]["outcome"] == "no_recent_run"
    assert rows[1]["risk_summary"]["state"] == "sparse"
    assert rows[1]["context_summary"]["state"] == "sparse"
    assert rows[1]["active_config"]["strategy"] == EXPENSIVE_YES_LIVE_STRATEGY
    assert payload["fleet_health"]["counts"]["healthy"] == 1
    assert payload["fleet_health"]["counts"]["unknown"] == 1


def test_strategy_operator_ledger_caps_and_sorts_recent_runs() -> None:
    repository = FakeConfigRepository("postgresql://example.test/alphadb")
    status = replace(
        no_recent_live_run_status(),
        run_id="fv_live_latest",
        generated_at=datetime(2026, 6, 4, 15, 3, tzinfo=UTC),
        live_orders_enabled=True,
        decision_outcome="submitted",
        latest_attempt_status="submitted",
        current_market_ticker="KXBTC15M-LATEST",
        daily_loss_used_dollars=1.25,
        daily_loss_limit_dollars=50.0,
        market_exposure_used_dollars=2.0,
        market_exposure_limit_dollars=5.0,
        summary={
            "market_context": {
                "market_context_source": "brti_primary",
                "market_context_status": "fresh",
                "external_close_source": "brti",
            }
        },
    )
    recent = [
        {"run_id": "oldest", "generated_at": "2026-06-04T15:00:00+00:00"},
        {"run_id": "newest", "generated_at": "2026-06-04T15:03:00+00:00"},
        {"run_id": "middle", "generated_at": "2026-06-04T15:02:00+00:00"},
        {"run_id": "fourth", "generated_at": "2026-06-04T15:01:00+00:00"},
    ]
    dashboard = service(repository, status=status, recent=recent)

    row = dashboard.strategy_operator_ledger_payload()["rows"][0]

    assert [run["run_id"] for run in row["recent_runs"]] == ["newest", "middle", "fourth"]
    assert row["latest_decision"]["outcome"] == "submitted"
    assert row["latest_decision"]["market_ticker"] == "KXBTC15M-LATEST"
    assert row["risk_summary"]["detail"] == "Daily $1.25/$50.00; market $2.00/$5.00"
    assert row["context_summary"]["latest_run_source"] == "brti_primary"
    assert row["context_summary"]["latest_run_status"] == "fresh"


def test_strategy_operator_ledger_marks_repository_failures_unavailable() -> None:
    class BrokenStatusRepository:
        def __init__(self, database_url: str):
            self.database_url = database_url

        def latest_status(self, *, strategy: str) -> LiveRunStatus:
            raise RuntimeError("database unavailable")

    repository = FakeConfigRepository("postgresql://example.test/alphadb")
    dashboard = DashboardService(
        settings=settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"}),
        config_repository_factory=lambda database_url: repository,
        status_repository_factory=BrokenStatusRepository,
        health_collector=ok_health,
    )

    payload = dashboard.strategy_operator_ledger_payload()

    assert {row["data_state"] for row in payload["rows"]} == {"unavailable"}
    assert all(row["live_state"] == "unavailable" for row in payload["rows"])
    assert all(row["status_error"].startswith("RuntimeError: database unavailable") for row in payload["rows"])


def test_live_payload_preserves_recent_attempt_edge_attribution() -> None:
    repository = FakeConfigRepository("postgresql://example.test/alphadb")
    attribution = {
        "edge": 0.03,
        "min_edge": 0.05,
        "edge_shortfall": 0.02,
        "edge_margin": -0.02,
        "edge_cleared": False,
    }
    status = replace(
        no_recent_live_run_status(),
        recent_attempts=[
            {
                "submitted_at": "2026-06-04T15:00:00+00:00",
                "market_ticker": "KXBTC15M-EDGE",
                "status": "skipped",
                "reason": "edge_below_min",
                "fill_status": None,
                "live_edge_attribution": attribution,
            },
            {
                "submitted_at": "2026-06-04T15:01:00+00:00",
                "market_ticker": "KXBTC15M-MISSING",
                "status": "skipped",
                "reason": "missing_orderbook_quote",
                "fill_status": None,
            },
        ],
    )
    dashboard = service(repository, status=status)

    payload = dashboard.live_payload()
    attempts = payload["live_status"]["recent_attempts"]

    assert attempts[0]["reason"] == "edge_below_min"
    assert attempts[0]["live_edge_attribution"]["edge"] == 0.03
    assert attempts[0]["live_edge_attribution"]["min_edge"] == 0.05
    assert attempts[0]["live_edge_attribution"]["edge_shortfall"] == 0.02
    assert "live_edge_attribution" not in attempts[1]


def test_cockpit_recent_attempts_table_renders_edge_diagnostics() -> None:
    source = Path("apps/dashboard/components/live/live-operations.tsx").read_text()

    assert "Activity Feed" in source
    assert "ACTIVITY_FEED_LIMIT = 50" in source
    assert 'label="Edge"' in source
    assert 'label="Min"' in source
    assert 'label="Gap"' in source
    assert "optionalPercent(attribution.edge)" in source
    assert "optionalPercent(attribution.min_edge)" in source
    assert "edgeGapText(attribution)" in source
    assert "short ${optionalPercent(shortfall)}" in source
    assert "colSpan={9}" in source
    assert "ResizableDraggablePanel" in source
    assert "PanelVisibilityMenu" in source
    assert "hiddenPanelIds" in source
    assert "Hide ${definition.label}" in source
    assert "hidden: hiddenPanelIds" in source
    assert "window.localStorage" in source


def test_cockpit_runtime_config_exposes_daily_limit_reset_action() -> None:
    source = Path("apps/dashboard/components/live/live-operations.tsx").read_text()

    assert "/live/reset-daily-limits" in source
    assert "Reset daily" in source
    assert "setDailyLimitsResetting" in source
    assert "Open and pending exposure will remain reserved" in source


def test_cockpit_home_renders_api_backed_strategy_operator_ledger() -> None:
    page_source = Path("apps/dashboard/app/page.tsx").read_text()
    component_source = Path(
        "apps/dashboard/components/live/strategy-operator-ledger.tsx"
    ).read_text()
    app_source = Path("src/alphadb/dashboard/app.py").read_text()

    assert "StrategyOperatorLedger" in page_source
    assert "StrategySummaryCardPrototype" not in page_source
    assert 'apiGet<StrategyLedgerPayload>("/live/ledger")' in component_source
    assert 'path == "/api/live/ledger"' in app_source
    assert "setSelectedStrategyId" in component_source
    assert "VISIBILITY_STORAGE_KEY" in component_source
    assert "window.localStorage" in component_source
    assert "RecentRunChips" in component_source
    assert "RiskMeter" in component_source
    assert not Path("apps/dashboard/components/live/strategy-summary-card-prototype.tsx").exists()
    assert not Path("apps/dashboard/components/prototype/prototype-switcher.tsx").exists()
    assert "sample state" not in component_source


def test_live_payload_keeps_simulated_summary_out_of_dashboard_api() -> None:
    repository = FakeConfigRepository("postgresql://example.test/alphadb")
    status = replace(
        no_recent_live_run_status(),
        run_id="fv_live_20260604T232706Z",
        generated_at=datetime(2026, 6, 4, 23, 27, tzinfo=UTC),
        live_orders_enabled=True,
        summary={
            "report_summary": {
                "simulated_replay_net_pnl_dollars": 100.0,
                "simulated_replay_settlement_status": "unreconciled",
            },
            "runtime_controls": {"paper_orders_allowed": True},
        },
    )
    dashboard = DashboardService(
        settings=settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"}),
        config_repository_factory=lambda database_url: repository,
        status_repository_factory=lambda database_url: FakeStatusRepository(
            database_url,
            status=status,
        ),
        health_collector=ok_health,
    )

    payload = dashboard.live_payload()
    encoded = json.dumps(payload, sort_keys=True)

    assert "summary" not in payload["live_status"]
    assert "simulated_replay" not in encoded
    assert "paper_orders" not in encoded


def test_dashboard_service_saves_config_and_reloads_active_values() -> None:
    repository = FakeConfigRepository("postgresql://example.test/alphadb")
    dashboard = service(repository)

    saved = dashboard.save_config(
        {
            "max_order_dollars": 2.25,
            "max_market_exposure_dollars": 3.5,
            "max_daily_loss_dollars": 12.0,
            "min_edge": 0.05,
            "min_contract_price": 0.25,
            "max_markets": 7,
            "market_context_source": "brti_primary",
        }
    )
    payload = dashboard.live_payload()

    assert saved["active_config"]["version"] == 2
    assert payload["active_config"]["max_order_dollars"] == 2.25
    assert payload["active_config"]["max_market_exposure_dollars"] == 3.5
    assert payload["active_config"]["min_contract_price"] == 0.25
    assert payload["active_config"]["market_context_source"] == "brti_primary"
    assert payload["market_context"]["active_source"] == "brti_primary"
    assert payload["market_context"]["brti_latest"]["status"] == "unavailable"
    assert [row["version"] for row in payload["config_history"]] == [2, 1]


def test_dashboard_service_resets_realized_daily_loss_without_erasing_exposure() -> None:
    repository = FakeConfigRepository("postgresql://example.test/alphadb")
    risk_repository = FakeLiveRiskRepository(
        "postgresql://example.test/alphadb",
        state=LiveRiskAdmissionState(
            strategy=FAIR_VALUE_LIVE_STRATEGY,
            live_risk_day=date(2026, 6, 4),
            daily_loss_used_dollars=12.5,
            open_exposure_dollars=4.25,
            pending_exposure_dollars=0.75,
            per_market_exposure_dollars={"KXBTC15M-OPEN": 4.25, "KXBTC15M-PENDING": 0.75},
            pending_reservations={
                "res_pending": {
                    "reservation_id": "res_pending",
                    "market_ticker": "KXBTC15M-PENDING",
                    "max_loss_dollars": 0.75,
                }
            },
            updated_at=datetime(2026, 6, 4, 15, tzinfo=UTC),
            version=3,
        ),
    )
    dashboard = service(repository, live_risk_repository=risk_repository)

    result = dashboard.reset_daily_limits(
        {"strategy": FAIR_VALUE_LIVE_STRATEGY},
        now=datetime(2026, 6, 5, 0, 30, tzinfo=UTC),
    )

    state = risk_repository.state
    assert result["live_risk_day"] == "2026-06-04"
    assert state is not None
    assert state.daily_loss_used_dollars == 0.0
    assert state.open_exposure_dollars == 4.25
    assert state.pending_exposure_dollars == 0.75
    assert state.pending_reservations["res_pending"]["market_ticker"] == "KXBTC15M-PENDING"
    assert state.metadata["last_daily_loss_reset"]["previous_daily_loss_used_dollars"] == 12.5
    assert result["live_risk_admission_state"]["daily_loss_used_dollars"] == 0.0


def test_dashboard_service_exposes_compact_market_context_from_latest_run() -> None:
    repository = FakeConfigRepository("postgresql://example.test/alphadb")
    repository.save_config(
        LiveRuntimeConfig(
            max_order_dollars=5.0,
            max_market_exposure_dollars=5.0,
            max_daily_loss_dollars=50.0,
            min_edge=0.0,
            max_markets=1,
            min_contract_price=0.25,
            market_context_source="brti_primary",
        ),
        strategy=FAIR_VALUE_LIVE_STRATEGY,
        created_by="test",
    )
    status = replace(
        no_recent_live_run_status(),
        run_id="fv_live_brti_context",
        generated_at=datetime(2026, 6, 4, 15, tzinfo=UTC),
        current_market_ticker="KXBTC15M-BRTI",
        decision_outcome="skipped",
        latest_attempt_status="skipped",
        latest_attempt_reason="brti_context_missing",
        skip_reason="brti_context_missing",
        summary={
            "market_context": {
                "market_context_source": "brti_primary",
                "market_context_status": "missing",
                "external_close_source": None,
                "brti": {
                    "index_id": "BRTI",
                    "context_status": "missing",
                    "context_reason": "missing_brti_latest_context",
                },
                "coinbase_diagnostics": {
                    "status": "available",
                    "basis_dollars": 0.25,
                    "basis_pct": 0.0000025,
                },
            }
        },
        recent_attempts=[
            {
                "submitted_at": "2026-06-04T15:00:00+00:00",
                "market_ticker": "KXBTC15M-BRTI",
                "status": "skipped",
                "reason": "brti_context_missing",
            }
        ],
    )
    dashboard = service(repository, status=status)

    payload = dashboard.live_payload()

    assert "summary" not in payload["live_status"]
    assert payload["live_status"]["latest_attempt_reason"] == "brti_context_missing"
    assert payload["market_context"]["active_source"] == "brti_primary"
    assert payload["market_context"]["latest_run"]["market_context_status"] == "missing"
    assert payload["market_context"]["coinbase_diagnostics"]["basis_dollars"] == 0.25


def test_dashboard_brti_latest_payload_includes_current_value_when_available(
    monkeypatch,
) -> None:
    now = datetime(2026, 6, 4, 15, tzinfo=UTC)

    class FakeContext:
        value = Decimal("101.25")
        source_timestamp = now
        received_at = now
        source_lag_ms = 125
        raw_event_id = "evt_brti_latest"
        payload_hash = "abc123"

    class FakeStatus:
        index_id = "BRTI"
        status = "usable"
        reason = None
        generated_at = now
        age_ms = 1000
        context = FakeContext()

    class FakeBRTIRepository:
        def __init__(self, database_url: str):
            self.database_url = database_url

        def get_latest(self, **kwargs):
            return FakeStatus()

    monkeypatch.setattr(dashboard_app, "BRTILatestContextRepository", FakeBRTIRepository)

    payload = dashboard_app.brti_latest_context_payload(
        settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"})
    )

    assert payload["status"] == "usable"
    assert payload["value"] == "101.25"
    assert payload["age_seconds"] == 1.0
    assert payload["source_lag_ms"] == 125
    assert payload["raw_event_id"] == "evt_brti_latest"


def test_dashboard_service_keeps_expensive_yes_config_isolated() -> None:
    repository = FakeConfigRepository("postgresql://example.test/alphadb")
    dashboard = service(repository)

    expensive_payload = dashboard.live_payload(strategy=EXPENSIVE_YES_LIVE_STRATEGY)
    saved = dashboard.save_config(
        {
            "strategy": EXPENSIVE_YES_LIVE_STRATEGY,
            "max_order_dollars": 0.95,
            "max_market_exposure_dollars": 1.0,
            "max_daily_loss_dollars": 9.0,
            "min_edge": 0.0,
            "min_contract_price": 0.7,
            "max_markets": 8,
        }
    )
    fair_value_payload = dashboard.live_payload()
    expensive_after = dashboard.live_payload(strategy=EXPENSIVE_YES_LIVE_STRATEGY)

    assert expensive_payload["active_config"]["strategy"] == EXPENSIVE_YES_LIVE_STRATEGY
    assert expensive_payload["active_config"]["min_contract_price"] == 0.65
    assert expensive_payload["strategy_metadata"]["threshold_label"] == "YES ask threshold"
    assert saved["active_config"]["min_contract_price"] == 0.7
    assert expensive_after["active_config"]["max_order_dollars"] == 0.95
    assert fair_value_payload["active_config"]["strategy"] == FAIR_VALUE_LIVE_STRATEGY
    assert fair_value_payload["active_config"]["max_order_dollars"] == 5.0


def test_dashboard_service_rejects_invalid_config_without_saving() -> None:
    repository = FakeConfigRepository("postgresql://example.test/alphadb")
    dashboard = service(repository)

    with pytest.raises(ValueError, match="max_order_dollars"):
        dashboard.save_config(
            {
                "max_order_dollars": -1,
                "max_market_exposure_dollars": 3.5,
                "max_daily_loss_dollars": 12.0,
                "min_edge": 0.05,
                "min_contract_price": 0.25,
                "max_markets": 7,
            }
        )
    with pytest.raises(ValueError, match="market_context_source"):
        dashboard.save_config(
            {
                "max_order_dollars": 1,
                "max_market_exposure_dollars": 3.5,
                "max_daily_loss_dollars": 12.0,
                "min_edge": 0.05,
                "min_contract_price": 0.25,
                "max_markets": 7,
                "market_context_source": "brti",
            }
        )

    assert repository.active.version == 1
