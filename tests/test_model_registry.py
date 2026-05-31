from uuid import uuid4

import psycopg
import pytest
from pydantic import ValidationError

from alphadb.config import settings_from_env
from alphadb.model_registry.registry import (
    ImmutableModelReferenceError,
    ModelRegistration,
    ModelRegistryRepository,
    PromotionState,
)
from alphadb.state.repository import OperationalStateRepository


def registry_or_skip() -> tuple[OperationalStateRepository, ModelRegistryRepository]:
    repository = OperationalStateRepository(settings_from_env().database_url)
    try:
        with repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    repository.apply_migrations()
    return repository, ModelRegistryRepository(repository.database_url)


def valid_registration(**overrides: object) -> ModelRegistration:
    values = {
        "series": "KXBTC15M",
        "model_name": "unit-test-model",
        "model_version": "v1",
        "artifact_uri": "artifacts/models/unit-test-model/v1/model.joblib",
        "artifact_sha256": "b" * 64,
        "feature_version": "features.kxbtc15m.v1",
        "calibration_version": "calibration.isotonic.v1",
        "dataset_id": "dataset_kxbtc15m_unit_v1",
        "promotion_state": PromotionState.CANDIDATE,
        "report_uri": "artifacts/reports/unit-test-model/v1/report.json",
        "metadata": {"framework": "sklearn"},
    }
    values.update(overrides)
    return ModelRegistration(**values)


def test_model_registry_registers_reads_lists_and_promotes_model_metadata() -> None:
    _state_repository, registry = registry_or_skip()
    registration = valid_registration(model_version=f"v-register-read-list-{uuid4().hex}")

    created = registry.register(registration)
    fetched = registry.get(created.model_id)
    listed = registry.list(series="KXBTC15M")
    promoted = registry.set_promotion_state(
        model_id=created.model_id,
        promotion_state=PromotionState.SHADOW,
    )

    assert created.inserted is True
    assert fetched.artifact_uri == registration.artifact_uri
    assert fetched.artifact_sha256 == registration.artifact_sha256
    assert fetched.feature_version == "features.kxbtc15m.v1"
    assert fetched.calibration_version == "calibration.isotonic.v1"
    assert fetched.dataset_id == "dataset_kxbtc15m_unit_v1"
    assert fetched.promotion_state == PromotionState.CANDIDATE
    assert any(model.model_id == created.model_id for model in listed)
    assert promoted.promotion_state == PromotionState.SHADOW


def test_model_registry_rejects_missing_or_incompatible_metadata() -> None:
    with pytest.raises(ValidationError):
        ModelRegistration(
            series="KXBTC15M",
            model_name="missing-calibration",
            model_version="v1",
            artifact_uri="artifacts/models/missing/model.joblib",
            artifact_sha256="c" * 64,
            feature_version="features.kxbtc15m.v1",
            dataset_id="dataset_kxbtc15m_unit_v1",
        )

    with pytest.raises(ValidationError):
        valid_registration(artifact_sha256="not-a-sha")

    with pytest.raises(ValidationError):
        valid_registration(metadata={"artifact_blob": "inline bytes belong in artifact storage"})

    with pytest.raises(ValidationError):
        valid_registration(artifact_uri="data:application/octet-stream;base64,AAAA")


def test_model_identity_is_idempotent_only_when_immutable_references_match() -> None:
    _state_repository, registry = registry_or_skip()
    model_version = f"v-immutable-{uuid4().hex}"
    registration = valid_registration(model_version=model_version)

    first = registry.register(registration)
    second = registry.register(registration)

    assert second.inserted is False
    assert second.model_id == first.model_id

    with pytest.raises(ImmutableModelReferenceError):
        registry.register(
            valid_registration(
                model_version=model_version,
                artifact_sha256="d" * 64,
            )
        )


def test_model_registry_schema_does_not_store_artifact_blobs() -> None:
    repository, _registry = registry_or_skip()

    with repository.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select column_name, data_type
                from information_schema.columns
                where table_name = 'model_registry_records'
                """
            )
            columns = {row["column_name"]: row["data_type"] for row in cursor.fetchall()}

    assert "artifact_uri" in columns
    assert "artifact_sha256" in columns
    assert "bytea" not in columns.values()
