"""Artifact audit for KXBTC15M model evaluation reports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from alphadb.model_evaluation.io import TABULAR_SUFFIXES, file_sha256, load_json, load_tabular_rows

ArtifactType = Literal[
    "training_rows",
    "prediction_artifact",
    "model_artifact",
    "model_training_report",
    "model_selection_report",
    "live_paper_attribution",
    "legacy_backtest_report",
    "unknown",
]

EvidenceTrack = Literal["current_kxbtc15m", "legacy_exploratory", "unknown"]

COMPARABILITY_FIELDS = (
    "schema_version",
    "profile_version",
    "feature_version",
    "label_version",
    "backfill_code_version",
    "source_endpoint_version",
)


@dataclass(frozen=True)
class ArtifactAuditRecord:
    path: str
    artifact_type: ArtifactType
    evidence_track: EvidenceTrack
    sha256: str | None
    readable: bool
    row_count: int | None
    schema_version: str | None
    dataset_id: str | None
    dataset_contract_status: str
    promotion_grade_eligible: bool
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "artifact_type": self.artifact_type,
            "evidence_track": self.evidence_track,
            "sha256": self.sha256,
            "readable": self.readable,
            "row_count": self.row_count,
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "dataset_contract_status": self.dataset_contract_status,
            "promotion_grade_eligible": self.promotion_grade_eligible,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ArtifactAuditReport:
    series: str
    artifact_root: str
    records: tuple[ArtifactAuditRecord, ...]

    def as_dict(self) -> dict[str, Any]:
        current = [record for record in self.records if record.evidence_track == "current_kxbtc15m"]
        legacy = [record for record in self.records if record.evidence_track == "legacy_exploratory"]
        promotion_grade = [record for record in self.records if record.promotion_grade_eligible]
        return {
            "schema_version": "model_artifact_audit_v1",
            "series": self.series,
            "artifact_root": self.artifact_root,
            "counts": {
                "total": len(self.records),
                "current_kxbtc15m": len(current),
                "legacy_exploratory": len(legacy),
                "promotion_grade_eligible": len(promotion_grade),
            },
            "records": [record.as_dict() for record in self.records],
        }


def audit_model_artifacts(
    artifact_root: str | Path,
    *,
    series: str = "KXBTC15M",
) -> ArtifactAuditReport:
    root = Path(artifact_root).expanduser().resolve()
    records = tuple(
        audit_artifact(path, root=root, series=series)
        for path in discover_model_artifact_paths(root, series=series)
    )
    return ArtifactAuditReport(series=series, artifact_root=str(root), records=records)


def discover_model_artifact_paths(root: Path, *, series: str = "KXBTC15M") -> list[Path]:
    if not root.exists():
        return []
    candidates: list[Path] = []
    patterns = [
        f"**/*{series}*training_rows*.parquet",
        f"**/*{series}*training_rows*.json",
        "**/*_kxbtc_model_training_*/metrics.json",
        "**/*_kxbtc_model_training_*/feature_schema.json",
        "**/*_kxbtc_model_training_*/predictions.*",
        "**/*_kxbtc_model_training_*/model_*.joblib",
        "**/*_kxbtc_model_selection_report/metrics.json",
        "**/*_KXBTC15M_live_attribution_report/report.json",
        "**/*_backtest/metrics.json",
    ]
    for pattern in patterns:
        candidates.extend(root.glob(pattern))
    return sorted({path.resolve() for path in candidates if path.is_file()})


def audit_artifact(path: Path, *, root: Path, series: str) -> ArtifactAuditRecord:
    relative = safe_relative(path, root)
    artifact_type = classify_artifact(path)
    evidence_track = classify_evidence_track(path, artifact_type)
    notes: list[str] = []
    sha256 = file_sha256(path)
    readable = False
    row_count: int | None = None
    schema_version: str | None = None
    dataset_id: str | None = None
    dataset_contract_status = "not_applicable"

    try:
        metadata = artifact_metadata(path, artifact_type)
        readable = True
        row_count = metadata.get("row_count")
        schema_version = metadata.get("schema_version")
        dataset_id = metadata.get("dataset_id")
        dataset_contract_status = metadata.get("dataset_contract_status", dataset_contract_status)
        notes.extend(metadata.get("notes", ()))
    except Exception as exc:
        notes.append(f"metadata_unreadable:{exc.__class__.__name__}")
        if path.suffix.lower() == ".joblib":
            notes.append("model_binary_not_loaded_by_audit")
        else:
            dataset_contract_status = "unknown_unreadable"

    if evidence_track == "legacy_exploratory":
        notes.append("legacy_exploratory_not_current_deployable_evidence")
    if artifact_type in {"training_rows", "prediction_artifact"} and dataset_contract_status != "complete":
        notes.append("missing_or_incomplete_dataset_contract")

    promotion_grade_eligible = (
        evidence_track == "current_kxbtc15m"
        and artifact_type
        in {
            "training_rows",
            "prediction_artifact",
            "model_training_report",
            "model_selection_report",
            "live_paper_attribution",
        }
        and dataset_contract_status in {"complete", "not_applicable"}
        and readable
    )
    return ArtifactAuditRecord(
        path=relative,
        artifact_type=artifact_type,
        evidence_track=evidence_track,
        sha256=sha256,
        readable=readable,
        row_count=row_count,
        schema_version=schema_version,
        dataset_id=dataset_id,
        dataset_contract_status=dataset_contract_status,
        promotion_grade_eligible=promotion_grade_eligible,
        notes=tuple(notes),
    )


def artifact_metadata(path: Path, artifact_type: ArtifactType) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".joblib":
        return {"notes": ("hash_only_model_binary",), "dataset_contract_status": "not_applicable"}
    if path.name.endswith(".manifest.json"):
        return metadata_from_mapping(load_json(path))
    if suffix == ".json" and artifact_type not in {"training_rows", "prediction_artifact"}:
        payload = load_json(path)
        return metadata_from_mapping(payload)
    if suffix in TABULAR_SUFFIXES:
        rows = load_tabular_rows(path)
        return metadata_from_rows(rows)
    return {"notes": (f"unhandled_suffix:{path.suffix}",)}


def metadata_from_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    dataset_contract = payload.get("dataset_contract")
    metadata = {
        "row_count": int(payload["row_count"]) if "row_count" in payload else None,
        "schema_version": optional_string(payload.get("schema_version")),
        "dataset_id": optional_string(payload.get("dataset_id")),
        "dataset_contract_status": "not_applicable",
        "notes": (),
    }
    if isinstance(dataset_contract, Mapping):
        metadata["dataset_id"] = optional_string(dataset_contract.get("dataset_id"))
        metadata["dataset_contract_status"] = dataset_contract_status(dataset_contract)
    return metadata


def metadata_from_rows(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    first = rows[0] if rows else {}
    return {
        "row_count": len(rows),
        "schema_version": single_value(rows, "schema_version") or optional_string(first.get("schema_version")),
        "dataset_id": single_value(rows, "dataset_id") or optional_string(first.get("dataset_id")),
        "dataset_contract_status": dataset_contract_status(first),
        "notes": (),
    }


def dataset_contract_status(values: Mapping[str, Any]) -> str:
    missing = [field for field in COMPARABILITY_FIELDS if not values.get(field)]
    if not missing:
        return "complete"
    present = [field for field in COMPARABILITY_FIELDS if values.get(field)]
    if present:
        return "incomplete"
    return "missing"


def single_value(rows: Iterable[Mapping[str, Any]], key: str) -> str | None:
    values = {str(row[key]) for row in rows if row.get(key) not in (None, "")}
    if len(values) == 1:
        return next(iter(values))
    return None


def optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def classify_artifact(path: Path) -> ArtifactType:
    text = str(path)
    name = path.name
    parent = path.parent.name
    if "training_rows" in name:
        return "training_rows"
    if name.startswith("predictions."):
        return "prediction_artifact"
    if name.startswith("model_") and path.suffix == ".joblib":
        return "model_artifact"
    if "_kxbtc_model_training_" in text and name == "metrics.json":
        return "model_training_report"
    if "_kxbtc_model_selection_report" in text and name == "metrics.json":
        return "model_selection_report"
    if "_live_attribution_report" in text and name == "report.json":
        return "live_paper_attribution"
    if parent.endswith("_backtest") and name == "metrics.json":
        return "legacy_backtest_report"
    return "unknown"


def classify_evidence_track(path: Path, artifact_type: ArtifactType) -> EvidenceTrack:
    text = str(path)
    if "_backtest" in text and artifact_type == "legacy_backtest_report":
        return "legacy_exploratory"
    if artifact_type in {
        "training_rows",
        "prediction_artifact",
        "model_artifact",
        "model_training_report",
        "model_selection_report",
        "live_paper_attribution",
    }:
        return "current_kxbtc15m"
    return "unknown"


def safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
