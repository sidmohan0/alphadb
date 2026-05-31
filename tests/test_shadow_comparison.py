from datetime import UTC, datetime

import psycopg
import pytest

from alphadb.config import settings_from_env
from alphadb.shadow.comparison import (
    DecisionBoundaryRecord,
    ShadowComparator,
    ShadowComparisonRepository,
)
from alphadb.state.repository import OperationalStateRepository


def shadow_repository_or_skip() -> ShadowComparisonRepository:
    repository = OperationalStateRepository(settings_from_env().database_url)
    try:
        with repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    repository.apply_migrations()
    return ShadowComparisonRepository(repository.database_url)


def boundary(**overrides: object) -> DecisionBoundaryRecord:
    values = {
        "market_ticker": "KXBTC15M-26MAY312100-00",
        "decision_timestamp": datetime(2026, 5, 31, 21, 14, tzinfo=UTC),
        "feature_row_id": "feature_abc",
        "feature_row_hash": "f" * 64,
        "model_id": "model_abc",
        "probability_yes": 0.65,
        "executable_quotes": {"yes_ask_dollars": 0.52, "no_ask_dollars": 0.53},
        "selected_ev_dollars": 0.112528,
        "selected_side": "yes",
        "skip_reason": None,
        "risk_status": "approved",
        "intended_quantity": 1,
        "source": "alphadb",
    }
    values.update(overrides)
    return DecisionBoundaryRecord.from_mapping(values)


def test_shadow_comparison_exact_match_persists_recent_status() -> None:
    repository = shadow_repository_or_skip()
    alpha = boundary(source="alphadb")
    current = boundary(source="current_mvp")

    report = repository.persist(ShadowComparator().compare(alpha=alpha, current_mvp=current))
    recent = repository.recent(limit=1)

    assert report.status == "match"
    assert report.mismatch_count == 0
    assert report.intentional_difference_count == 0
    assert report.alpha_controls_live_orders is False
    assert recent[0]["comparison_id"] == report.comparison_id
    assert recent[0]["mismatch_count"] == 0


def test_shadow_comparison_detects_mismatch() -> None:
    alpha = boundary(selected_side="yes")
    current = boundary(selected_side="no", source="current_mvp")

    report = ShadowComparator().compare(alpha=alpha, current_mvp=current)

    assert report.status == "mismatch"
    assert report.mismatch_count == 1
    assert [item.field for item in report.comparisons if item.status == "mismatch"] == [
        "selected_side"
    ]


def test_shadow_comparison_handles_missing_current_mvp_data() -> None:
    report = ShadowComparator().compare(alpha=boundary(), current_mvp=None)

    assert report.status == "missing_current_mvp_data"
    assert report.current_mvp is None
    assert report.mismatch_count == 0
    assert report.alpha_controls_live_orders is False


def test_shadow_comparison_marks_intentional_documented_differences() -> None:
    alpha = boundary(selected_ev_dollars=0.112528)
    current = boundary(selected_ev_dollars=0.10, source="current_mvp")

    report = ShadowComparator().compare(
        alpha=alpha,
        current_mvp=current,
        intentional_differences={"selected_ev_dollars": "AlphaDB applies taker fee v1"},
    )

    intentional = [item for item in report.comparisons if item.status == "intentional_difference"]
    assert report.status == "intentional_difference"
    assert report.mismatch_count == 0
    assert report.intentional_difference_count == 1
    assert intentional[0].field == "selected_ev_dollars"
    assert intentional[0].note == "AlphaDB applies taker fee v1"
