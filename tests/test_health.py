from datetime import UTC

from alphadb.config import Settings
from alphadb.health import ComponentHealth, HealthStatus, collect_health, render_text


def ok_package() -> ComponentHealth:
    return ComponentHealth(
        name="package",
        status=HealthStatus.OK,
        detail="alphadb test",
    )


def test_collect_health_reports_ok_when_components_are_ok() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql://alphadb:alphadb@localhost:55433/alphadb",
        streamlit_port="8501",
    )

    report = collect_health(
        settings=settings,
        database_check=lambda _: ComponentHealth(
            name="postgres",
            status=HealthStatus.OK,
            detail="connection ok",
        ),
        package_check=ok_package,
    )

    assert report.ok is True
    assert report.service == "alphadb"
    assert report.environment == "test"
    assert report.generated_at_utc.tzinfo == UTC
    assert {component.name for component in report.components} == {"package", "postgres"}


def test_collect_health_reports_error_when_database_is_unavailable() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql://alphadb:alphadb@localhost:55433/alphadb",
        streamlit_port="8501",
    )

    report = collect_health(
        settings=settings,
        database_check=lambda _: ComponentHealth(
            name="postgres",
            status=HealthStatus.ERROR,
            detail="connection failed",
        ),
        package_check=ok_package,
    )

    assert report.ok is False
    assert "postgres: error - connection failed" in render_text(report)
