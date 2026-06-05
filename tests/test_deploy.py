from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alphadb.config import Settings, settings_from_env
from alphadb.deploy import (
    MigrationStatus,
    build_smoke_report,
    dashboard_auth_status,
    database_location,
    runtime_config_status,
    runtime_guard_status,
    settings_summary,
)
from alphadb.health import ComponentHealth, HealthReport, HealthStatus


def ok_health(settings: Settings) -> HealthReport:
    return HealthReport(
        service="alphadb",
        environment=settings.environment,
        generated_at_utc=datetime(2026, 6, 1, 12, tzinfo=UTC),
        components=(
            ComponentHealth("package", HealthStatus.OK, "alphadb test"),
            ComponentHealth("postgres", HealthStatus.OK, "connection ok"),
        ),
    )


def no_pending_migrations(_) -> MigrationStatus:
    return MigrationStatus(
        ok=True,
        applied=["0001_operational_state"],
        pending=[],
        detail="all migrations applied",
    )


def pending_migrations(_) -> MigrationStatus:
    return MigrationStatus(
        ok=False,
        applied=[],
        pending=["0001_operational_state"],
        detail="pending migrations",
    )


def ok_runtime_config(_) -> dict:
    return {
        "ok": True,
        "detail": "active dashboard-owned live runtime config is readable",
        "config_id": "cfg_test",
        "version": 1,
    }


def test_settings_summary_keeps_database_credentials_out_of_smoke_output() -> None:
    settings = settings_from_env(
        {
            "DATABASE_URL": "postgresql://user:secret@db.example.test:5432/alphadb",
            "ALPHADB_DASHBOARD_PIN": "1234",
            "ALPHADB_DASHBOARD_COOKIE_SECRET": "cookie-secret",
        }
    )

    summary = settings_summary(settings)

    assert summary["database"] == "db.example.test:5432/alphadb"
    assert summary["dashboard_port"] == "8501"
    assert summary["live_stake_cap_dollars"] == 1.0
    assert summary["max_ticker_exposure_dollars"] == 1.0
    assert summary["max_daily_loss_dollars"] == 10.0
    assert "secret" not in str(summary)
    assert database_location(settings.database_url) == "db.example.test:5432/alphadb"


def test_smoke_report_accepts_local_auth_disabled_when_dependencies_are_ready() -> None:
    settings = settings_from_env({"ALPHADB_ENV": "local", "ALPHADB_RUNTIME_MODE": "paper"})

    report = build_smoke_report(
        settings,
        health_collector=ok_health,
        migration_status_provider=no_pending_migrations,
        runtime_config_status_provider=ok_runtime_config,
    )

    assert report["ok"] is True
    assert report["dashboard_auth"]["enabled"] is False
    assert report["dashboard_auth"]["required"] is False
    assert report["runtime_guard"]["can_submit_live_orders"] is False


def test_smoke_report_requires_dashboard_auth_for_aws_environment() -> None:
    settings = settings_from_env({"ALPHADB_ENV": "aws"})

    report = build_smoke_report(
        settings,
        health_collector=ok_health,
        migration_status_provider=no_pending_migrations,
        runtime_config_status_provider=ok_runtime_config,
    )

    assert report["ok"] is False
    assert report["dashboard_auth"]["required"] is True
    assert report["dashboard_auth"]["detail"] == "dashboard auth is required for AWS-like environments"


def test_smoke_report_accepts_aws_environment_with_pin_auth() -> None:
    settings = settings_from_env(
        {
            "ALPHADB_ENV": "aws",
            "ALPHADB_DASHBOARD_PIN": "1234",
            "ALPHADB_DASHBOARD_COOKIE_SECRET": "cookie-secret",
        }
    )

    report = build_smoke_report(
        settings,
        health_collector=ok_health,
        migration_status_provider=no_pending_migrations,
        runtime_config_status_provider=ok_runtime_config,
    )

    assert report["ok"] is True
    assert report["dashboard_auth"]["enabled"] is True


def test_smoke_report_fails_on_pending_migrations_unless_allowed() -> None:
    settings = settings_from_env({"ALPHADB_ENV": "local"})

    blocked = build_smoke_report(
        settings,
        health_collector=ok_health,
        migration_status_provider=pending_migrations,
        runtime_config_status_provider=ok_runtime_config,
    )
    allowed = build_smoke_report(
        settings,
        health_collector=ok_health,
        migration_status_provider=pending_migrations,
        runtime_config_status_provider=ok_runtime_config,
        allow_pending_migrations=True,
    )

    assert blocked["ok"] is False
    assert allowed["ok"] is True
    assert allowed["migrations"]["allow_pending"] is True


def test_runtime_guard_smoke_fails_when_live_order_submission_is_enabled() -> None:
    settings = settings_from_env(
        {
            "ALPHADB_RUNTIME_MODE": "gated-live",
            "ALPHADB_ENABLE_LIVE_ORDERS": "1",
            "ALPHADB_HUMAN_CUTOVER_APPROVED": "1",
            "KALSHI_API_KEY_ID": "key-id",
            "KALSHI_PRIVATE_KEY_PATH": "/tmp/key.pem",
        }
    )

    blocked = runtime_guard_status(settings)
    allowed = runtime_guard_status(settings, allow_live_orders=True)

    assert blocked["ok"] is False
    assert blocked["can_submit_live_orders"] is True
    assert allowed["ok"] is True


def test_dashboard_auth_can_be_required_outside_aws_environment() -> None:
    settings = settings_from_env({"ALPHADB_ENV": "local"})

    status = dashboard_auth_status(settings, require_dashboard_auth=True)

    assert status["ok"] is False
    assert status["required"] is True


def test_dashboard_fargate_template_can_run_in_private_or_public_subnets() -> None:
    template = Path("deploy/aws/ecs-fargate-dashboard.yaml").read_text(encoding="utf-8")

    assert "AssignPublicIp:" in template
    assert "Default: DISABLED" in template
    assert "AssignPublicIp: !Ref AssignPublicIp" in template
    assert "CpuArchitecture: ARM64" in template
    assert "DatabaseUrlSecretArn" in template
    assert "DashboardPinSecretArn" in template
    assert "DashboardCookieSecretArn" in template


def test_fair_value_live_aws_template_enables_live_money_with_minimal_caps() -> None:
    template = Path("deploy/aws/fair-value-live-trading-job.yaml").read_text(encoding="utf-8")
    deploy_script = Path("deploy/aws/deploy-fair-value-live-trading-job.sh").read_text(
        encoding="utf-8"
    )

    assert "fair-value-live-trading-job" in template
    assert "AWS::Events::Rule" in template
    assert "rate(1 minute)" in template
    assert "Default: DISABLED" in template
    assert 'ScheduleState="${SCHEDULE_STATE:-DISABLED}"' in deploy_script
    assert "--submit-live-orders" in template
    assert "ALPHADB_RUNTIME_MODE" in template
    assert "gated-live" in template
    assert "ALPHADB_ENABLE_LIVE_ORDERS" in template
    assert "ALPHADB_HUMAN_CUTOVER_APPROVED" in template
    assert "DatabaseUrlSecretArn" in template
    assert "DATABASE_URL" in template
    assert "--runtime-config-source" in template
    assert "postgres" in template
    assert "MaxOrderDollars" not in template
    assert "MaxTickerExposureDollars" not in template
    assert "--max-ticker-exposure-dollars" not in template
    assert "ALPHADB_MAX_TICKER_EXPOSURE_DOLLARS" not in template
    assert "MaxDailyLossDollars" not in template
    assert "KALSHI_API_KEY_ID" in template
    assert "KALSHI_PRIVATE_KEY_PEM" in template
    assert "s3:GetObject" in template
    assert "s3:PutObject" in template
    assert "s3:DeleteObject" in template


def test_runtime_config_status_reports_readable_active_config(monkeypatch) -> None:
    class FakeRevision:
        config_id = "cfg_test"
        version = 2
        strategy = "fair_value_live"

        class config:
            @staticmethod
            def as_dict() -> dict[str, float | int]:
                return {
                    "max_order_dollars": 5.0,
                    "max_market_exposure_dollars": 5.0,
                    "max_daily_loss_dollars": 50.0,
                    "min_edge": 0.0,
                    "max_markets": 20,
                }

    class FakeRepository:
        def __init__(self, database_url: str):
            self.database_url = database_url

        def seed_defaults(self) -> FakeRevision:
            return FakeRevision()

    monkeypatch.setattr("alphadb.deploy.LiveRuntimeConfigRepository", FakeRepository)
    settings = settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"})

    status = runtime_config_status(settings)

    assert status["ok"] is True
    assert status["config_id"] == "cfg_test"
