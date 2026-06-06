from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from alphadb.config import settings_from_env
from alphadb.dashboard.app import DashboardService
from alphadb.performance import build_performance_summary


NOW = datetime(2026, 6, 6, 18, 30, tzinfo=UTC)


def test_performance_summary_reports_truthful_empty_state() -> None:
    summary = build_performance_summary(
        strategy="fair_value_live",
        market_series="KXBTC15M",
        generated_at=NOW,
    )

    assert summary["data_status"] == "empty"
    assert summary["config"]["status"] == "missing"
    assert summary["execution"]["data_status"] == "empty"
    assert summary["execution"]["counts"] == {
        "submitted": 0,
        "skipped": 0,
        "rejected": 0,
        "filled": 0,
        "no_fill": 0,
        "unknown": 0,
    }
    assert summary["pnl"]["status"] == "unavailable"
    assert summary["pnl"]["net_pnl_dollars"] is None
    assert summary["freshness"]["status"] == "empty"


def test_performance_summary_counts_execution_outcomes_and_skip_reasons() -> None:
    summary = build_performance_summary(
        strategy="fair_value_live",
        market_series="KXBTC15M",
        generated_at=NOW,
        config_row=config_row(version=4),
        status_rows=[
            status_row(
                "run_unknown",
                NOW,
                decision_outcome="submitted",
                latest_attempt_status="submitted",
                fill_status="submitted_fill_unknown",
            ),
            status_row(
                "run_skip",
                NOW - timedelta(minutes=1),
                decision_outcome="skipped",
                latest_attempt_status="skipped",
                skip_reason="daily_loss_cap_reached",
                latest_attempt_reason="daily_loss_cap_reached",
            ),
            status_row(
                "run_filled",
                NOW - timedelta(minutes=2),
                decision_outcome="submitted",
                latest_attempt_status="submitted",
                fill_status="filled",
            ),
            status_row(
                "run_no_fill",
                NOW - timedelta(minutes=3),
                decision_outcome="submitted",
                latest_attempt_status="submitted",
                fill_status="no_fill",
            ),
            status_row(
                "run_rejected",
                NOW - timedelta(minutes=4),
                decision_outcome="rejected",
                latest_attempt_status="rejected",
                latest_attempt_reason="guard_denied",
            ),
        ],
    )

    assert summary["data_status"] == "partial"
    assert summary["config"]["version"] == 4
    assert summary["execution"]["counts"] == {
        "submitted": 3,
        "skipped": 1,
        "rejected": 1,
        "filled": 1,
        "no_fill": 1,
        "unknown": 1,
    }
    assert summary["execution"]["skip_reasons"] == [
        {"reason": "daily_loss_cap_reached", "count": 1}
    ]
    assert summary["recent_runs"][0]["run_id"] == "run_unknown"


def test_performance_summary_reports_pnl_fees_exposure_and_risk_budget() -> None:
    summary = build_performance_summary(
        strategy="fair_value_live",
        market_series="KXBTC15M",
        generated_at=NOW,
        config_row=config_row(version=7),
        status_rows=[
            status_row(
                "run_filled",
                NOW,
                decision_outcome="submitted",
                latest_attempt_status="submitted",
                fill_status="filled",
                daily_loss_used_dollars=1.25,
                daily_loss_limit_dollars=50.0,
                market_exposure_used_dollars=0.9,
                market_exposure_limit_dollars=5.0,
            )
        ],
        order_rows=[
            paper_order_row(
                status="filled",
                filled_quantity=2,
                open_quantity=0,
                realized_pnl_dollars=1.0,
                unrealized_pnl_dollars=0.25,
            )
        ],
        fill_rows=[
            {
                "quantity": 2,
                "fee_dollars": 0.05,
                "filled_at": NOW - timedelta(seconds=5),
            }
        ],
        position_rows=[
            {
                "quantity": 2,
                "avg_price": 0.45,
                "realized_pnl_dollars": 1.0,
                "unrealized_pnl_dollars": 0.25,
                "updated_at": NOW - timedelta(seconds=4),
            }
        ],
    )

    assert summary["data_status"] == "ok"
    assert summary["pnl"]["status"] == "ok"
    assert summary["pnl"]["settlement_state"] == "complete"
    assert summary["pnl"]["net_pnl_dollars"] == 1.2
    assert summary["pnl"]["fees_dollars"] == 0.05
    assert summary["pnl"]["unsettled_exposure_dollars"] == 0.9
    assert summary["risk_budget"]["daily_loss_usage_fraction"] == 0.025
    assert summary["risk_budget"]["market_exposure_usage_fraction"] == 0.18


def test_performance_summary_distinguishes_no_fill_from_missing_pnl() -> None:
    summary = build_performance_summary(
        strategy="fair_value_live",
        market_series="KXBTC15M",
        generated_at=NOW,
        status_rows=[
            status_row(
                "run_no_fill",
                NOW,
                decision_outcome="submitted",
                latest_attempt_status="submitted",
                fill_status="no_fill",
            )
        ],
        order_rows=[
            paper_order_row(
                status="unfilled",
                filled_quantity=0,
                open_quantity=1,
                realized_pnl_dollars=0.0,
                unrealized_pnl_dollars=0.0,
            )
        ],
    )

    assert summary["pnl"]["status"] == "ok"
    assert summary["pnl"]["settlement_state"] == "complete"
    assert summary["pnl"]["fees_status"] == "not_applicable"
    assert summary["pnl"]["net_pnl_dollars"] == 0.0
    assert summary["pnl"]["unsettled_exposure_dollars"] == 0.0


def test_performance_summary_marks_partial_when_fees_or_settlement_are_unavailable() -> None:
    summary = build_performance_summary(
        strategy="fair_value_live",
        market_series="KXBTC15M",
        generated_at=NOW,
        status_rows=[
            status_row(
                "run_partial",
                NOW,
                decision_outcome="submitted",
                latest_attempt_status="submitted",
                fill_status="filled",
            )
        ],
        order_rows=[
            paper_order_row(
                status="partial",
                filled_quantity=1,
                open_quantity=1,
                realized_pnl_dollars=0.2,
                unrealized_pnl_dollars=0.1,
            )
        ],
    )

    assert summary["data_status"] == "partial"
    assert summary["pnl"]["status"] == "partial"
    assert summary["pnl"]["settlement_state"] == "partial"
    assert summary["pnl"]["fees_status"] == "unavailable"
    assert summary["pnl"]["net_pnl_dollars"] is None
    assert summary["pnl"]["unsettled_exposure_dollars"] == 0.45


def test_dashboard_service_exposes_performance_payload() -> None:
    payload = build_performance_summary(
        strategy="fair_value_live",
        market_series="KXBTC15M",
        generated_at=NOW,
    )
    repository = FakePerformanceRepository(payload)
    service = DashboardService(
        settings=settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"}),
        performance_repository_factory=lambda database_url: repository,
    )

    result = service.performance_payload()

    assert result["schema_version"] == "alphadb_performance_summary.v1"
    assert result["strategy"] == "fair_value_live"
    assert repository.calls == ["fair_value_live"]


@dataclass
class FakePerformanceRepository:
    payload: dict[str, Any]
    calls: list[str] | None = None

    def __post_init__(self) -> None:
        if self.calls is None:
            self.calls = []

    def summary(self, *, strategy: str) -> dict[str, Any]:
        assert self.calls is not None
        self.calls.append(strategy)
        return dict(self.payload)


def config_row(*, version: int) -> dict[str, Any]:
    return {
        "config_id": f"cfg_{version}",
        "strategy": "fair_value_live",
        "version": version,
        "is_active": True,
        "max_order_dollars": 5.0,
        "max_market_exposure_dollars": 5.0,
        "max_daily_loss_dollars": 50.0,
        "min_edge": 0.0,
        "min_contract_price": 0.25,
        "max_markets": 20,
        "created_at": NOW - timedelta(minutes=10),
    }


def status_row(
    run_id: str,
    generated_at: datetime,
    *,
    decision_outcome: str,
    latest_attempt_status: str,
    fill_status: str | None = None,
    skip_reason: str | None = None,
    latest_attempt_reason: str | None = None,
    daily_loss_used_dollars: float = 0.0,
    daily_loss_limit_dollars: float = 50.0,
    market_exposure_used_dollars: float = 0.0,
    market_exposure_limit_dollars: float = 5.0,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "generated_at": generated_at,
        "config_version": 1,
        "current_market_ticker": "KXBTC15M-TEST",
        "decision_outcome": decision_outcome,
        "selected_side": "yes" if latest_attempt_status == "submitted" else None,
        "skip_reason": skip_reason,
        "latest_attempt_status": latest_attempt_status,
        "latest_attempt_reason": latest_attempt_reason,
        "fill_status": fill_status,
        "daily_loss_used_dollars": daily_loss_used_dollars,
        "daily_loss_limit_dollars": daily_loss_limit_dollars,
        "market_exposure_used_dollars": market_exposure_used_dollars,
        "market_exposure_limit_dollars": market_exposure_limit_dollars,
        "recent_attempt_count": 0,
        "recent_submitted_count": 0,
        "recent_skipped_count": 0,
        "recent_no_fill_count": 0,
        "recent_filled_count": 0,
    }


def paper_order_row(
    *,
    status: str,
    filled_quantity: int,
    open_quantity: int,
    realized_pnl_dollars: float,
    unrealized_pnl_dollars: float,
) -> dict[str, Any]:
    return {
        "paper_order_id": f"order_{status}",
        "market_ticker": "KXBTC15M-TEST",
        "status": status,
        "limit_price": 0.45,
        "quantity": filled_quantity + open_quantity,
        "filled_quantity": filled_quantity,
        "submitted_at": NOW - timedelta(seconds=10),
        "reconciliation_status": status,
        "reconciliation_expected_quantity": filled_quantity + open_quantity,
        "reconciliation_filled_quantity": filled_quantity,
        "reconciliation_open_quantity": open_quantity,
        "reconciliation_realized_pnl_dollars": realized_pnl_dollars,
        "reconciliation_unrealized_pnl_dollars": unrealized_pnl_dollars,
        "reconciliation_created_at": NOW - timedelta(seconds=9),
    }
