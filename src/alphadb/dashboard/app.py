"""Streamlit entrypoint for the AlphaDB target-platform dashboard."""

from __future__ import annotations

import streamlit as st

from alphadb.config import settings_from_env
from alphadb.health import collect_health


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
    st.caption(f"Generated {report.generated_at_utc.isoformat()}")


render()
