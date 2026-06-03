"""Offline settlement-state dataset builder."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphadb.artifacts import file_sha256
from alphadb.events.log import canonical_payload_hash
from alphadb.markets.spec import SettlementSpec
from alphadb.settlement.inputs import MarketSettlementMetadata, ensure_utc_datetime
from alphadb.settlement.state import (
    SETTLEMENT_STATE_ROW_SCHEMA_VERSION,
    SettlementStateRow,
    calculate_settlement_state_from_payloads,
)

SETTLEMENT_STATE_DATASET_SUMMARY_SCHEMA_VERSION = "settlement_state_dataset_summary.v1"
DEFAULT_SETTLEMENT_DATASET_ROOT = Path("artifacts/settlement-state")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SettlementDatasetMarketInput(StrictModel):
    market_metadata_payload: dict[str, Any]
    official_input_payload: dict[str, Any]
    decision_times_utc: tuple[datetime, ...]

    @field_validator("decision_times_utc")
    @classmethod
    def decision_times_must_be_utc(cls, values: tuple[datetime, ...]) -> tuple[datetime, ...]:
        return tuple(ensure_utc_datetime(value) for value in values)


class SettlementDatasetSummary(StrictModel):
    schema_version: Literal["settlement_state_dataset_summary.v1"] = (
        SETTLEMENT_STATE_DATASET_SUMMARY_SCHEMA_VERSION
    )
    dataset_id: str = Field(min_length=1)
    row_schema_version: Literal["settlement_state_row.v1"] = SETTLEMENT_STATE_ROW_SCHEMA_VERSION
    settlement_spec_version: str = Field(min_length=1)
    market_count: int = Field(ge=0)
    decision_row_count: int = Field(ge=0)
    valid_row_count: int = Field(ge=0)
    invalid_row_count: int = Field(ge=0)
    promotion_safe_row_count: int = Field(ge=0)
    tested_time_range_start_utc: datetime | None
    tested_time_range_end_utc: datetime | None
    source_ids: tuple[str, ...]
    source_versions: tuple[str, ...]
    source_statuses: tuple[str, ...]
    market_metadata_hashes: tuple[str, ...]
    official_input_hashes: tuple[str, ...]
    row_hashes: tuple[str, ...]
    quality_flag_counts: dict[str, int]
    exclusion_reasons: dict[str, int]
    generated_dataset_hash: str = Field(min_length=64, max_length=64)
    artifact_locations: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class SettlementDatasetBuildResult(StrictModel):
    rows: tuple[SettlementStateRow, ...]
    summary: SettlementDatasetSummary


def build_settlement_state_dataset(
    *,
    settlement_spec: SettlementSpec,
    dataset_id: str,
    market_inputs: Sequence[SettlementDatasetMarketInput],
    output_dir: str | Path | None = None,
) -> SettlementDatasetBuildResult:
    output_root = Path(output_dir) if output_dir is not None else DEFAULT_SETTLEMENT_DATASET_ROOT / dataset_id
    output_root.mkdir(parents=True, exist_ok=True)
    rows_path = output_root / "settlement_state_rows.jsonl"
    summary_path = output_root / "settlement_state_summary.json"

    rows: list[SettlementStateRow] = []
    market_tickers: set[str] = set()
    market_metadata_hashes: set[str] = set()
    official_input_hashes: set[str] = set()
    for market_input in market_inputs:
        metadata = MarketSettlementMetadata(**market_input.market_metadata_payload)
        market_tickers.add(metadata.market_ticker)
        market_metadata_hashes.add(canonical_payload_hash(market_input.market_metadata_payload))
        official_input_hashes.add(canonical_payload_hash(market_input.official_input_payload))
        for decision_time in market_input.decision_times_utc:
            rows.append(
                calculate_settlement_state_from_payloads(
                    settlement_spec=settlement_spec,
                    market_metadata_payload=market_input.market_metadata_payload,
                    official_input_payload=market_input.official_input_payload,
                    decision_time_utc=decision_time,
                )
            )

    write_rows_jsonl(rows_path, rows)
    summary = summarize_settlement_state_dataset(
        settlement_spec=settlement_spec,
        dataset_id=dataset_id,
        rows=rows,
        market_count=len(market_tickers),
        market_metadata_hashes=tuple(sorted(market_metadata_hashes)),
        official_input_hashes=tuple(sorted(official_input_hashes)),
        generated_dataset_hash=file_sha256(rows_path),
        rows_path=rows_path,
        summary_path=summary_path,
    )
    summary_path.write_text(
        json.dumps(summary.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return SettlementDatasetBuildResult(rows=tuple(rows), summary=summary)


def summarize_settlement_state_dataset(
    *,
    settlement_spec: SettlementSpec,
    dataset_id: str,
    rows: Sequence[SettlementStateRow],
    market_count: int,
    market_metadata_hashes: tuple[str, ...],
    official_input_hashes: tuple[str, ...],
    generated_dataset_hash: str,
    rows_path: Path,
    summary_path: Path,
) -> SettlementDatasetSummary:
    valid_row_count = sum(row.row_valid for row in rows)
    promotion_safe_row_count = sum(row.promotion_safe for row in rows)
    quality_flag_counts = Counter(
        flag for row in rows for flag in row.source_quality_flags
    )
    exclusion_reasons = Counter(
        row.invalid_reason or ",".join(row.source_quality_flags) or "unknown"
        for row in rows
        if not row.promotion_safe
    )
    decision_times = tuple(row.decision_time_utc for row in rows)
    return SettlementDatasetSummary(
        dataset_id=dataset_id,
        settlement_spec_version=settlement_spec.spec_version,
        market_count=market_count,
        decision_row_count=len(rows),
        valid_row_count=valid_row_count,
        invalid_row_count=len(rows) - valid_row_count,
        promotion_safe_row_count=promotion_safe_row_count,
        tested_time_range_start_utc=min(decision_times) if decision_times else None,
        tested_time_range_end_utc=max(decision_times) if decision_times else None,
        source_ids=unique_non_null(row.source_id for row in rows),
        source_versions=unique_non_null(row.source_version for row in rows),
        source_statuses=unique_non_null(row.source_status for row in rows),
        market_metadata_hashes=market_metadata_hashes,
        official_input_hashes=official_input_hashes,
        row_hashes=tuple(row.row_hash for row in rows),
        quality_flag_counts=dict(sorted(quality_flag_counts.items())),
        exclusion_reasons=dict(sorted(exclusion_reasons.items())),
        generated_dataset_hash=generated_dataset_hash,
        artifact_locations={
            "rows": public_artifact_location(rows_path),
            "summary": public_artifact_location(summary_path),
        },
    )


def write_rows_jsonl(path: Path, rows: Sequence[SettlementStateRow]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.as_dict(), sort_keys=True) + "\n")


def unique_non_null(values: Sequence[str | None] | Any) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values if value is not None}))


def public_artifact_location(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(Path.cwd().resolve()))
    except ValueError:
        return f"<external>/{resolved.name}"
