"""Deployment-oriented checks and one-off commands for the dashboard runtime."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from alphadb.config import Settings, settings_from_env
from alphadb.dashboard.auth import DashboardAuthConfig
from alphadb.health import HealthReport, collect_health
from alphadb.live_runtime import LiveRuntimeConfigRepository
from alphadb.markets.registry import default_market_registry
from alphadb.runtime import RuntimeGuardError, evaluate_runtime_guard
from alphadb.state.repository import OperationalStateRepository


AWS_LIKE_ENVIRONMENTS = {"aws", "prod", "production"}


@dataclass(frozen=True)
class MigrationStatus:
    ok: bool
    applied: list[str]
    pending: list[str]
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "applied": self.applied,
            "pending": self.pending,
            "detail": self.detail,
        }


def dashboard_auth_required(settings: Settings) -> bool:
    return settings.environment.lower() in AWS_LIKE_ENVIRONMENTS


def database_location(database_url: str) -> str:
    parsed = urlsplit(database_url)
    if not parsed.hostname:
        return "configured"
    database = parsed.path.lstrip("/") or "unknown"
    if parsed.port:
        return f"{parsed.hostname}:{parsed.port}/{database}"
    return f"{parsed.hostname}/{database}"


def settings_summary(settings: Settings) -> dict[str, Any]:
    return {
        "environment": settings.environment,
        "aws_region": settings.aws_region,
        "database": database_location(settings.database_url),
        "dashboard_port": settings.dashboard_port,
        "runtime_mode": settings.runtime_mode,
        "live_orders_explicitly_enabled": settings.enable_live_orders,
        "human_cutover_approved": settings.human_cutover_approved,
        "dashboard_auth_configured": settings.dashboard_auth_configured,
        "live_stake_cap_dollars": settings.live_stake_cap_dollars,
        "max_ticker_exposure_dollars": settings.max_ticker_exposure_dollars,
        "max_daily_loss_dollars": settings.max_daily_loss_dollars,
    }


def health_report_dict(report: HealthReport) -> dict[str, Any]:
    return {
        "ok": report.ok,
        "service": report.service,
        "environment": report.environment,
        "generated_at_utc": report.generated_at_utc.isoformat(),
        "components": report.as_rows(),
    }


def collect_migration_status(repository: OperationalStateRepository) -> MigrationStatus:
    try:
        applied = repository.applied_migrations()
        pending = repository.pending_migrations()
    except Exception as exc:
        return MigrationStatus(
            ok=False,
            applied=[],
            pending=[],
            detail=f"migration status unavailable: {exc}",
        )
    return MigrationStatus(
        ok=not pending,
        applied=applied,
        pending=pending,
        detail="all migrations applied" if not pending else "pending migrations",
    )


def dashboard_auth_status(
    settings: Settings,
    *,
    require_dashboard_auth: bool | None = None,
) -> dict[str, Any]:
    required = dashboard_auth_required(settings) if require_dashboard_auth is None else require_dashboard_auth
    try:
        config = DashboardAuthConfig.from_settings(settings).validate()
    except Exception as exc:
        return {
            "ok": False,
            "enabled": False,
            "required": required,
            "detail": f"dashboard auth configuration invalid: {exc}",
        }
    enabled = config.enabled
    ok = enabled or not required
    detail = "signed PIN cookie enabled" if enabled else "disabled outside AWS-like environment"
    if required and not enabled:
        detail = "dashboard auth is required for AWS-like environments"
    return {
        "ok": ok,
        "enabled": enabled,
        "required": required,
        "cookie_name": config.cookie_name,
        "ttl_seconds": config.cookie_ttl_seconds,
        "detail": detail,
    }


def runtime_guard_status(
    settings: Settings,
    *,
    allow_live_orders: bool = False,
) -> dict[str, Any]:
    try:
        guard = evaluate_runtime_guard(settings)
    except RuntimeGuardError as exc:
        return {
            "ok": False,
            "detail": str(exc),
        }
    guard_payload = guard.as_dict()
    ok = allow_live_orders or not guard.can_submit_live_orders
    detail = (
        "live orders blocked by runtime guard"
        if not guard.can_submit_live_orders
        else "live orders can be submitted"
    )
    if guard.can_submit_live_orders and not allow_live_orders:
        detail = "live orders can be submitted; pass --allow-live-orders only during cutover"
    return {
        "ok": ok,
        "detail": detail,
        **guard_payload,
    }


def runtime_config_status(settings: Settings) -> dict[str, Any]:
    try:
        revision = LiveRuntimeConfigRepository(settings.database_url).seed_defaults()
    except Exception as exc:
        return {
            "ok": False,
            "detail": f"runtime config unavailable: {exc}",
        }
    return {
        "ok": True,
        "detail": "active dashboard-owned live runtime config is readable",
        "config_id": revision.config_id,
        "version": revision.version,
        "strategy": revision.strategy,
        "snapshot": revision.config.as_dict(),
    }


MigrationStatusProvider = Callable[[OperationalStateRepository], MigrationStatus]
HealthCollector = Callable[[Settings], HealthReport]
RuntimeConfigStatusProvider = Callable[[Settings], dict[str, Any]]


def build_smoke_report(
    settings: Settings,
    *,
    health_collector: HealthCollector = collect_health,
    migration_status_provider: MigrationStatusProvider = collect_migration_status,
    runtime_config_status_provider: RuntimeConfigStatusProvider = runtime_config_status,
    allow_pending_migrations: bool = False,
    require_dashboard_auth: bool | None = None,
    allow_live_orders: bool = False,
) -> dict[str, Any]:
    health = health_collector(settings)
    repository = OperationalStateRepository(settings.database_url)
    migrations = migration_status_provider(repository)
    auth = dashboard_auth_status(settings, require_dashboard_auth=require_dashboard_auth)
    runtime = runtime_guard_status(settings, allow_live_orders=allow_live_orders)
    runtime_config = runtime_config_status_provider(settings)
    migrations_ok = migrations.ok or (allow_pending_migrations and bool(migrations.pending))
    ok = health.ok and migrations_ok and auth["ok"] and runtime["ok"] and runtime_config["ok"]
    return {
        "ok": ok,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "settings": settings_summary(settings),
        "health": health_report_dict(health),
        "migrations": {
            **migrations.as_dict(),
            "ok": migrations_ok,
            "allow_pending": allow_pending_migrations,
        },
        "dashboard_auth": auth,
        "runtime_guard": runtime,
        "runtime_config": runtime_config,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-deploy")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("migrate", help="Apply operational-state migrations")

    smoke = subparsers.add_parser("smoke", help="Run deployment smoke checks and emit JSON")
    smoke.add_argument(
        "--allow-pending-migrations",
        action="store_true",
        help="Do not fail when migrations are pending",
    )
    smoke.add_argument(
        "--require-dashboard-auth",
        action="store_true",
        help="Require dashboard PIN auth even outside AWS-like environments",
    )
    smoke.add_argument(
        "--allow-live-orders",
        action="store_true",
        help="Do not fail when runtime guard permits live order submission",
    )

    seed = subparsers.add_parser(
        "seed-readiness",
        help="Apply migrations and create a tracer run for dashboard readiness checks",
    )
    seed.add_argument("--series", default="KXBTC15M")
    seed.add_argument(
        "--skip-migrate",
        action="store_true",
        help="Create the tracer run without applying migrations first",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    repository = OperationalStateRepository(settings.database_url)

    if args.command == "migrate":
        applied = repository.apply_migrations()
        pending = repository.pending_migrations()
        print(
            json.dumps(
                {
                    "ok": not pending,
                    "applied_migrations": applied,
                    "pending_migrations": pending,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if not pending else 1

    if args.command == "smoke":
        report = build_smoke_report(
            settings,
            allow_pending_migrations=args.allow_pending_migrations,
            require_dashboard_auth=True if args.require_dashboard_auth else None,
            allow_live_orders=args.allow_live_orders,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1

    if args.command == "seed-readiness":
        if not args.skip_migrate:
            repository.apply_migrations()
        spec = default_market_registry().get(args.series)
        tracer = repository.create_tracer_run(spec)
        print(
            json.dumps(
                {
                    "ok": True,
                    "tracer": tracer.as_dict(),
                    "summary": repository.get_run_summary(tracer.run_id),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
