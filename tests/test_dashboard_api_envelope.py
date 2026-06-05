from __future__ import annotations

from alphadb.config import settings_from_env
from alphadb.dashboard.app import DashboardService


def test_dashboard_capabilities_expose_agent_terminal_skills() -> None:
    service = DashboardService(
        settings=settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"})
    )

    payload = service.capabilities()

    names = {skill["name"] for skill in payload["skills"]}
    assert "capabilities.list" in names
    assert "live.summary" in names
    assert "strategy.compile" in names
    assert "data.view.query" in names
    assert "lab.insights.generate" in names
