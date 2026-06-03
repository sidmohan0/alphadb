"""Streamlit entrypoint for the AlphaDB target-platform dashboard."""

import importlib
from datetime import UTC, datetime
from typing import Any, Mapping

import streamlit as st

from alphadb.dashboard import strategy_manager as strategy_manager_module
from alphadb.collectors.kalshi_rest import CollectorRunStore
from alphadb.config import settings_from_env
from alphadb.dashboard.auth import (
    DashboardAuthConfig,
    evaluate_access,
    remember_authenticated_browser,
)
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


STRATEGY_RUN_METRIC_LABELS = {
    "run_id": "run_id",
    "runtime_mode": "mode",
    "uptime_seconds": "uptime_seconds",
    "current_market_instance": "current_market",
    "terminal": "outcomes_recorded",
    "handled": "cycles_processed",
    "skipped": "cycles_skipped",
    "errored": "cycles_errored",
    "selected": "trade_signals",
    "risk_denied": "risk_denials",
    "paper_filled": "sim_fills",
    "rejected": "live_rejections",
    "scanned": "markets_scanned",
    "waiting": "markets_waiting",
    "cycle_scanned": "cycle_markets_scanned",
    "cycle_waiting": "cycle_markets_waiting",
    "cycle_handled": "cycle_markets_processed",
    "cycle_skipped": "cycle_markets_skipped",
    "cycle_errored": "cycle_market_errors",
    "cycle_duplicate_prevented": "cycle_duplicates_blocked",
    "duplicate_prevented": "duplicates_blocked",
    "last_scan_scanned": "last_scan_markets_scanned",
    "last_scan_waiting": "last_scan_markets_waiting",
    "last_scan_handled": "last_scan_markets_processed",
    "last_scan_skipped": "last_scan_markets_skipped",
    "last_scan_errored": "last_scan_market_errors",
    "last_scan_duplicate_prevented": "last_scan_duplicates_blocked",
    "model_artifact_sha256": "model_artifact_sha256",
    "feature_schema_sha256": "feature_schema_sha256",
    "per_trade_cap_dollars": "per_trade_cap_dollars",
    "max_daily_loss_dollars": "daily_loss_limit_dollars",
    "min_ev_dollars": "min_ev_dollars",
    "live_guard": "live_order_submit_ready",
}

STRATEGY_CYCLE_LABELS = {
    "handled": "cycle_processed",
    "skipped": "cycle_skipped",
    "error": "cycle_error",
}

SIGNAL_LABELS = {
    "order_candidate": "trade_signal",
    "skip": "no_trade",
}

LIVE_SUBMISSION_LABELS = {
    "submitted": "api_acknowledged",
    "accepted": "api_acknowledged",
    "rejected": "exchange_rejected",
    "guard_denied": "not_submitted",
    "error": "submit_error",
}

EXCHANGE_TERMINAL_STATUSES = {"canceled", "cancelled", "rejected", "failed", "executed", "filled"}

try:
    from streamlit_cookies_controller import CookieController as BrowserCookieController
except ImportError:  # pragma: no cover - exercised only when dashboard extra is missing.
    BrowserCookieController = None


SESSION_TOKEN_KEY = "_alphadb_dashboard_auth_token"
DASHBOARD_COOKIE_TTL_SECONDS = 60 * 60 * 24 * 7
DASHBOARD_COOKIE_NAME = "alphadb_dashboard_auth"


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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _payload_number(payload: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number(payload.get(key))
        if value is not None:
            return value
    return None


def _payload_text(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _text(payload.get(key))
        if value is not None:
            return value
    return None


def _round_or_none(value: Any, digits: int = 4) -> float | None:
    number = _number(value)
    return None if number is None else round(number, digits)


def _order_payload(response_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    order = response_payload.get("order")
    return order if isinstance(order, Mapping) else {}


def _execution_quantities(
    *,
    request_payload: Mapping[str, Any],
    response_payload: Mapping[str, Any],
) -> dict[str, float | None]:
    order = _order_payload(response_payload)
    fill_qty = _payload_number(
        response_payload,
        "fill_count",
        "fill_count_fp",
        "filled_quantity",
    )
    if fill_qty is None:
        fill_qty = _payload_number(order, "fill_count", "fill_count_fp", "filled_quantity")
    open_qty = _payload_number(response_payload, "remaining_count", "remaining_count_fp")
    if open_qty is None:
        open_qty = _payload_number(order, "remaining_count", "remaining_count_fp")
    initial_qty = _payload_number(response_payload, "initial_count", "initial_count_fp")
    if initial_qty is None:
        initial_qty = _payload_number(order, "initial_count", "initial_count_fp")
    if initial_qty is None:
        initial_qty = _payload_number(request_payload, "count")
    return {
        "initial_qty": initial_qty,
        "fill_qty": fill_qty,
        "open_qty": open_qty,
    }


def _exchange_order_status(response_payload: Mapping[str, Any]) -> str | None:
    order = _order_payload(response_payload)
    return _payload_text(order, "status") or _payload_text(response_payload, "status")


def _exchange_order_id(response_payload: Mapping[str, Any]) -> str | None:
    order = _order_payload(response_payload)
    return _payload_text(response_payload, "order_id") or _payload_text(order, "order_id")


def _execution_status(
    *,
    live_attempt_id: str | None,
    live_submission_status: str | None,
    exchange_order_status: str | None,
    fill_qty: float | None,
    open_qty: float | None,
    order_id: str | None,
) -> str:
    exchange_order_status = exchange_order_status.lower() if exchange_order_status else None
    if not live_attempt_id:
        return "no_live_order"
    if live_submission_status == "guard_denied":
        return "not_submitted"
    if live_submission_status == "rejected" or exchange_order_status == "rejected":
        return "rejected"
    if fill_qty is not None and fill_qty > 0 and open_qty is not None and open_qty > 0:
        return "partial_fill_open"
    if fill_qty is not None and fill_qty > 0:
        return "filled"
    if open_qty is not None and open_qty > 0:
        return "open_order"
    if exchange_order_status in {"executed", "filled"} and fill_qty is None:
        return "filled_qty_unknown"
    if exchange_order_status in EXCHANGE_TERMINAL_STATUSES:
        return "done_no_fill"
    if order_id and fill_qty == 0 and open_qty == 0:
        return "done_no_fill"
    if live_submission_status in {"submitted", "accepted"}:
        return "submitted_fill_unknown"
    return "unknown"


def _trader_signal_row(row: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _mapping(row.get("metadata"))
    request_payload = _mapping(row.get("live_order_request"))
    response_payload = _mapping(row.get("live_order_response"))
    quantities = _execution_quantities(
        request_payload=request_payload,
        response_payload=response_payload,
    )
    live_attempt_id = _text(row.get("live_order_attempt_id")) or _text(metadata.get("live_order_attempt_id"))
    live_submission_status = _text(row.get("live_submission_status")) or _text(
        metadata.get("live_order_status")
    )
    exchange_order_status = _exchange_order_status(response_payload)
    order_id = _exchange_order_id(response_payload)
    fill_qty = quantities["fill_qty"]
    open_qty = quantities["open_qty"]
    decision_outcome = _text(metadata.get("decision_outcome"))
    selected_side = _text(row.get("selected_side")) or _text(metadata.get("selected_side"))
    return {
        "decision_time_utc": row.get("decision_timestamp"),
        "market": row.get("market_ticker"),
        "cycle_status": STRATEGY_CYCLE_LABELS.get(str(row.get("status")), row.get("status")),
        "signal": SIGNAL_LABELS.get(str(decision_outcome), decision_outcome or row.get("reason")),
        "side": selected_side,
        "prob_yes": _round_or_none(metadata.get("probability_yes"), 4),
        "limit_price": _round_or_none(row.get("selected_price_dollars")),
        "size": _number(row.get("intended_quantity")) or _number(metadata.get("intended_quantity")),
        "expected_value_dollars": _round_or_none(row.get("selected_ev_dollars")),
        "risk": row.get("risk_status"),
        "execution_status": _execution_status(
            live_attempt_id=live_attempt_id,
            live_submission_status=live_submission_status,
            exchange_order_status=exchange_order_status,
            fill_qty=fill_qty,
            open_qty=open_qty,
            order_id=order_id,
        ),
        "order_status": exchange_order_status
        or LIVE_SUBMISSION_LABELS.get(str(live_submission_status), live_submission_status),
        "fill_qty": fill_qty,
        "open_qty": open_qty,
        "order_id": order_id,
        "order_attempt_id": live_attempt_id,
        "reason": row.get("reason") or row.get("risk_reason") or row.get("skip_reason"),
        "run_id": row.get("run_id"),
    }


def _trader_live_order_row(row: Mapping[str, Any]) -> dict[str, Any]:
    request_payload = _mapping(row.get("request_payload"))
    response_payload = _mapping(row.get("response_payload"))
    quantities = _execution_quantities(
        request_payload=request_payload,
        response_payload=response_payload,
    )
    exchange_order_status = _exchange_order_status(response_payload)
    order_id = _exchange_order_id(response_payload)
    fill_qty = quantities["fill_qty"]
    open_qty = quantities["open_qty"]
    return {
        "created_at": row.get("created_at"),
        "market": row.get("market_ticker"),
        "submission_status": LIVE_SUBMISSION_LABELS.get(str(row.get("status")), row.get("status")),
        "execution_status": _execution_status(
            live_attempt_id=_text(row.get("live_order_attempt_id")),
            live_submission_status=_text(row.get("status")),
            exchange_order_status=exchange_order_status,
            fill_qty=fill_qty,
            open_qty=open_qty,
            order_id=order_id,
        ),
        "side": request_payload.get("side"),
        "limit_price": _round_or_none(request_payload.get("price")),
        "initial_qty": quantities["initial_qty"],
        "fill_qty": fill_qty,
        "open_qty": open_qty,
        "order_status": exchange_order_status
        or LIVE_SUBMISSION_LABELS.get(str(row.get("status")), row.get("status")),
        "order_id": order_id,
        "client_order_id": request_payload.get("client_order_id") or response_payload.get("client_order_id"),
        "order_attempt_id": row.get("live_order_attempt_id"),
        "block_reason": row.get("guard_reason"),
    }


def _display_run_row(row: Mapping[str, Any]) -> dict[str, Any]:
    metric = str(row.get("metric"))
    detail = row.get("detail")
    if metric == "current_market_instance":
        detail = STRATEGY_CYCLE_LABELS.get(str(detail), detail)
    return {
        "metric": STRATEGY_RUN_METRIC_LABELS.get(metric, metric),
        "value": row.get("value"),
        "detail": detail,
    }


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
        return [_display_run_row(row) for row in rows]
    except Exception as exc:
        return [{"metric": "strategy_run", "value": "unavailable", "detail": str(exc)}]


def latest_strategy_outcome_rows(database_url: str) -> list[dict[str, str | int]]:
    try:
        rows = StrategyRunRepository(database_url).latest_outcomes(limit=10)
    except Exception as exc:
        return [{"outcome_id": "strategy_market_outcomes", "detail": str(exc)}]
    return [_trader_signal_row(row) for row in rows] or [
        {"signal": "none", "execution_status": "none"}
    ]


def live_order_rows(database_url: str) -> list[dict[str, str | int]]:
    try:
        rows = LiveOrderRepository(database_url).recent(limit=10)
    except Exception as exc:
        return [{"live_order_attempt_id": "live_order_attempts", "detail": str(exc)}]
    return [_trader_live_order_row(row) for row in rows] or [
        {"submission_status": "none", "execution_status": "none"}
    ]


def browser_cookie_token(config: DashboardAuthConfig, controller: object | None) -> str | None:
    context = getattr(st, "context", None)
    context_cookies = getattr(context, "cookies", {}) if context is not None else {}
    token = context_cookies.get(config.cookie_name) if hasattr(context_cookies, "get") else None
    if token:
        return str(token)
    if controller is not None and hasattr(controller, "get"):
        cookie = controller.get(config.cookie_name)
        if cookie:
            return str(cookie)
    session_token = st.session_state.get(SESSION_TOKEN_KEY)
    return str(session_token) if session_token else None


def dashboard_auth_config(settings) -> DashboardAuthConfig:
    return DashboardAuthConfig(
        pin=getattr(settings, "dashboard_pin", None),
        cookie_secret=getattr(settings, "dashboard_cookie_secret", None),
        cookie_ttl_seconds=getattr(
            settings,
            "dashboard_cookie_ttl_seconds",
            DASHBOARD_COOKIE_TTL_SECONDS,
        ),
        cookie_name=getattr(settings, "dashboard_cookie_name", DASHBOARD_COOKIE_NAME),
    ).validate()


def render_dashboard_login(settings) -> bool:
    config = dashboard_auth_config(settings)
    if not config.enabled:
        return True
    if BrowserCookieController is None:
        st.error("Dashboard cookie support is not installed.")
        st.stop()

    controller = BrowserCookieController()
    remember_token = browser_cookie_token(config, controller)
    decision = evaluate_access(config, remember_token=remember_token)
    if decision.authenticated:
        if remember_token:
            st.session_state[SESSION_TOKEN_KEY] = remember_token
        return True

    st.title("AlphaDB")
    st.subheader("Dashboard access")
    with st.form("dashboard_login"):
        pin = st.text_input("PIN", type="password", max_chars=4)
        submitted = st.form_submit_button("Unlock")

    if submitted:
        login = evaluate_access(config, submitted_pin=pin)
        if login.authenticated and login.remember_token:
            st.session_state[SESSION_TOKEN_KEY] = login.remember_token
            remember_authenticated_browser(config, controller, login.remember_token)
            st.rerun()
        st.error("Invalid PIN")
    st.stop()
    return False


def render_dashboard(settings, report) -> None:

    st.set_page_config(page_title="AlphaDB", layout="wide")
    if not render_dashboard_login(settings):
        return

    st.title("AlphaDB")

    status_label = "OK" if report.ok else "ERROR"
    status_delta = None if report.ok else "attention required"

    left, middle, right = st.columns(3)
    left.metric("Platform", status_label, delta=status_delta)
    middle.metric("Environment", report.environment)
    right.metric("Postgres", "configured", settings.database_url.rsplit("@", maxsplit=1)[-1])

    st.subheader("Ops Health")
    st.dataframe(report.as_rows(), hide_index=True, use_container_width=True)

    st.subheader("Market Universe")
    registry = default_market_registry()
    st.dataframe(
        [spec_summary_row(spec) for spec in registry.list()],
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Data Store Counts")
    st.dataframe(
        operational_state_rows(settings.database_url),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Live Trading Config")
    st.dataframe(runtime_status_rows(settings), hide_index=True, use_container_width=True)

    st.subheader("Run Monitor")
    st.dataframe(strategy_run_rows(settings.database_url), hide_index=True, use_container_width=True)

    importlib.reload(strategy_manager_module).render_strategy_manager(settings)

    st.subheader("Signal & Execution Blotter")
    st.dataframe(
        latest_strategy_outcome_rows(settings.database_url),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Market Data Events")
    st.dataframe(
        raw_event_rows(settings.database_url),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Data Ingestion")
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

    st.subheader("Feature Store")
    st.dataframe(
        feature_ledger_rows(settings.database_url),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Signal Decisions")
    st.dataframe(
        decision_rows(settings.database_url),
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Risk & Sizing Decisions")
    st.dataframe(
        risk_rows(settings.database_url),
        hide_index=True,
        use_container_width=True,
    )

    paper = paper_status_rows(settings.database_url)
    st.subheader("Simulator Orders")
    st.dataframe(paper["orders"], hide_index=True, use_container_width=True)
    st.subheader("Simulator Fills")
    st.dataframe(paper["fills"], hide_index=True, use_container_width=True)
    st.subheader("Simulator Positions")
    st.dataframe(paper["positions"], hide_index=True, use_container_width=True)
    st.subheader("Simulator P&L Reconciliation")
    st.dataframe(paper["reconciliations"], hide_index=True, use_container_width=True)

    st.subheader("Shadow Comparison Archive")
    st.dataframe(shadow_rows(settings.database_url), hide_index=True, use_container_width=True)

    st.subheader("Live Order Readiness")
    st.dataframe(live_adapter_status_rows(settings), hide_index=True, use_container_width=True)
    st.subheader("Live Execution Blotter")
    st.dataframe(live_order_rows(settings.database_url), hide_index=True, use_container_width=True)

    st.caption(f"Generated {report.generated_at_utc.isoformat()}")


def render() -> None:
    settings = settings_from_env()
    report = collect_health(settings=settings)
    render_dashboard(settings, report)


if __name__ == "__main__":
    render()
