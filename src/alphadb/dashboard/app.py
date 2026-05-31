"""Streamlit entrypoint for the AlphaDB target-platform dashboard."""

from __future__ import annotations

import streamlit as st

from alphadb.collectors.kalshi_rest import CollectorRunStore
from alphadb.config import settings_from_env
from alphadb.events.log import RawEventLog
from alphadb.health import collect_health
from alphadb.markets.cli import spec_summary_row
from alphadb.markets.registry import default_market_registry
from alphadb.model_registry.registry import ModelRegistryRepository
from alphadb.state.repository import OperationalStateRepository


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

    st.caption(f"Generated {report.generated_at_utc.isoformat()}")


render()
