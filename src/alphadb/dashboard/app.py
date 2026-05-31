"""Streamlit entrypoint for the AlphaDB target-platform dashboard."""

from __future__ import annotations

import streamlit as st

from alphadb.config import settings_from_env
from alphadb.health import collect_health
from alphadb.markets.cli import spec_summary_row
from alphadb.markets.registry import default_market_registry
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

    st.caption(f"Generated {report.generated_at_utc.isoformat()}")


render()
