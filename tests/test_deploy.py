from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
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
    assert "KalshiApiKeyIdSecretArn" in template
    assert "KalshiPrivateKeyPemSecretArn" in template
    assert '${KalshiApiKeyIdSecretArn}-*' in template
    assert '${KalshiPrivateKeyPemSecretArn}-*' in template
    assert "AWS::ServiceDiscovery::PrivateDnsNamespace" in template
    assert "AWS::ServiceDiscovery::Service" in template
    assert "Name: ALPHADB_API_BASE_URL" in cockpit_task
    assert "http://alphadb-api.${PrivateNamespaceName}:${AlphaDbApiPort}" in cockpit_task
    assert "Name: ALPHADB_COCKPIT_PIN" in cockpit_task
    assert "Name: ALPHADB_COCKPIT_COOKIE_SECRET" in cockpit_task
    assert "DATABASE_URL" not in cockpit_task
    assert "Name: DATABASE_URL" in api_task
    assert "Name: ALPHADB_DASHBOARD_PIN" in api_task
    assert "Name: KALSHI_API_KEY_ID" in api_task
    assert "Name: KALSHI_PRIVATE_KEY_PEM" in api_task
    assert "Command:" in api_task
    assert "/tmp/alphadb-kalshi-private-key.pem" in api_task
    assert "KALSHI_PRIVATE_KEY_PATH" in api_task
    assert 'os.environ["KALSHI_PRIVATE_KEY_PEM"].replace("\\\\n", "\\n")' in api_task
    assert "path.chmod(0o600)" in api_task
    assert "exec alphadb-dashboard" in api_task
    assert "echo ${KALSHI_PRIVATE_KEY_PEM" not in api_task
    assert "echo $KALSHI_PRIVATE_KEY_PEM" not in api_task
    assert "Name: KALSHI_API_KEY_ID" not in cockpit_task
    assert "Name: KALSHI_PRIVATE_KEY_PEM" not in cockpit_task
    assert "LoadBalancers:" not in api_service
    assert "ServiceRegistries:" in api_service
    assert "LoadBalancers:" in cockpit_service
    assert "SourceSecurityGroupId: !Ref CockpitServiceSecurityGroup" in template
    assert "AWS::Events::Rule" not in template
    assert "HealthCheckIntervalSeconds: 5" in template
    assert "HealthyThresholdCount: 2" in template
    assert "HealthCheckTimeoutSeconds: 3" in template
    assert "deregistration_delay.timeout_seconds" in template
    assert "HealthCheckGracePeriodSeconds: 60" in cockpit_service
    assert "- AlphaDbApiService" not in cockpit_service


def test_cockpit_deploy_script_builds_two_images_and_runs_smoke_without_raw_secrets() -> None:
    deploy_script = Path("deploy/aws/deploy-cockpit-stack.sh").read_text(encoding="utf-8")
    smoke_script = Path("deploy/aws/smoke-cockpit-stack.sh").read_text(encoding="utf-8")
    local_auth_smoke = Path("apps/dashboard/scripts/smoke-auth.sh").read_text(encoding="utf-8")

    assert 'COCKPIT_IMAGE_TAG="${COCKPIT_IMAGE_TAG:-cockpit-$COCKPIT_CONTEXT_HASH}"' in deploy_script
    assert (
        'ALPHADB_API_IMAGE_TAG="${ALPHADB_API_IMAGE_TAG:-runtime-$RUNTIME_CONTEXT_HASH}"'
        in deploy_script
    )
    assert "context_hash" in deploy_script
    assert "ecr reuse:" in deploy_script
    assert 'SKIP_RELEASE_CHECK="${SKIP_RELEASE_CHECK:-$SKIP_MIGRATE}"' in deploy_script
    assert "-f apps/dashboard/Dockerfile" in deploy_script
    assert "apps/dashboard" in deploy_script
    assert 'CockpitContainerImage="$COCKPIT_IMAGE_URI"' in deploy_script
    assert 'AlphaDbApiContainerImage="$ALPHADB_API_IMAGE_URI"' in deploy_script
    assert "require_env DATABASE_URL_SECRET_ARN" in deploy_script
    assert "require_env COCKPIT_PIN_SECRET_ARN" in deploy_script
    assert "require_env COCKPIT_COOKIE_SECRET_ARN" in deploy_script
    assert "require_env KALSHI_API_KEY_ID_SECRET_ARN" in deploy_script
    assert "require_env KALSHI_PRIVATE_KEY_PEM_SECRET_ARN" in deploy_script
    assert 'KalshiApiKeyIdSecretArn="$KALSHI_API_KEY_ID_SECRET_ARN"' in deploy_script
    assert (
        'KalshiPrivateKeyPemSecretArn="$KALSHI_PRIVATE_KEY_PEM_SECRET_ARN"'
        in deploy_script
    )
    assert "DATABASE_URL=" not in deploy_script
    assert "run_api_command alphadb-deploy release-check --series KXBTC15M" in deploy_script
    assert "run_api_command alphadb-deploy migrate" not in deploy_script
    assert "run_api_command alphadb-deploy seed-readiness --series KXBTC15M" not in deploy_script
    assert "run_api_command alphadb-deploy smoke" not in deploy_script
    assert "deploy/aws/smoke-cockpit-stack.sh" in deploy_script
    assert "DRY_RUN" in deploy_script

    assert "secretsmanager get-secret-value" in smoke_script
    assert "$COCKPIT_URL/api/alphadb/health" in smoke_script
    assert 'STATUS" != "401"' in smoke_script
    assert "$COCKPIT_URL/api/auth/login" in smoke_script
    assert '--data-urlencode "pin=$PIN"' in smoke_script
    assert 'components.get("postgres") != "ok"' in smoke_script
    assert "$COCKPIT_URL/api/alphadb/live" in smoke_script
    assert "validate-cockpit-portfolio-smoke.py" in smoke_script
    assert "portfolio_balance_dollars" not in smoke_script
    assert "cash_dollars" not in smoke_script
    assert "assets_dollars" not in smoke_script

    assert "auth-disabled Cockpit opens" in local_auth_smoke
    assert "wrong PIN is rejected" in local_auth_smoke
    assert "correct PIN sets signed cookie" in local_auth_smoke
    assert "signed cookie opens Cockpit" in local_auth_smoke


def test_cockpit_portfolio_smoke_validator_reports_status_without_balances(
    tmp_path: Path,
) -> None:
    payload = {
        "portfolio_balance": {
            "status": "ok",
            "source": "kalshi",
            "portfolio_balance_dollars": 191.34,
            "cash_dollars": 67.89,
            "assets_dollars": 123.45,
            "observed_at_utc": "2026-06-06T22:00:00+00:00",
            "stale": False,
            "detail": None,
        }
    }

    result = run_cockpit_portfolio_validator(tmp_path, payload)

    assert result.returncode == 0
    assert "portfolio credentials accepted" in result.stdout
    assert "191.34" not in result.stdout
    assert "67.89" not in result.stdout
    assert "123.45" not in result.stdout
    assert "portfolio_balance_dollars" not in result.stdout


def test_cockpit_portfolio_smoke_validator_allows_noncredential_unavailable_reason(
    tmp_path: Path,
) -> None:
    payload = {
        "ok": True,
        "data": {
            "portfolio_balance": {
                "status": "unavailable",
                "source": "kalshi",
                "portfolio_balance_dollars": None,
                "cash_dollars": None,
                "assets_dollars": None,
                "observed_at_utc": None,
                "stale": True,
                "detail": "exchange API timeout",
            }
        },
    }

    result = run_cockpit_portfolio_validator(tmp_path, payload)

    assert result.returncode == 0
    assert "exchange API timeout" in result.stdout


def test_cockpit_portfolio_smoke_validator_rejects_missing_credentials(
    tmp_path: Path,
) -> None:
    payload = {
        "portfolio_balance": {
            "status": "unavailable",
            "source": "kalshi",
            "portfolio_balance_dollars": None,
            "cash_dollars": None,
            "assets_dollars": None,
            "observed_at_utc": None,
            "stale": True,
            "detail": "missing_kalshi_credentials",
        }
    }

    result = run_cockpit_portfolio_validator(tmp_path, payload)

    assert result.returncode == 1
    assert "missing_kalshi_credentials" in result.stderr


def test_cockpit_portfolio_smoke_validator_rejects_unavailable_ui_text(
    tmp_path: Path,
) -> None:
    payload = {
        "portfolio_balance": {
            "status": "unavailable",
            "source": "kalshi",
            "portfolio_balance_dollars": None,
            "cash_dollars": None,
            "assets_dollars": None,
            "observed_at_utc": None,
            "stale": True,
            "detail": "Kalshi credentials unavailable",
        }
    }

    result = run_cockpit_portfolio_validator(tmp_path, payload)

    assert result.returncode == 1
    assert "Kalshi credentials unavailable" in result.stderr


def run_cockpit_portfolio_validator(
    tmp_path: Path,
    payload: dict[str, object],
) -> subprocess.CompletedProcess[str]:
    body = tmp_path / "portfolio.json"
    body.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            "scripts/validate-cockpit-portfolio-smoke.py",
            str(body),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


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
    assert "LiveAuthorityBackend" not in template
    assert "--live-authority-backend" in template
    assert 'LIVE_AUTHORITY_BACKEND_VALUE="${LIVE_AUTHORITY_BACKEND:-postgres}"' in deploy_script
    assert "S3 live-run lock authority has been retired" in deploy_script
    assert "      - s3\n" not in template
    assert "--quote-stale-seconds" in template
    assert "--coinbase-feature-stale-seconds" in template
    assert "--brti-future-tolerance-seconds" in template
    assert "--live-risk-state-stale-seconds" in template
    assert "MinContractPrice" in template
    assert "--min-contract-price" in template
    assert 'MinContractPrice="${MIN_CONTRACT_PRICE:-0.25}"' in deploy_script
    assert "FAIR_VALUE_LIVE_SMOKE_EVIDENCE" in deploy_script
    assert "validate-fair-value-live-smoke.py" in deploy_script
    assert "PRESERVE_ENABLED_SCHEDULE" in deploy_script
    assert "describe-rule" in deploy_script
    assert "MaxOrderDollars" not in template
    assert "MaxTickerExposureDollars" not in template
    assert "--max-ticker-exposure-dollars" not in template
    assert "ALPHADB_MAX_TICKER_EXPOSURE_DOLLARS" not in template
    assert "MaxDailyLossDollars" not in template
    assert "KALSHI_API_KEY_ID" in template
    assert "KALSHI_PRIVATE_KEY_PEM" in template
    assert "s3:GetObject" in template
    assert "s3:PutObject" in template
    assert "s3:DeleteObject" not in template


def test_fair_value_live_smoke_validator_requires_runtime_gate_evidence(tmp_path: Path) -> None:
    script = Path("scripts/validate-fair-value-live-smoke.py")
    passing_payload = {
        "p95_runtime_seconds": 44.9,
        "overlapping_task_count": 0,
        "stale_task_count": 0,
        "executable_quote": {
            "source": "kalshi_orderbook",
            "max_quote_age_seconds": 15,
        },
        "runtime_guard": {
            "credentials_present": True,
            "can_submit_live_orders": True,
        },
        "live_risk_admission_state": {
            "status": "active",
            "reason": None,
        },
        "runtime_controls": {
            "min_contract_price": 0.25,
            "min_edge": 0,
        },
        "task_definition_one_cycle": True,
        "live_order_guards_preserved": True,
        "schedule_state_before": "DISABLED",
    }
    passing = write_smoke_payload(tmp_path, "passing", passing_payload)

    ok = subprocess.run(
        [sys.executable, str(script), str(passing)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert ok.returncode == 0

    cases = {
        "p95_runtime": (
            lambda payload: payload.update({"p95_runtime_seconds": 45}),
            "p95_runtime_seconds",
        ),
        "quote_age": (
            lambda payload: payload["executable_quote"].update({"max_quote_age_seconds": 16}),
            "executable quote age",
        ),
        "credentials": (
            lambda payload: payload["runtime_guard"].update({"credentials_present": False}),
            "credentials_present",
        ),
        "live_order_guards": (
            lambda payload: payload.update({"live_order_guards_preserved": False}),
            "live_order_guards_preserved",
        ),
        "risk_state": (
            lambda payload: payload["live_risk_admission_state"].update(
                {"status": "active", "reason": "risk_state_stale"}
            ),
            "live risk admission state must be fresh",
        ),
        "schedule": (
            lambda payload: payload.update({"schedule_state_before": "ENABLED"}),
            "schedule_state_before",
        ),
        "min_contract_price": (
            lambda payload: payload["runtime_controls"].update({"min_contract_price": 0.2}),
            "min_contract_price",
        ),
        "min_edge": (
            lambda payload: payload["runtime_controls"].update({"min_edge": 0.01}),
            "min_edge",
        ),
        "overlap": (
            lambda payload: payload.update({"overlapping_task_count": 1}),
            "overlapping_task_count",
        ),
        "stale_tasks": (
            lambda payload: payload.update({"stale_task_count": 1}),
            "stale_task_count",
        ),
        "one_cycle": (
            lambda payload: payload.update({"task_definition_one_cycle": False}),
            "task_definition_one_cycle",
        ),
    }
    for name, (mutate, expected) in cases.items():
        payload = deepcopy(passing_payload)
        mutate(payload)
        path = write_smoke_payload(tmp_path, name, payload)
        bad = subprocess.run(
            [sys.executable, str(script), str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert bad.returncode == 1
        assert expected in bad.stderr


def test_brti_live_collector_aws_template_runs_separate_restartable_worker() -> None:
    template = Path("deploy/aws/brti-live-collector.yaml").read_text(encoding="utf-8")
    deploy_script = Path("deploy/aws/deploy-brti-live-collector.sh").read_text(
        encoding="utf-8"
    )

    assert "alphadb-brti-live-collector" in template
    assert "AWS::ECS::Service" in template
    assert "DesiredCount" in template
    assert "alphadb-brti" in template
    assert "live-collect" in template
    assert "ALPHADB_ENABLE_LIVE_WS_SMOKE" in template
    assert "ALPHADB_KALSHI_WS_URL" in template
    assert "DATABASE_URL" in template
    assert "KALSHI_API_KEY_ID" in template
    assert "KALSHI_PRIVATE_KEY_PEM" in template
    assert "secretsmanager:GetSecretValue" in template
    assert "/ecs/${ServiceName}" in template
    assert "ALPHADB_ENABLE_LIVE_ORDERS" not in template
    assert "ALPHADB_HUMAN_CUTOVER_APPROVED" not in template
    assert "ecs wait services-stable" in deploy_script


def test_brti_primary_live_smoke_validator_requires_foundation_evidence(
    tmp_path: Path,
) -> None:
    script = Path("scripts/validate-brti-primary-live-smoke.py")
    passing_payload = {
        "collector_service": {
            "desired_count": 1,
            "running_count": 1,
            "log_group": "/ecs/alphadb-brti-live-collector",
            "restart_behavior": "ecs_service_desired_count",
        },
        "collector": {
            "summary": {
                "accepted": 1,
                "raw_events_inserted": 1,
                "latest_context_updates": 1,
            },
            "latest_context": {
                "status": "usable",
                "age_seconds": 1.2,
                "freshness_limit_seconds": 5,
            },
        },
        "database_url_secret_match": True,
        "fair_value_cycle": {
            "task_definition_one_cycle": True,
            "manifest_uri": "s3://alphadb-artifacts/fair-value-live/run/manifest.json",
            "status_evidence_uri": "s3://alphadb-artifacts/fair-value-live/run/status.json",
            "manifest": {
                "config": {"market_context_source": "brti_primary"},
                "runtime_config": {
                    "snapshot": {"market_context_source": "brti_primary"},
                },
                "runtime_controls": {"market_context_source": "brti_primary"},
                "market_context": {
                    "market_context_source": "brti_primary",
                    "external_close_from_brti": True,
                },
                "selected_row": {
                    "market_context_source": "brti_primary",
                    "external_close_source": "brti_latest_context",
                },
            },
        },
        "runtime_guard": {
            "credentials_present": True,
            "can_submit_live_orders": True,
        },
        "live_order_guards_preserved": True,
        "fair_value_schedule_state_before": "DISABLED",
        "fair_value_schedule_state_after": "DISABLED",
        "expensive_yes_schedule_state_before": "ENABLED",
        "expensive_yes_schedule_state_after": "ENABLED",
        "rollback": {
            "market_context_source": "coinbase_primary",
            "command": (
                "alphadb-runtime set-market-context --source coinbase_primary "
                "--created-by rollback-alp-258"
            ),
        },
    }
    passing = write_smoke_payload(tmp_path, "brti_passing", passing_payload)

    ok = subprocess.run(
        [sys.executable, str(script), str(passing)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert ok.returncode == 0

    cases = {
        "collector_insert": (
            lambda payload: payload["collector"]["summary"].update(
                {"raw_events_inserted": 0}
            ),
            "raw_events_inserted",
        ),
        "latest_stale": (
            lambda payload: payload["collector"]["latest_context"].update(
                {"age_seconds": 6}
            ),
            "freshness limit",
        ),
        "market_context": (
            lambda payload: payload["fair_value_cycle"]["manifest"]["config"].update(
                {"market_context_source": "coinbase_primary"}
            ),
            "market_context_source",
        ),
        "external_close": (
            lambda payload: (
                payload["fair_value_cycle"]["manifest"]["market_context"].update(
                    {"external_close_from_brti": False}
                ),
                payload["fair_value_cycle"]["manifest"]["selected_row"].update(
                    {"external_close_source": "coinbase_live"}
                ),
            ),
            "materialize BRTI context",
        ),
        "schedule": (
            lambda payload: payload.update({"fair_value_schedule_state_after": "ENABLED"}),
            "schedule state",
        ),
        "rollback": (
            lambda payload: payload["rollback"].update(
                {"market_context_source": "brti_primary"}
            ),
            "rollback market_context_source",
        ),
    }
    for name, (mutate, expected) in cases.items():
        payload = deepcopy(passing_payload)
        mutate(payload)
        path = write_smoke_payload(tmp_path, f"brti_{name}", payload)
        bad = subprocess.run(
            [sys.executable, str(script), str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert bad.returncode == 1
        assert expected in bad.stderr


def write_smoke_payload(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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

        def get_active_config(self) -> FakeRevision:
            return FakeRevision()

    monkeypatch.setattr("alphadb.deploy.LiveRuntimeConfigRepository", FakeRepository)
    settings = settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"})

    status = runtime_config_status(settings)

    assert status["ok"] is True
    assert status["config_id"] == "cfg_test"
