from __future__ import annotations

import pytest

from alphadb.dashboard.data_explorer import build_data_query


def test_data_query_uses_allowlisted_filters_sort_and_limit() -> None:
    query = build_data_query(
        "decisions",
        filters={
            "run_id": "run_1",
            "outcome": "skip",
            "source": "ignored-because-decisions-has-no-source",
            "raw_sql": "drop table decisions",
        },
        sort={"column": "source", "direction": "sideways"},
        limit=10_000,
    )

    assert query.view.name == "decisions"
    assert query.filters == {"run_id": "run_1", "outcome": "skip"}
    assert query.sort == {"column": "decision_timestamp", "direction": "desc"}
    assert query.limit == 500


def test_data_query_allows_view_specific_columns() -> None:
    query = build_data_query(
        "raw_events",
        filters={"source": "kalshi_rest", "market_ticker": "KXBTC15M-TEST"},
        sort={"column": "received_at", "direction": "asc"},
        limit=25,
    )

    assert query.filters == {"source": "kalshi_rest", "market_ticker": "KXBTC15M-TEST"}
    assert query.sort == {"column": "received_at", "direction": "asc"}
    assert query.limit == 25


def test_unknown_data_view_is_rejected() -> None:
    with pytest.raises(KeyError, match="unknown data view"):
        build_data_query("freeform_sql", filters={}, sort={}, limit=100)
