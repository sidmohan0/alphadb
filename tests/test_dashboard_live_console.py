from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from alphadb.config import settings_from_env
from alphadb.dashboard.app import DASHBOARD_HTML, DashboardService
from alphadb.health import ComponentHealth, HealthReport, HealthStatus
from alphadb.live_runtime import (
    LiveRunStatus,
    LiveRuntimeConfig,
    LiveRuntimeConfigRevision,
    no_recent_live_run_status,
)


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
            self.active = revision(1, LiveRuntimeConfig(5.0, 5.0, 50.0, 0.0, 20))
        if self.history is None:
            self.history = [self.active]

    def seed_defaults(self, *, strategy: str):
        return self.active

    def recent_revisions(self, *, strategy: str, limit: int):
        return list(self.history or [])[:limit]

    def save_config(self, config: LiveRuntimeConfig, *, strategy: str, created_by: str):
        saved = revision((self.active.version if self.active else 0) + 1, config)
        if self.active is not None:
            self.history = [saved, self.active]
        else:
            self.history = [saved]
        self.active = saved
        return saved


@dataclass
class FakeStatusRepository:
    database_url: str
    status: LiveRunStatus = no_recent_live_run_status()

    def latest_status(self, *, strategy: str) -> LiveRunStatus:
        return self.status

    def recent_details(self, *, strategy: str, limit: int) -> list[dict[str, Any]]:
        return []


def revision(version: int, config: LiveRuntimeConfig) -> LiveRuntimeConfigRevision:
    return LiveRuntimeConfigRevision(
        config_id=f"cfg_{version}",
        strategy="fair_value_live",
        version=version,
        is_active=True,
        config=config,
        created_by="dashboard",
        created_at=datetime(2026, 6, 4, 15, version, tzinfo=UTC),
    )


def service(repository: FakeConfigRepository) -> DashboardService:
    return DashboardService(
        settings=settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"}),
        config_repository_factory=lambda database_url: repository,
        status_repository_factory=FakeStatusRepository,
        health_collector=ok_health,
    )


def test_dashboard_primary_route_is_live_first_and_not_a_table_dump() -> None:
    assert "Live Operator Console" in DASHBOARD_HTML
    assert "Runtime Config" in DASHBOARD_HTML
    assert "Recent Attempts" in DASHBOARD_HTML
    assert "status.live_orders_enabled" in DASHBOARD_HTML
    assert "live runner active" in DASHBOARD_HTML
    assert "data.runtime_guard?.can_submit_live_orders ? \"live orders enabled\"" not in DASHBOARD_HTML
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
            "max_markets": 7,
        }
    )
    payload = dashboard.live_payload()

    assert saved["active_config"]["version"] == 2
    assert payload["active_config"]["max_order_dollars"] == 2.25
    assert payload["active_config"]["max_market_exposure_dollars"] == 3.5
    assert [row["version"] for row in payload["config_history"]] == [2, 1]


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
                "max_markets": 7,
            }
        )

    assert repository.active.version == 1
