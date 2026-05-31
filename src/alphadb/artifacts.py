"""Pinned Current MVP artifact loading without storing private artifacts in Git."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import yaml

from alphadb.config import Settings, settings_from_env
from alphadb.model_registry.registry import (
    ModelRegistration,
    ModelRegistryRepository,
    PromotionState,
    RegisteredModel,
)
from alphadb.state.repository import OperationalStateRepository

SUPPORTED_CANDIDATES = {"extra_trees", "constant_probability"}


class ArtifactLoadError(RuntimeError):
    """Raised when pinned artifacts cannot be safely loaded."""


@dataclass(frozen=True)
class PinnedArtifactReference:
    path: Path
    sha256: str

    def as_dict(self) -> dict[str, str]:
        return {"path": str(self.path), "sha256": self.sha256}


@dataclass(frozen=True)
class PinnedArtifactConfig:
    artifact_root: Path
    candidate: str
    decision_minute_offset: int
    mode: str
    sizing: str
    model: PinnedArtifactReference
    feature_schema: PinnedArtifactReference
    model_selection_report: PinnedArtifactReference
    calibration_version: str
    dataset_id: str
    model_name: str
    model_version: str

    def as_model_registration(self, *, series: str = "KXBTC15M") -> ModelRegistration:
        return ModelRegistration(
            series=series,
            model_name=self.model_name,
            model_version=self.model_version,
            artifact_uri=str(self.model.path),
            artifact_sha256=self.model.sha256,
            feature_version="current_mvp." + self.feature_schema.sha256[:12],
            calibration_version=self.calibration_version,
            dataset_id=self.dataset_id,
            promotion_state=PromotionState.PAPER,
            report_uri=str(self.model_selection_report.path),
            metadata={
                "candidate": self.candidate,
                "feature_schema_path": str(self.feature_schema.path),
                "feature_schema_sha256": self.feature_schema.sha256,
                "model_selection_report_sha256": self.model_selection_report.sha256,
                "decision_minute_offset": self.decision_minute_offset,
                "mode": self.mode,
                "sizing": self.sizing,
            },
        )


@dataclass(frozen=True)
class PinnedModelPolicy:
    config: PinnedArtifactConfig
    estimator: object
    feature_columns: tuple[str, ...]
    feature_schema: Mapping[str, Any]
    model_selection_report: Mapping[str, Any]

    @property
    def model_artifact_sha256(self) -> str:
        return self.config.model.sha256

    @property
    def feature_schema_sha256(self) -> str:
        return self.config.feature_schema.sha256

    def predict_yes_probability(self, feature_values: Mapping[str, Any]) -> float:
        missing = [column for column in self.feature_columns if column not in feature_values]
        if missing:
            raise ArtifactLoadError(f"feature row missing model columns: {', '.join(missing)}")
        row = [[float(feature_values[column]) for column in self.feature_columns]]
        estimator = self.estimator
        if isinstance(estimator, Mapping) and estimator.get("type") == "constant_probability":
            return float(estimator["probability_yes"])
        if not hasattr(estimator, "predict_proba"):
            raise ArtifactLoadError("loaded estimator does not expose predict_proba")
        probability = estimator.predict_proba(row)
        return float(probability[0][1])

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.config.candidate,
            "decision_minute_offset": self.config.decision_minute_offset,
            "model_name": self.config.model_name,
            "model_version": self.config.model_version,
            "model": self.config.model.as_dict(),
            "feature_schema": self.config.feature_schema.as_dict(),
            "model_selection_report": self.config.model_selection_report.as_dict(),
            "feature_columns": list(self.feature_columns),
            "calibration_version": self.config.calibration_version,
            "dataset_id": self.config.dataset_id,
        }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json_or_yaml(path: Path) -> Mapping[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ArtifactLoadError(f"artifact config missing: {path}") from exc
    if path.suffix.lower() in {".yaml", ".yml"}:
        loaded = yaml.safe_load(text)
    else:
        loaded = json.loads(text)
    if not isinstance(loaded, Mapping):
        raise ArtifactLoadError(f"artifact config must be an object: {path}")
    return loaded


def load_pinned_artifact_config(
    *,
    artifact_root: str | Path,
    config_path: str | Path,
) -> PinnedArtifactConfig:
    root = Path(artifact_root).expanduser().resolve()
    config_path = Path(config_path).expanduser().resolve()
    raw = load_json_or_yaml(config_path)
    live_policy = raw.get("live_policy") if isinstance(raw.get("live_policy"), Mapping) else raw
    artifacts = live_policy.get("artifacts") if isinstance(live_policy.get("artifacts"), Mapping) else raw

    candidate = str(live_policy.get("candidate") or raw.get("candidate") or "")
    if candidate not in SUPPORTED_CANDIDATES:
        raise ArtifactLoadError(f"unsupported Current MVP candidate: {candidate!r}")

    report_path_value = artifacts.get("model_selection_report_path") or artifacts.get("report_path")
    model_ref = resolve_verified_reference(
        root,
        artifacts.get("model_path"),
        artifacts.get("model_sha256"),
        "model artifact",
    )
    schema_ref = resolve_verified_reference(
        root,
        artifacts.get("feature_schema_path"),
        artifacts.get("feature_schema_sha256"),
        "feature schema",
    )
    report_ref = resolve_verified_reference(
        root,
        report_path_value,
        artifacts.get("model_selection_report_sha256") or artifacts.get("report_sha256"),
        "model-selection report",
    )
    return PinnedArtifactConfig(
        artifact_root=root,
        candidate=candidate,
        decision_minute_offset=int(live_policy.get("decision_minute_offset", 12)),
        mode=str(live_policy.get("mode", "conditional")),
        sizing=str(live_policy.get("sizing", "fixed_dollars")),
        model=model_ref,
        feature_schema=schema_ref,
        model_selection_report=report_ref,
        calibration_version=str(live_policy.get("calibration_version", "calibration.none.v1")),
        dataset_id=str(live_policy.get("dataset_id", "current_mvp_pinned_dataset")),
        model_name=str(live_policy.get("model_name", f"current-mvp-{candidate}")),
        model_version=str(live_policy.get("model_version", "pinned")),
    )


def resolve_verified_reference(
    root: Path,
    path_value: Any,
    expected_sha256: Any,
    label: str,
) -> PinnedArtifactReference:
    if not path_value:
        raise ArtifactLoadError(f"{label} path is required")
    if not expected_sha256:
        raise ArtifactLoadError(f"{label} sha256 is required")
    path = Path(str(path_value)).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.exists():
        raise ArtifactLoadError(f"{label} missing: {path}")
    actual = file_sha256(path)
    if actual != str(expected_sha256):
        raise ArtifactLoadError(f"{label} sha256 mismatch: expected {expected_sha256}, got {actual}")
    return PinnedArtifactReference(path=path, sha256=actual)


def load_pinned_model_policy(config: PinnedArtifactConfig) -> PinnedModelPolicy:
    feature_schema = dict(load_json_or_yaml(config.feature_schema.path))
    report = dict(load_json_or_yaml(config.model_selection_report.path))
    feature_columns = extract_feature_columns(feature_schema)
    validate_selection_metadata(config, report)
    estimator, model_features = load_estimator(config.model.path)
    if model_features is not None and tuple(model_features) != feature_columns:
        raise ArtifactLoadError("model artifact feature columns do not match pinned feature schema")
    return PinnedModelPolicy(
        config=config,
        estimator=estimator,
        feature_columns=feature_columns,
        feature_schema=feature_schema,
        model_selection_report=report,
    )


def load_pinned_model_policy_from_settings(settings: Settings | None = None) -> PinnedModelPolicy:
    settings = settings or settings_from_env()
    if not settings.artifact_root:
        raise ArtifactLoadError("ALPHADB_ARTIFACT_ROOT is required")
    if not settings.current_mvp_artifact_config:
        raise ArtifactLoadError("ALPHADB_CURRENT_MVP_ARTIFACT_CONFIG is required")
    return load_pinned_model_policy(
        load_pinned_artifact_config(
            artifact_root=settings.artifact_root,
            config_path=settings.current_mvp_artifact_config,
        )
    )


def extract_feature_columns(feature_schema: Mapping[str, Any]) -> tuple[str, ...]:
    columns = feature_schema.get("feature_columns") or feature_schema.get("columns")
    if not isinstance(columns, list) or not columns:
        raise ArtifactLoadError("feature schema missing non-empty feature_columns")
    if any(not isinstance(column, str) or not column for column in columns):
        raise ArtifactLoadError("feature schema contains invalid feature column names")
    return tuple(columns)


def validate_selection_metadata(
    config: PinnedArtifactConfig,
    report: Mapping[str, Any],
) -> None:
    selected = report.get("selection")
    if isinstance(selected, Mapping) and isinstance(selected.get("selection"), Mapping):
        selected = selected["selection"]
    if not isinstance(selected, Mapping):
        selected = {}
    report_candidate = selected.get("candidate") or report.get("candidate")
    if report_candidate and str(report_candidate) != config.candidate:
        raise ArtifactLoadError(
            f"configured candidate {config.candidate!r} does not match report {report_candidate!r}"
        )
    report_offset = selected.get("decision_minute_offset") or report.get("decision_minute_offset")
    if report_offset is not None and int(report_offset) != config.decision_minute_offset:
        raise ArtifactLoadError("configured decision offset does not match model-selection report")
    if config.mode != "conditional":
        raise ArtifactLoadError(f"unsupported Current MVP mode: {config.mode!r}")
    if config.sizing != "fixed_dollars":
        raise ArtifactLoadError(f"unsupported Current MVP sizing: {config.sizing!r}")


def load_estimator(path: Path) -> tuple[object, tuple[str, ...] | None]:
    if path.suffix.lower() == ".json":
        payload = dict(load_json_or_yaml(path))
        if payload.get("type") != "constant_probability":
            raise ArtifactLoadError(f"unsupported JSON model artifact type: {payload.get('type')!r}")
        if "probability_yes" not in payload:
            raise ArtifactLoadError("constant_probability model missing probability_yes")
        features = payload.get("feature_columns")
        return payload, None if features is None else tuple(str(feature) for feature in features)
    try:
        artifact = joblib.load(path)
    except Exception as exc:
        raise ArtifactLoadError(f"model artifact could not be loaded: {path}: {exc}") from exc
    if isinstance(artifact, Mapping):
        estimator = artifact.get("estimator", artifact)
        features = artifact.get("feature_columns")
    else:
        estimator = artifact
        features = getattr(artifact, "feature_names_in_", None)
    return estimator, None if features is None else tuple(str(feature) for feature in features)


def register_loaded_model(
    *,
    database_url: str,
    policy: PinnedModelPolicy,
    series: str = "KXBTC15M",
) -> RegisteredModel:
    OperationalStateRepository(database_url).apply_migrations()
    return ModelRegistryRepository(database_url).register(
        policy.config.as_model_registration(series=series)
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status", help="Validate and show pinned artifact metadata")
    status.add_argument("--artifact-root", default=None)
    status.add_argument("--config", default=None)
    register = subparsers.add_parser("register-model", help="Register loaded model metadata")
    register.add_argument("--series", default="KXBTC15M")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    if args.command == "status":
        policy = load_pinned_model_policy(
            load_pinned_artifact_config(
                artifact_root=args.artifact_root or settings.artifact_root,
                config_path=args.config or settings.current_mvp_artifact_config,
            )
        )
        print(json.dumps(policy.as_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "register-model":
        policy = load_pinned_model_policy_from_settings(settings)
        model = register_loaded_model(
            database_url=settings.database_url,
            policy=policy,
            series=args.series,
        )
        print(json.dumps(model.as_dict(), indent=2, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")
