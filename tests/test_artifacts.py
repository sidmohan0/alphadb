import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from alphadb.artifacts import (
    ArtifactLoadError,
    file_sha256,
    load_pinned_artifact_config,
    load_pinned_model_policy,
    register_loaded_model,
)
from alphadb.config import settings_from_env
from alphadb.state.repository import OperationalStateRepository


def artifact_fixture(tmp_path: Path, *, candidate: str = "constant_probability") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    model = tmp_path / "model.json"
    schema = tmp_path / "feature_schema.json"
    report = tmp_path / "report.json"
    model.write_text(
        json.dumps(
            {
                "type": "constant_probability",
                "probability_yes": 0.65,
                "feature_columns": ["yes_ask", "no_ask", "external_close"],
            }
        ),
        encoding="utf-8",
    )
    schema.write_text(
        json.dumps(
            {
                "schema_version": "kxbtc_feature_schema_v1",
                "feature_columns": ["yes_ask", "no_ask", "external_close"],
            }
        ),
        encoding="utf-8",
    )
    report.write_text(
        json.dumps(
            {
                "selection": {
                    "selection": {
                        "candidate": candidate,
                        "decision_minute_offset": 12,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    config = tmp_path / "artifacts.json"
    config.write_text(
        json.dumps(
            {
                "candidate": candidate,
                "decision_minute_offset": 12,
                "mode": "conditional",
                "sizing": "fixed_dollars",
                "model_name": "current-mvp-test",
                "model_version": f"v-{uuid4().hex}",
                "dataset_id": "dataset-test",
                "artifacts": {
                    "model_path": model.name,
                    "model_sha256": file_sha256(model),
                    "feature_schema_path": schema.name,
                    "feature_schema_sha256": file_sha256(schema),
                    "model_selection_report_path": report.name,
                    "model_selection_report_sha256": file_sha256(report),
                },
            }
        ),
        encoding="utf-8",
    )
    return config


def postgres_or_skip() -> OperationalStateRepository:
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


def test_pinned_artifact_loader_validates_hashes_and_predicts_probability(tmp_path: Path) -> None:
    config_path = artifact_fixture(tmp_path)

    config = load_pinned_artifact_config(artifact_root=tmp_path, config_path=config_path)
    policy = load_pinned_model_policy(config)

    assert policy.feature_columns == ("yes_ask", "no_ask", "external_close")
    assert policy.predict_yes_probability(
        {"yes_ask": 0.51, "no_ask": 0.52, "external_close": 100.0}
    ) == 0.65


def test_pinned_artifact_loader_fails_closed_for_hash_candidate_and_schema_mismatch(
    tmp_path: Path,
) -> None:
    config_path = artifact_fixture(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["artifacts"]["model_sha256"] = "0" * 64
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ArtifactLoadError, match="sha256 mismatch"):
        load_pinned_artifact_config(artifact_root=tmp_path, config_path=config_path)

    unsupported = artifact_fixture(tmp_path / "unsupported", candidate="neural_magic")
    with pytest.raises(ArtifactLoadError, match="unsupported"):
        load_pinned_artifact_config(artifact_root=unsupported.parent, config_path=unsupported)

    mismatched = artifact_fixture(tmp_path / "mismatch")
    schema_path = mismatched.parent / "feature_schema.json"
    schema_path.write_text(
        json.dumps({"feature_columns": ["yes_ask", "different_feature"]}),
        encoding="utf-8",
    )
    payload = json.loads(mismatched.read_text(encoding="utf-8"))
    payload["artifacts"]["feature_schema_sha256"] = file_sha256(schema_path)
    mismatched.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ArtifactLoadError, match="feature columns"):
        load_pinned_model_policy(
            load_pinned_artifact_config(artifact_root=mismatched.parent, config_path=mismatched)
        )


def test_loaded_model_metadata_can_be_registered_without_storing_binary(tmp_path: Path) -> None:
    repository = postgres_or_skip()
    config_path = artifact_fixture(tmp_path)
    policy = load_pinned_model_policy(
        load_pinned_artifact_config(artifact_root=tmp_path, config_path=config_path)
    )

    model = register_loaded_model(database_url=repository.database_url, policy=policy)

    assert model.artifact_uri.endswith("model.json")
    assert model.artifact_sha256 == policy.model_artifact_sha256
    assert "artifact_blob" not in model.metadata
