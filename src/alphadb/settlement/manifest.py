"""Public-safe settlement-state readiness manifests."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from alphadb.events.log import canonical_payload_hash
from alphadb.settlement.dataset import SettlementDatasetSummary, public_artifact_location

SETTLEMENT_STATE_MANIFEST_SCHEMA_VERSION = "settlement_state_manifest.v1"
ReadinessVerdict = Literal["PASS", "FAIL", "INCONCLUSIVE"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SettlementReadinessManifest(StrictModel):
    schema_version: Literal["settlement_state_manifest.v1"] = (
        SETTLEMENT_STATE_MANIFEST_SCHEMA_VERSION
    )
    dataset_id: str = Field(min_length=1)
    row_schema_version: str = Field(min_length=1)
    summary_schema_version: str = Field(min_length=1)
    code_version: str = Field(min_length=1)
    settlement_spec_version: str = Field(min_length=1)
    tested_time_range_start_utc: str | None
    tested_time_range_end_utc: str | None
    market_count: int = Field(ge=0)
    decision_row_count: int = Field(ge=0)
    valid_row_count: int = Field(ge=0)
    invalid_row_count: int = Field(ge=0)
    promotion_safe_row_count: int = Field(ge=0)
    source_ids: tuple[str, ...]
    source_versions: tuple[str, ...]
    official_input_statuses: tuple[str, ...]
    exclusion_reasons: dict[str, int]
    quality_flag_counts: dict[str, int]
    input_hashes: dict[str, tuple[str, ...]]
    generated_dataset_hash: str = Field(min_length=64, max_length=64)
    artifact_locations: dict[str, str]
    readiness_verdict: ReadinessVerdict
    readiness_reasons: tuple[str, ...]
    public_safety_notes: tuple[str, ...]
    manifest_hash: str

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def build_settlement_readiness_manifest(
    *,
    summary: SettlementDatasetSummary,
    artifact_locations: dict[str, str] | None = None,
) -> SettlementReadinessManifest:
    verdict, reasons = evaluate_readiness_verdict(summary)
    locations = dict(summary.artifact_locations)
    if artifact_locations is not None:
        locations.update(artifact_locations)
    payload = {
        "schema_version": SETTLEMENT_STATE_MANIFEST_SCHEMA_VERSION,
        "dataset_id": summary.dataset_id,
        "row_schema_version": summary.row_schema_version,
        "summary_schema_version": summary.schema_version,
        "code_version": alphadb_code_version(),
        "settlement_spec_version": summary.settlement_spec_version,
        "tested_time_range_start_utc": (
            summary.tested_time_range_start_utc.isoformat()
            if summary.tested_time_range_start_utc is not None
            else None
        ),
        "tested_time_range_end_utc": (
            summary.tested_time_range_end_utc.isoformat()
            if summary.tested_time_range_end_utc is not None
            else None
        ),
        "market_count": summary.market_count,
        "decision_row_count": summary.decision_row_count,
        "valid_row_count": summary.valid_row_count,
        "invalid_row_count": summary.invalid_row_count,
        "promotion_safe_row_count": summary.promotion_safe_row_count,
        "source_ids": summary.source_ids,
        "source_versions": summary.source_versions,
        "official_input_statuses": summary.source_statuses,
        "exclusion_reasons": summary.exclusion_reasons,
        "quality_flag_counts": summary.quality_flag_counts,
        "input_hashes": {
            "market_metadata": summary.market_metadata_hashes,
            "official_settlement_input": summary.official_input_hashes,
        },
        "generated_dataset_hash": summary.generated_dataset_hash,
        "artifact_locations": locations,
        "readiness_verdict": verdict,
        "readiness_reasons": reasons,
        "public_safety_notes": public_safety_notes(),
    }
    return SettlementReadinessManifest(
        **payload,
        manifest_hash=canonical_payload_hash(payload),
    )


def write_settlement_readiness_manifest(
    *,
    summary: SettlementDatasetSummary,
    output_path: str | Path,
) -> SettlementReadinessManifest:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_settlement_readiness_manifest(
        summary=summary,
        artifact_locations={"manifest": public_artifact_location(path)},
    )
    path.write_text(
        json.dumps(manifest.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def evaluate_readiness_verdict(
    summary: SettlementDatasetSummary,
) -> tuple[ReadinessVerdict, tuple[str, ...]]:
    reasons: list[str] = []
    if summary.market_count == 0 or summary.decision_row_count == 0:
        reasons.append("insufficient_coverage")
        return "INCONCLUSIVE", tuple(reasons)

    non_rule_quality_failures = {
        flag: count
        for flag, count in summary.quality_flag_counts.items()
        if flag != "ambiguous_market_metadata" and count > 0
    }
    if non_rule_quality_failures:
        reasons.extend(f"{flag}:{count}" for flag, count in sorted(non_rule_quality_failures.items()))
        return "FAIL", tuple(reasons)

    if summary.invalid_row_count > 0:
        reasons.append("ambiguous_rule_or_metadata")
        return "INCONCLUSIVE", tuple(reasons)

    if summary.source_statuses != ("official_licensed",):
        reasons.append("official_licensed_source_required_for_promotion_grade_readiness")
        return "INCONCLUSIVE", tuple(reasons)

    reasons.append("all_rows_valid_with_official_licensed_source")
    return "PASS", tuple(reasons)


def public_safety_notes() -> tuple[str, ...]:
    return (
        "Manifest records hashes, counts, statuses, verdicts, and artifact references only.",
        "Raw official settlement prints and full generated datasets remain outside Git.",
        "Synthetic readiness output is not a strategy promotion decision and does not imply H1/H2/H3 results.",
    )


def alphadb_code_version() -> str:
    try:
        return version("alphadb")
    except PackageNotFoundError:
        return "0.1.0"
