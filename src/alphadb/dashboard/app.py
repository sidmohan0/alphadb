"""Streamlit entrypoint for the AlphaDB target-platform dashboard."""

from datetime import UTC, datetime

import streamlit as st

from alphadb.collectors.kalshi_rest import CollectorRunStore
from alphadb.config import settings_from_env
from alphadb.decision_engine.engine import DecisionRepository
from alphadb.events.log import RawEventLog
from alphadb.features.ledger import FeatureLedgerRepository
from alphadb.health import collect_health
from alphadb.live_orders import LiveOrderRepository, live_adapter_status_rows
from alphadb.markets.cli import spec_summary_row
from alphadb.markets.registry import default_market_registry
from alphadb.model_registry.registry import ModelRegistryRepository
from alphadb.paper.ioc import PaperExecutionRepository
from alphadb.risk.gate import RiskDecisionRepository
from alphadb.runtime import runtime_status_rows
from alphadb.shadow.comparison import ShadowComparisonRepository
from alphadb.state.repository import OperationalStateRepository
from alphadb.strategy.state import StrategyRunRepository


def operational_state_rows(database_url: str) -> list[dict[str, str | int]]:
    try:
        counts = OperationalStateRepository(database_url).counts().as_dict()
    except Exception as exc:
        return [{"metric": "operational_state", "value": "unavailable", "detail": str(exc)}]
    return [
        {"metric": metric, "value": value, "detail": "postgres"}
        for metric, value in counts.items()
    ]


def raw_event_rows(database_url: str) -> list[dict[str, str | int]]:
    try:
        rows = RawEventLog(database_url).counts_by_source_schema()
    except Exception as exc:
        return [{"source": "raw_events", "schema_version": "unavailable", "events": str(exc)}]
    return rows or [{"source": "raw_events", "schema_version": "none", "events": 0}]


def collector_status_rows(database_url: str) -> list[dict[str, str | int]]:
    try:
        rows = CollectorRunStore(database_url).recent_runs(limit=10)
    except Exception as exc:
        return [{"collector_run_id": "collector_runs", "status": "unavailable", "errors": str(exc)}]
    return rows or [{"collector_run_id": "collector_runs", "status": "none", "errors": 0}]


def model_registry_rows(database_url: str) -> list[dict[str, str | int]]:
    try:
        rows = ModelRegistryRepository(database_url).recent_models(limit=10)
    except Exception as exc:
        return [{"model_id": "model_registry", "promotion_state": "unavailable", "detail": str(exc)}]
    return rows or [{"model_id": "model_registry", "promotion_state": "none", "detail": ""}]


def feature_ledger_rows(database_url: str) -> list[dict[str, str | int]]:
    try:
        rows = FeatureLedgerRepository(database_url).recent_rows(limit=10)
    except Exception as exc:
        return [{"feature_row_id": "feature_rows", "detail": str(exc)}]
    return rows or [{"feature_row_id": "feature_rows", "detail": "none"}]


def decision_rows(database_url: str) -> list[dict[str, str | int]]:
    try:
        rows = DecisionRepository(database_url).list()
    except Exception as exc:
        return [{"decision_id": "decisions", "detail": str(exc)}]
    return rows or [{"decision_id": "decisions", "detail": "none"}]


def risk_rows(database_url: str) -> list[dict[str, str | int]]:
    try:
        rows = RiskDecisionRepository(database_url).list()
    except Exception as exc:
        return [{"risk_decision_id": "risk_decisions", "detail": str(exc)}]
    return rows or [{"risk_decision_id": "risk_decisions", "detail": "none"}]


def paper_status_rows(database_url: str) -> dict[str, list[dict[str, str | int]]]:
    try:
        repository = PaperExecutionRepository(database_url)
        return {
            "orders": repository.list_orders(),
            "fills": repository.list_fills(),
            "positions": repository.list_positions(),
            "reconciliations": repository.list_reconciliations(),
        }
    except Exception as exc:
        row = [{"paper": "unavailable", "detail": str(exc)}]
        return {"orders": row, "fills": row, "positions": row, "reconciliations": row}


def shadow_rows(database_url: str) -> list[dict[str, str | int]]:
    try:
        rows = ShadowComparisonRepository(database_url).recent(limit=10)
    except Exception as exc:
        return [{"comparison_id": "shadow_comparisons", "detail": str(exc)}]
    return rows or [{"comparison_id": "shadow_comparisons", "detail": "none"}]


def strategy_run_rows(database_url: str) -> list[dict[str, str | int]]:
    try:
        repository = StrategyRunRepository(database_url)
        run = repository.latest_run()
        if run is None:
            return [{"metric": "strategy_run", "value": "none", "detail": ""}]
        counts = repository.counts(run_id=run["run_id"])
        rows: list[dict[str, str | int]] = [
            {"metric": "run_id", "value": str(run["run_id"]), "detail": str(run["status"])},
            {"metric": "runtime_mode", "value": str(run["mode"]), "detail": str(run["market_series"])},
            {
                "metric": "uptime_seconds",
                "value": int((datetime.now(UTC) - run["started_at"]).total_seconds()),
                "detail": "wall_clock",
            },
        ]
        latest = repository.latest_outcomes(run_id=run["run_id"], limit=1)
        if latest:
            rows.append(
                {
                    "metric": "current_market_instance",
                    "value": str(latest[0]["market_ticker"]),
                    "detail": str(latest[0]["status"]),
                }
            )
        rows.extend({"metric": key, "value": value, "detail": "latest_counts"} for key, value in counts.items())
        metadata = dict(run["metadata"])
        if metadata.get("model_artifact_sha256"):
            rows.append(
                {
                    "metric": "model_artifact_sha256",
                    "value": str(metadata["model_artifact_sha256"])[:12],
                    "detail": "active_model",
                }
            )
        if metadata.get("feature_schema_sha256"):
            rows.append(
                {
                    "metric": "feature_schema_sha256",
                    "value": str(metadata["feature_schema_sha256"])[:12],
                    "detail": "active_schema",
                }
            )
        spec = default_market_registry().get(str(run["market_series"]))
        rows.extend(
            [
                {
                    "metric": "per_trade_cap_dollars",
                    "value": metadata.get(
                        "live_stake_cap_dollars", spec.risk_config.live_stake_cap_dollars
                    ),
                    "detail": "runtime_config",
                },
                {
                    "metric": "max_daily_loss_dollars",
                    "value": metadata.get(
                        "max_daily_loss_dollars", spec.risk_config.max_daily_loss_dollars
                    ),
                    "detail": "runtime_config",
                },
                {
                    "metric": "min_ev_dollars",
                    "value": metadata.get("min_ev_dollars", spec.trading_cutoffs.min_ev),
                    "detail": "runtime_config",
                },
            ]
        )
        guard = metadata.get("guard", {})
        if isinstance(guard, dict):
            rows.append(
                {
                    "metric": "live_guard",
                    "value": str(guard.get("can_submit_live_orders")),
                    "detail": str(guard.get("denial_reason") or ""),
                }
            )
        return rows
    except Exception as exc:
        return [{"metric": "strategy_run", "value": "unavailable", "detail": str(exc)}]


def latest_strategy_outcome_rows(database_url: str) -> list[dict[str, str | int]]:
    try:
        rows = StrategyRunRepository(database_url).latest_outcomes(limit=10)
    except Exception as exc:
        return [{"outcome_id": "strategy_market_outcomes", "detail": str(exc)}]
    return rows or [{"outcome_id": "strategy_market_outcomes", "detail": "none"}]


def live_order_rows(database_url: str) -> list[dict[str, str | int]]:
    try:
        rows = LiveOrderRepository(database_url).recent(limit=10)
    except Exception as exc:
        return [{"live_order_attempt_id": "live_order_attempts", "detail": str(exc)}]
    return rows or [{"live_order_attempt_id": "live_order_attempts", "detail": "none"}]


def render() -> None:
    settings = settings_from_env()
    report = collect_health(settings=settings)

    st.set_page_config(page_title="AlphaDB", layout="wide")
    st.title("AlphaDB")

    status_label = "OK" if report.ok else "ERROR"
    status_delta = None if report.ok else "attention required"

    left, middle, right = st.columns(3)
    left.metric("Platform", status_label, delta=status_delta)
    middle.metric("Environment", report.environment)
    right.metric("Postgres", "configured", settings.database_url.rsplit("@", maxsplit=1)[-1])

    st.subheader("Health")
    st.dataframe(report.as_rows(), hide_index=True, use_container_width=True)

    st.subheader("Market Specs")
    registry = default_market_registry()
    st.dataframe(
        [spec_summary_row(spec) for spec in registry.list()],
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Operational State")
    st.dataframe(
        operational_state_rows(settings.database_url),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Runtime Guard")
    st.dataframe(runtime_status_rows(settings), hide_index=True, use_container_width=True)

    st.subheader("Strategy Run")
    st.dataframe(strategy_run_rows(settings.database_url), hide_index=True, use_container_width=True)

    st.subheader("Latest Handled Auctions")
    st.dataframe(
        latest_strategy_outcome_rows(settings.database_url),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Raw Events")
    st.dataframe(
        raw_event_rows(settings.database_url),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Collectors")
    st.dataframe(
        collector_status_rows(settings.database_url),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Model Registry")
    st.dataframe(
        model_registry_rows(settings.database_url),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Feature Ledger")
    st.dataframe(
        feature_ledger_rows(settings.database_url),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Decisions")
    st.dataframe(
        decision_rows(settings.database_url),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Risk")
    st.dataframe(
        risk_rows(settings.database_url),
        hide_index=True,
        use_container_width=True,
    )

    paper = paper_status_rows(settings.database_url)
    st.subheader("Paper Orders")
    st.dataframe(paper["orders"], hide_index=True, use_container_width=True)
    st.subheader("Paper Fills")
    st.dataframe(paper["fills"], hide_index=True, use_container_width=True)
    st.subheader("Paper Positions")
    st.dataframe(paper["positions"], hide_index=True, use_container_width=True)
    st.subheader("Paper Reconciliation")
    st.dataframe(paper["reconciliations"], hide_index=True, use_container_width=True)

    st.subheader("Shadow Comparisons")
    st.dataframe(shadow_rows(settings.database_url), hide_index=True, use_container_width=True)

    st.subheader("Live Adapter")
    st.dataframe(live_adapter_status_rows(settings), hide_index=True, use_container_width=True)
    st.dataframe(live_order_rows(settings.database_url), hide_index=True, use_container_width=True)

    st.caption(f"Generated {report.generated_at_utc.isoformat()}")


render()
