from __future__ import annotations

from datetime import UTC, datetime

from alphadb.config import Settings, settings_from_env
from alphadb.deploy import (
    MigrationStatus,
    build_smoke_report,
    dashboard_auth_status,
    database_location,
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
    assert "secret" not in str(summary)
    assert database_location(settings.database_url) == "db.example.test:5432/alphadb"


def test_smoke_report_accepts_local_auth_disabled_when_dependencies_are_ready() -> None:
    settings = settings_from_env({"ALPHADB_ENV": "local", "ALPHADB_RUNTIME_MODE": "paper"})

    report = build_smoke_report(
        settings,
        health_collector=ok_health,
        migration_status_provider=no_pending_migrations,
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
    )

    assert report["ok"] is True
    assert report["dashboard_auth"]["enabled"] is True


def test_smoke_report_fails_on_pending_migrations_unless_allowed() -> None:
    settings = settings_from_env({"ALPHADB_ENV": "local"})

    blocked = build_smoke_report(
        settings,
        health_collector=ok_health,
        migration_status_provider=pending_migrations,
    )
    allowed = build_smoke_report(
        settings,
        health_collector=ok_health,
        migration_status_provider=pending_migrations,
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
