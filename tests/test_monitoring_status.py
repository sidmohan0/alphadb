from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from alphadb.config import settings_from_env
from alphadb.health import ComponentHealth, HealthReport, HealthStatus
from alphadb.monitoring.status import (
    StrategyProcess,
    collect_monitor_status,
    collect_strategy_status,
    parse_strategy_processes,
)


def ok_health(_) -> HealthReport:
    return HealthReport(
        service="alphadb",
        environment="test",
        generated_at_utc=datetime(2026, 6, 1, 12, tzinfo=UTC),
        components=(
            ComponentHealth("package", HealthStatus.OK, "alphadb test"),
            ComponentHealth("postgres", HealthStatus.OK, "connection ok"),
        ),
    )


class FakeStrategyRepository:
    def __init__(self, database_url: str, *, latest_status: str = "running"):
        self.database_url = database_url
        self.latest_status = latest_status

    def latest_run(self) -> dict[str, Any]:
        return {
            "run_id": "run_live",
            "mode": "gated-live",
            "market_series": "KXBTC15M",
            "status": self.latest_status,
            "started_at": datetime(2026, 6, 1, 11, 45, tzinfo=UTC),
            "metadata": {"runner": "gated-live", "unsafe_secret": "do-not-render"},
            "created_at": datetime(2026, 6, 1, 11, 45, tzinfo=UTC),
        }

    def counts(self, *, run_id: str | None = None) -> dict[str, int]:
        assert run_id == "run_live"
        return {"handled": 2, "skipped": 1, "errored": 0}

    def latest_outcomes(
        self,
        *,
        run_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        assert run_id == "run_live"
        assert limit == 10
        return [
            {
                "run_id": "run_live",
                "market_ticker": "KXBTC15M-TEST",
                "decision_timestamp": datetime(2026, 6, 1, 11, 59, tzinfo=UTC),
                "status": "handled",
                "live_order_request": {"order": "raw"},
            }
        ]


class BrokenStrategyRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def latest_run(self) -> dict[str, Any]:
        raise RuntimeError("database unavailable")


def test_parse_strategy_processes_extracts_alphadb_strategy_processes() -> None:
    processes = parse_strategy_processes(
        """
          1     0 Ssl  /usr/local/bin/python /usr/local/bin/alphadb-dashboard --host 0.0.0.0
        389     1 Ssl  /usr/local/bin/python /usr/local/bin/alphadb-strategy gated-live-loop --max-markets 3
        401   389 S    alphadb-strategy status
        """
    )

    assert [process.pid for process in processes] == [389, 401]


def test_collect_monitor_status_passes_when_live_loop_and_run_status_match() -> None:
    settings = settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"})

    status = collect_monitor_status(
        settings,
        health_collector=ok_health,
        process_lister=lambda: [
            StrategyProcess(
                pid=389,
                ppid=1,
                state="Ssl",
                command="/usr/local/bin/alphadb-strategy gated-live-loop --max-markets 3",
            )
        ],
        repository_factory=FakeStrategyRepository,
    )

    assert status["ok"] is True
    assert status["checks"] == {
        "health": True,
        "strategy_process": True,
        "strategy_latest_run": True,
    }
    assert status["strategy_process"]["count"] == 1
    assert status["strategy"]["latest_run_status"] == "running"
    assert status["strategy"]["latest_run"]["started_at"] == "2026-06-01T11:45:00+00:00"
    assert status["strategy"]["latest_run"]["metadata"] == {"runner": "gated-live"}
    assert status["strategy"]["latest_outcomes"][0]["decision_timestamp"] == (
        "2026-06-01T11:59:00+00:00"
    )
    assert "live_order_request" not in status["strategy"]["latest_outcomes"][0]


def test_collect_monitor_status_fails_when_process_count_does_not_match() -> None:
    settings = settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"})

    status = collect_monitor_status(
        settings,
        health_collector=ok_health,
        process_lister=lambda: [],
        repository_factory=FakeStrategyRepository,
    )

    assert status["ok"] is False
    assert status["checks"]["strategy_process"] is False
    assert status["strategy_process"]["detail"] == "expected 1 matching process(es), found 0"


def test_collect_strategy_status_fails_when_latest_run_status_does_not_match() -> None:
    settings = settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"})

    status = collect_strategy_status(
        settings,
        repository_factory=lambda database_url: FakeStrategyRepository(
            database_url,
            latest_status="completed",
        ),
    )

    assert status["ok"] is False
    assert status["latest_run_status"] == "completed"
    assert status["detail"] == "expected latest run status 'running', found 'completed'"


def test_collect_strategy_status_reports_repository_errors() -> None:
    settings = settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"})

    status = collect_strategy_status(settings, repository_factory=BrokenStrategyRepository)

    assert status["ok"] is False
    assert status["latest_run"] is None
    assert status["detail"] == "strategy status unavailable: database unavailable"
