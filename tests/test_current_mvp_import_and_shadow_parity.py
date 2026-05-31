import psycopg
import pytest

from alphadb.config import settings_from_env
from alphadb.shadow.comparison import DecisionBoundaryRecord
from alphadb.shadow.current_mvp import (
    CURRENT_MVP_BOUNDARY_SCHEMA,
    CurrentMvpBoundaryImporter,
    CurrentMvpImportError,
)
from alphadb.shadow.parity import ShadowParityRunner
from alphadb.state.repository import OperationalStateRepository


def shadow_db_or_skip() -> OperationalStateRepository:
    repository = OperationalStateRepository(settings_from_env().database_url)
    try:
        with repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    repository.apply_migrations()
    return repository


def boundary(**overrides: object) -> dict:
    values = {
        "market_ticker": "KXBTC15M-26MAY312100-00",
        "decision_timestamp": "2026-05-31T21:13:00+00:00",
        "feature_row_id": "feature_1",
        "feature_row_hash": "f" * 64,
        "model_id": "model_1",
        "model_artifact_sha256": "a" * 64,
        "probability_yes": 0.66,
        "executable_quotes": {"yes_ask_dollars": 0.52, "no_ask_dollars": 0.53},
        "yes_ev_dollars": 0.123,
        "no_ev_dollars": -0.211,
        "selected_ev_dollars": 0.123,
        "selected_side": "yes",
        "skip_reason": None,
        "risk_status": "approved",
        "intended_quantity": 1,
        "feature_values": {"yes_ask": 0.52, "external_close": 101.2},
        "timing_metadata": {"model_inference_ms": 1.2},
    }
    values.update(overrides)
    return values


def test_current_mvp_import_maps_fixture_boundary_and_rejects_bad_records() -> None:
    repository = shadow_db_or_skip()
    importer = CurrentMvpBoundaryImporter(repository.database_url)

    imported = importer.import_mapping(
        {
            "schema_version": CURRENT_MVP_BOUNDARY_SCHEMA,
            "boundary": boundary(),
            "intentional_differences": {"feature_row_hash": "hashes differ by platform id"},
        },
        source_identity="fixture.json",
    )

    assert imported.boundary.source == "current_mvp"
    assert imported.boundary.probability_yes == 0.66
    assert imported.intentional_differences["feature_row_hash"]
    assert imported.source_identity == "fixture.json"
    assert imported.record_hash

    with pytest.raises(CurrentMvpImportError, match="schema_version"):
        importer.import_mapping({"schema_version": "old", "boundary": boundary()})
    with pytest.raises(CurrentMvpImportError, match="malformed"):
        importer.import_mapping({"schema_version": CURRENT_MVP_BOUNDARY_SCHEMA, "boundary": {"market_ticker": "x"}})
    with pytest.raises(CurrentMvpImportError, match="forbidden secret"):
        importer.import_mapping(
            {
                "schema_version": CURRENT_MVP_BOUNDARY_SCHEMA,
                "boundary": boundary(),
                "api_key": "nope",
            }
        )


def test_shadow_parity_runner_distinguishes_matches_mismatches_missing_and_intentional() -> None:
    repository = shadow_db_or_skip()
    runner = ShadowParityRunner(repository.database_url)
    alpha = DecisionBoundaryRecord.from_mapping({**boundary(), "source": "alphadb"})
    current = DecisionBoundaryRecord.from_mapping({**boundary(), "source": "current_mvp"})

    exact = runner.compare_boundaries(alpha=alpha, current_mvp=current)
    feature_mismatch = runner.compare_boundaries(
        alpha=DecisionBoundaryRecord.from_mapping({**boundary(feature_values={"yes_ask": 0.52}), "source": "alphadb"}),
        current_mvp=DecisionBoundaryRecord.from_mapping({**boundary(feature_values={"yes_ask": 0.51}), "source": "current_mvp"}),
    )
    ev_mismatch = runner.compare_boundaries(
        alpha=DecisionBoundaryRecord.from_mapping({**boundary(yes_ev_dollars=0.123), "source": "alphadb"}),
        current_mvp=DecisionBoundaryRecord.from_mapping({**boundary(yes_ev_dollars=0.111), "source": "current_mvp"}),
    )
    side_mismatch = runner.compare_boundaries(
        alpha=DecisionBoundaryRecord.from_mapping({**boundary(selected_side="yes"), "source": "alphadb"}),
        current_mvp=DecisionBoundaryRecord.from_mapping({**boundary(selected_side="no"), "source": "current_mvp"}),
    )
    missing_current = runner.compare_boundaries(alpha=alpha, current_mvp=None)
    missing_alpha = runner.compare_boundaries(alpha=None, current_mvp=current)
    intentional = runner.compare_boundaries(
        alpha=alpha,
        current_mvp=DecisionBoundaryRecord.from_mapping({**boundary(feature_row_hash="b" * 64), "source": "current_mvp"}),
        intentional_differences={"feature_row_hash": "platform-specific row hash"},
    )

    assert exact.status == "match"
    assert feature_mismatch.status == "mismatch"
    assert [item.field for item in feature_mismatch.comparisons if item.status == "mismatch"] == ["feature_values"]
    assert ev_mismatch.status == "mismatch"
    assert side_mismatch.status == "mismatch"
    assert missing_current.status == "missing_current_mvp_data"
    assert missing_alpha.status == "missing_alpha_data"
    assert intentional.status == "intentional_difference"
