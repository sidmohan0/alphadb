"""Postgres-backed model registry for immutable model artifact references."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphadb.config import settings_from_env
from alphadb.state.repository import OperationalStateRepository


class PromotionState(StrEnum):
    CANDIDATE = "candidate"
    SHADOW = "shadow"
    PAPER = "paper"
    LIVE = "live"
    ARCHIVED = "archived"
    REJECTED = "rejected"


class ImmutableModelReferenceError(ValueError):
    """Raised when a registered model identity points at different immutable inputs."""


class ModelRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    series: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    artifact_uri: str = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    feature_version: str = Field(min_length=1)
    calibration_version: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    promotion_state: PromotionState = PromotionState.CANDIDATE
    report_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("artifact_uri", "report_uri")
    @classmethod
    def reject_inline_artifacts(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value.startswith("data:"):
            raise ValueError("artifact/report URI must reference external immutable storage")
        return value

    @field_validator("metadata")
    @classmethod
    def reject_artifact_blobs(cls, value: dict[str, Any]) -> dict[str, Any]:
        blocked_keys = {"artifact_blob", "model_blob", "binary_blob", "pickle_blob", "bytes"}
        if blocked_keys.intersection(value):
            raise ValueError("model registry metadata must not contain artifact blobs")
        return value


class RegisteredModel(ModelRegistration):
    model_id: str
    created_at: datetime
    updated_at: datetime
    inserted: bool = True

    def as_dict(self) -> dict[str, Any]:
        row = self.model_dump(mode="json")
        row["promotion_state"] = str(self.promotion_state)
        return row


class ModelRegistryRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def register(self, registration: ModelRegistration) -> RegisteredModel:
        model_id = f"model_{uuid4().hex[:12]}"
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into model_registry_records (
                        model_id,
                        series,
                        model_name,
                        model_version,
                        artifact_uri,
                        artifact_sha256,
                        feature_version,
                        calibration_version,
                        dataset_id,
                        promotion_state,
                        report_uri,
                        metadata
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (series, model_name, model_version) do nothing
                    returning *
                    """,
                    (
                        model_id,
                        registration.series,
                        registration.model_name,
                        registration.model_version,
                        registration.artifact_uri,
                        registration.artifact_sha256,
                        registration.feature_version,
                        registration.calibration_version,
                        registration.dataset_id,
                        str(registration.promotion_state),
                        registration.report_uri,
                        Jsonb(registration.metadata),
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    row = self._fetch_by_identity(cursor, registration)
                    self._ensure_immutable_reference_matches(registration, row)
                    row = {**row, "inserted": False}
            connection.commit()
        return row_to_registered_model(row)

    def get(self, model_id: str) -> RegisteredModel:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "select * from model_registry_records where model_id = %s",
                    (model_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise KeyError(f"unknown model_id: {model_id}")
        return row_to_registered_model(row)

    def list(
        self,
        *,
        series: str | None = None,
        promotion_state: PromotionState | str | None = None,
    ) -> list[RegisteredModel]:
        clauses: list[str] = []
        params: list[str] = []
        if series is not None:
            clauses.append("series = %s")
            params.append(series)
        if promotion_state is not None:
            clauses.append("promotion_state = %s")
            params.append(str(promotion_state))
        where = f"where {' and '.join(clauses)}" if clauses else ""

        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select *
                    from model_registry_records
                    {where}
                    order by updated_at desc, created_at desc, model_id desc
                    """,
                    params,
                )
                rows = cursor.fetchall()
        return [row_to_registered_model(row) for row in rows]

    def set_promotion_state(
        self,
        *,
        model_id: str,
        promotion_state: PromotionState,
    ) -> RegisteredModel:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update model_registry_records
                    set promotion_state = %s, updated_at = now()
                    where model_id = %s
                    returning *
                    """,
                    (str(promotion_state), model_id),
                )
                row = cursor.fetchone()
            connection.commit()
        if row is None:
            raise KeyError(f"unknown model_id: {model_id}")
        return row_to_registered_model(row)

    def recent_models(self, *, limit: int = 10) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select
                        model_id,
                        series,
                        model_name,
                        model_version,
                        artifact_uri,
                        left(artifact_sha256, 12) as artifact_sha256_prefix,
                        feature_version,
                        calibration_version,
                        dataset_id,
                        promotion_state,
                        updated_at
                    from model_registry_records
                    order by updated_at desc, created_at desc, model_id desc
                    limit %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _fetch_by_identity(
        self,
        cursor: psycopg.Cursor,
        registration: ModelRegistration,
    ) -> Mapping[str, Any]:
        cursor.execute(
            """
            select *
            from model_registry_records
            where series = %s and model_name = %s and model_version = %s
            """,
            (registration.series, registration.model_name, registration.model_version),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("model registration conflict neither inserted nor found existing row")
        return row

    def _ensure_immutable_reference_matches(
        self,
        registration: ModelRegistration,
        existing: Mapping[str, Any],
    ) -> None:
        immutable_fields = (
            "artifact_uri",
            "artifact_sha256",
            "feature_version",
            "calibration_version",
            "dataset_id",
        )
        mismatches = [
            field for field in immutable_fields if str(existing[field]) != str(getattr(registration, field))
        ]
        if mismatches:
            joined = ", ".join(mismatches)
            raise ImmutableModelReferenceError(
                "model identity already registered with different immutable fields: "
                f"{joined}"
            )


def row_to_registered_model(row: Mapping[str, Any]) -> RegisteredModel:
    values = dict(row)
    values.setdefault("inserted", True)
    return RegisteredModel(
        model_id=str(values["model_id"]),
        series=str(values["series"]),
        model_name=str(values["model_name"]),
        model_version=str(values["model_version"]),
        artifact_uri=str(values["artifact_uri"]),
        artifact_sha256=str(values["artifact_sha256"]),
        feature_version=str(values["feature_version"]),
        calibration_version=str(values["calibration_version"]),
        dataset_id=str(values["dataset_id"]),
        promotion_state=PromotionState(str(values["promotion_state"])),
        report_uri=values["report_uri"],
        metadata=dict(values["metadata"]),
        created_at=values["created_at"],
        updated_at=values["updated_at"],
        inserted=bool(values["inserted"]),
    )


def demo_registration(series: str = "KXBTC15M") -> ModelRegistration:
    return ModelRegistration(
        series=series,
        model_name="kxbtc15m-baseline-logistic",
        model_version="v0.1.0",
        artifact_uri="artifacts/models/kxbtc15m-baseline-logistic/v0.1.0/model.joblib",
        artifact_sha256="a" * 64,
        feature_version="features.kxbtc15m.v1",
        calibration_version="calibration.none.v1",
        dataset_id="dataset_kxbtc15m_tracer_v1",
        promotion_state=PromotionState.CANDIDATE,
        report_uri="artifacts/reports/kxbtc15m-baseline-logistic/v0.1.0/report.json",
        metadata={"registered_by": "alphadb-models register-demo"},
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-models")
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser("register", help="Register model artifact metadata")
    register_parser.add_argument("--series", required=True)
    register_parser.add_argument("--model-name", required=True)
    register_parser.add_argument("--model-version", required=True)
    register_parser.add_argument("--artifact-uri", required=True)
    register_parser.add_argument("--artifact-sha256", required=True)
    register_parser.add_argument("--feature-version", required=True)
    register_parser.add_argument("--calibration-version", required=True)
    register_parser.add_argument("--dataset-id", required=True)
    register_parser.add_argument("--promotion-state", default=PromotionState.CANDIDATE.value)
    register_parser.add_argument("--report-uri", default=None)
    register_parser.add_argument("--metadata-json", default="{}")

    demo_parser = subparsers.add_parser("register-demo", help="Register deterministic demo metadata")
    demo_parser.add_argument("--series", default="KXBTC15M")

    list_parser = subparsers.add_parser("list", help="List registered models")
    list_parser.add_argument("--series", default=None)
    list_parser.add_argument("--promotion-state", default=None)

    show_parser = subparsers.add_parser("show", help="Show one registered model")
    show_parser.add_argument("model_id")

    promote_parser = subparsers.add_parser("promote", help="Change model promotion state")
    promote_parser.add_argument("model_id")
    promote_parser.add_argument("--state", required=True, choices=[state.value for state in PromotionState])

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    OperationalStateRepository(settings.database_url).apply_migrations()
    repository = ModelRegistryRepository(settings.database_url)

    if args.command == "register":
        registration = ModelRegistration(
            series=args.series,
            model_name=args.model_name,
            model_version=args.model_version,
            artifact_uri=args.artifact_uri,
            artifact_sha256=args.artifact_sha256,
            feature_version=args.feature_version,
            calibration_version=args.calibration_version,
            dataset_id=args.dataset_id,
            promotion_state=PromotionState(args.promotion_state),
            report_uri=args.report_uri,
            metadata=json.loads(args.metadata_json),
        )
        print(json.dumps(repository.register(registration).as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "register-demo":
        print(
            json.dumps(
                repository.register(demo_registration(args.series)).as_dict(),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "list":
        rows = [
            model.as_dict()
            for model in repository.list(
                series=args.series,
                promotion_state=args.promotion_state,
            )
        ]
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    if args.command == "show":
        print(json.dumps(repository.get(args.model_id).as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "promote":
        model = repository.set_promotion_state(
            model_id=args.model_id,
            promotion_state=PromotionState(args.state),
        )
        print(json.dumps(model.as_dict(), indent=2, sort_keys=True))
        return 0

    raise AssertionError(f"unhandled command: {args.command}")
