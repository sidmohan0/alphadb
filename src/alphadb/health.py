"""Health checks for the AlphaDB target-platform dev environment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from typing import Callable, Sequence

import psycopg

from alphadb.config import Settings, settings_from_env


class HealthStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


@dataclass(frozen=True)
class ComponentHealth:
    name: str
    status: HealthStatus
    detail: str

    @property
    def ok(self) -> bool:
        return self.status == HealthStatus.OK


@dataclass(frozen=True)
class HealthReport:
    service: str
    environment: str
    generated_at_utc: datetime
    components: tuple[ComponentHealth, ...]

    @property
    def ok(self) -> bool:
        return all(component.ok for component in self.components)

    def as_rows(self) -> list[dict[str, str]]:
        return [
            {
                "component": component.name,
                "status": component.status.value,
                "detail": component.detail,
            }
            for component in self.components
        ]


DatabaseCheck = Callable[[str], ComponentHealth]
PackageCheck = Callable[[], ComponentHealth]


def check_package() -> ComponentHealth:
    try:
        package_version = version("alphadb")
    except PackageNotFoundError:
        return ComponentHealth(
            name="package",
            status=HealthStatus.ERROR,
            detail="alphadb package is not installed",
        )
    return ComponentHealth(
        name="package",
        status=HealthStatus.OK,
        detail=f"alphadb {package_version}",
    )


def check_database(database_url: str) -> ComponentHealth:
    try:
        with psycopg.connect(database_url, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except Exception as exc:  # pragma: no cover - concrete exception varies by driver/platform.
        return ComponentHealth(
            name="postgres",
            status=HealthStatus.ERROR,
            detail=f"connection failed: {exc}",
        )
    return ComponentHealth(
        name="postgres",
        status=HealthStatus.OK,
        detail="connection ok",
    )


def collect_health(
    settings: Settings | None = None,
    database_check: DatabaseCheck = check_database,
    package_check: PackageCheck = check_package,
    extra_components: Sequence[ComponentHealth] = (),
) -> HealthReport:
    resolved_settings = settings or settings_from_env()
    components = (
        package_check(),
        database_check(resolved_settings.database_url),
        *extra_components,
    )
    return HealthReport(
        service="alphadb",
        environment=resolved_settings.environment,
        generated_at_utc=datetime.now(UTC),
        components=components,
    )


def render_text(report: HealthReport) -> str:
    lines = [
        f"service: {report.service}",
        f"environment: {report.environment}",
        f"status: {'ok' if report.ok else 'error'}",
        f"generated_at_utc: {report.generated_at_utc.isoformat()}",
    ]
    for component in report.components:
        lines.append(f"{component.name}: {component.status.value} - {component.detail}")
    return "\n".join(lines)


def main() -> int:
    report = collect_health()
    print(render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
