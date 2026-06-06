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
    assert (
        report["dashboard_auth"]["detail"] == "dashboard auth is required for AWS-like environments"
    )


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


def test_dashboard_fargate_template_defines_public_cockpit_and_private_api() -> None:
    template = Path("deploy/aws/ecs-fargate-dashboard.yaml").read_text(encoding="utf-8")
    cockpit_task = template.split("CockpitTaskDefinition:", maxsplit=1)[1].split(
        "AlphaDbApiTaskDefinition:",
        maxsplit=1,
    )[0]
    api_task = template.split("AlphaDbApiTaskDefinition:", maxsplit=1)[1].split(
        "AlphaDbApiService:",
        maxsplit=1,
    )[0]
    api_service = template.split("AlphaDbApiService:", maxsplit=1)[1].split(
        "CockpitService:",
        maxsplit=1,
    )[0]
    cockpit_service = template.split("CockpitService:", maxsplit=1)[1].split(
        "Outputs:",
        maxsplit=1,
    )[0]

    assert "AssignPublicIp:" in template
    assert "Default: DISABLED" in template
    assert "AssignPublicIp: !Ref AssignPublicIp" in template
    assert "CpuArchitecture: ARM64" in template
    assert "CockpitContainerImage" in template
    assert "AlphaDbApiContainerImage" in template
    assert "DatabaseUrlSecretArn" in template
    assert "CockpitPinSecretArn" in template
    assert "CockpitCookieSecretArn" in template
    assert "AWS::ServiceDiscovery::PrivateDnsNamespace" in template
    assert "AWS::ServiceDiscovery::Service" in template
    assert "Name: ALPHADB_API_BASE_URL" in cockpit_task
    assert "http://alphadb-api.${PrivateNamespaceName}:${AlphaDbApiPort}" in cockpit_task
    assert "Name: ALPHADB_COCKPIT_PIN" in cockpit_task
    assert "Name: ALPHADB_COCKPIT_COOKIE_SECRET" in cockpit_task
    assert "DATABASE_URL" not in cockpit_task
    assert "Name: DATABASE_URL" in api_task
    assert "Name: ALPHADB_DASHBOARD_PIN" in api_task
    assert "LoadBalancers:" not in api_service
    assert "ServiceRegistries:" in api_service
    assert "LoadBalancers:" in cockpit_service
    assert "SourceSecurityGroupId: !Ref CockpitServiceSecurityGroup" in template
    assert "AWS::Events::Rule" not in template


def test_cockpit_deploy_script_builds_two_images_and_runs_smoke_without_raw_secrets() -> None:
    deploy_script = Path("deploy/aws/deploy-cockpit-stack.sh").read_text(encoding="utf-8")
    smoke_script = Path("deploy/aws/smoke-cockpit-stack.sh").read_text(encoding="utf-8")
    local_auth_smoke = Path("apps/dashboard/scripts/smoke-auth.sh").read_text(encoding="utf-8")

    assert 'COCKPIT_IMAGE_TAG="${COCKPIT_IMAGE_TAG:-cockpit-' in deploy_script
    assert 'ALPHADB_API_IMAGE_TAG="${ALPHADB_API_IMAGE_TAG:-api-' in deploy_script
    assert "-f apps/dashboard/Dockerfile" in deploy_script
    assert "apps/dashboard" in deploy_script
    assert 'CockpitContainerImage="$COCKPIT_IMAGE_URI"' in deploy_script
    assert 'AlphaDbApiContainerImage="$ALPHADB_API_IMAGE_URI"' in deploy_script
    assert "require_env DATABASE_URL_SECRET_ARN" in deploy_script
    assert "require_env COCKPIT_PIN_SECRET_ARN" in deploy_script
    assert "require_env COCKPIT_COOKIE_SECRET_ARN" in deploy_script
    assert "DATABASE_URL=" not in deploy_script
    assert "run_api_command alphadb-deploy migrate" in deploy_script
    assert "run_api_command alphadb-deploy seed-readiness --series KXBTC15M" in deploy_script
    assert "run_api_command alphadb-deploy smoke" in deploy_script
    assert "deploy/aws/smoke-cockpit-stack.sh" in deploy_script
    assert "DRY_RUN" in deploy_script

    assert "secretsmanager get-secret-value" in smoke_script
    assert "$COCKPIT_URL/api/alphadb/health" in smoke_script
    assert 'STATUS" != "401"' in smoke_script
    assert "$COCKPIT_URL/api/auth/login" in smoke_script
    assert '--data-urlencode "pin=$PIN"' in smoke_script
    assert 'components.get("postgres") != "ok"' in smoke_script

    assert "auth-disabled Cockpit opens" in local_auth_smoke
    assert "wrong PIN is rejected" in local_auth_smoke
    assert "correct PIN sets signed cookie" in local_auth_smoke
    assert "signed cookie opens Cockpit" in local_auth_smoke


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
    assert "MinContractPrice" in template
    assert "--min-contract-price" in template
    assert 'MinContractPrice="${MIN_CONTRACT_PRICE:-0.25}"' in deploy_script
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
                    "min_contract_price": 0.25,
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
