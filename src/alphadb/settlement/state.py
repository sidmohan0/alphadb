"""Pure settlement-state calculator."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from alphadb.events.log import canonical_payload_hash
from alphadb.markets.spec import PayoutComparator, SettlementSpec
from alphadb.settlement.inputs import (
    MarketSettlementMetadata,
    NormalizedOfficialSettlementInput,
    OfficialSettlementPrint,
    SettlementInputValidationError,
    ensure_utc_datetime,
    expected_final_window_times,
    source_event_ids,
    validate_market_thresholds,
)

SETTLEMENT_STATE_ROW_SCHEMA_VERSION = "settlement_state_row.v1"

SettlementStateQualityFlag = Literal[
    "missing_prints",
    "duplicate_timestamps",
    "incomplete_window",
    "stale_source_timestamp",
    "future_effective_timestamp",
    "wrong_index_ticker",
    "ambiguous_market_metadata",
    "source_timestamp_after_decision",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SettlementStateRow(StrictModel):
    schema_version: Literal["settlement_state_row.v1"] = SETTLEMENT_STATE_ROW_SCHEMA_VERSION
    market_ticker: str = Field(min_length=1)
    series: str = Field(min_length=1)
    index_ticker: str = Field(min_length=1)
    decision_time_utc: datetime
    expiration_time_utc: datetime
    payout_comparator: PayoutComparator
    payout_thresholds: tuple[Decimal, ...]
    threshold_precision: int = Field(ge=0)
    final_window_start_utc: datetime
    final_window_end_utc: datetime
    locked_count: int = Field(ge=0)
    locked_sum: Decimal
    locked_average: Decimal | None
    remaining_count: int = Field(ge=0)
    expected_print_count: int = Field(ge=0)
    source_quality_flags: tuple[SettlementStateQualityFlag, ...]
    row_valid: bool
    promotion_safe: bool
    invalid_reason: str | None
    max_source_event_timestamp_utc: datetime | None
    source_lag_seconds: int | None
    source_id: str | None
    source_version: str | None
    source_status: str | None
    metadata_source_id: str = Field(min_length=1)
    metadata_source_version: str = Field(min_length=1)
    source_event_ids: tuple[str, ...]
    locked_prints_hash: str
    market_metadata_hash: str
    row_hash: str

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def calculate_settlement_state(
    *,
    settlement_spec: SettlementSpec,
    metadata: MarketSettlementMetadata,
    official_input: NormalizedOfficialSettlementInput,
    decision_time_utc: datetime,
) -> SettlementStateRow:
    decision_time_utc = ensure_utc_datetime(decision_time_utc)
    expected_times = expected_final_window_times(
        expiration_time_utc=metadata.expiration_time_utc,
        settlement_spec=settlement_spec,
    )
    required_times = expected_locked_times(
        decision_time_utc=decision_time_utc,
        expected_times=expected_times,
    )
    validation_flags = validate_settlement_state_inputs(
        settlement_spec=settlement_spec,
        metadata=metadata,
        official_input=official_input,
    )
    prints_by_time = {official_print.effective_time_utc: official_print for official_print in official_input.prints}
    missing_times = tuple(timestamp for timestamp in required_times if timestamp not in prints_by_time)
    locked_prints = tuple(
        prints_by_time[timestamp] for timestamp in required_times if timestamp in prints_by_time
    )

    flags: list[SettlementStateQualityFlag] = list(validation_flags)
    reason_parts: list[str] = []
    if "ambiguous_market_metadata" in flags:
        reason_parts.append("ambiguous_market_metadata")
    if missing_times:
        flags.append("missing_prints")
        reason_parts.append(f"missing_prints:{len(missing_times)}")
    if decision_time_utc >= metadata.expiration_time_utc and len(locked_prints) < len(expected_times):
        flags.append("incomplete_window")
        reason_parts.append(
            f"incomplete_window:{len(locked_prints)}/{len(expected_times)}"
        )

    max_source_event_timestamp = max(
        (official_print.effective_time_utc for official_print in locked_prints),
        default=None,
    )
    if max_source_event_timestamp is not None and max_source_event_timestamp > decision_time_utc:
        flags.append("source_timestamp_after_decision")
        reason_parts.append("source_timestamp_after_decision")
    source_lag_seconds = (
        int((decision_time_utc - max_source_event_timestamp).total_seconds())
        if max_source_event_timestamp is not None
        else None
    )

    locked_sum = sum((official_print.observed_value for official_print in locked_prints), Decimal("0"))
    locked_average = locked_sum / Decimal(len(locked_prints)) if locked_prints else None
    ordered_flags = ordered_quality_flags(flags)
    row_valid = not ordered_flags
    return build_settlement_state_row(
        metadata=metadata,
        decision_time_utc=decision_time_utc,
        expected_times=expected_times,
        required_times=required_times,
        locked_prints=locked_prints,
        locked_sum=locked_sum,
        locked_average=locked_average,
        source_quality_flags=ordered_flags,
        row_valid=row_valid,
        invalid_reason=";".join(reason_parts) if reason_parts else None,
        max_source_event_timestamp=max_source_event_timestamp,
        source_lag_seconds=source_lag_seconds,
        source_id=official_input.source.source_id,
        source_version=official_input.source.source_version,
        source_status=official_input.source.source_status,
    )


def calculate_settlement_state_from_payloads(
    *,
    settlement_spec: SettlementSpec,
    market_metadata_payload: Mapping[str, Any],
    official_input_payload: Mapping[str, Any],
    decision_time_utc: datetime,
) -> SettlementStateRow:
    metadata = MarketSettlementMetadata(**market_metadata_payload)
    try:
        official_input = NormalizedOfficialSettlementInput(**official_input_payload)
    except ValidationError as exc:
        return invalid_payload_settlement_state_row(
            settlement_spec=settlement_spec,
            metadata=metadata,
            official_input_payload=official_input_payload,
            decision_time_utc=decision_time_utc,
            validation_error=exc,
        )

    return calculate_settlement_state(
        settlement_spec=settlement_spec,
        metadata=metadata,
        official_input=official_input,
        decision_time_utc=decision_time_utc,
    )


def expected_locked_times(
    *,
    decision_time_utc: datetime,
    expected_times: Sequence[datetime],
) -> tuple[datetime, ...]:
    decision_time_utc = ensure_utc_datetime(decision_time_utc)
    return tuple(timestamp for timestamp in expected_times if timestamp <= decision_time_utc)


def validate_settlement_state_inputs(
    *,
    settlement_spec: SettlementSpec,
    metadata: MarketSettlementMetadata,
    official_input: NormalizedOfficialSettlementInput,
) -> tuple[SettlementStateQualityFlag, ...]:
    flags: list[SettlementStateQualityFlag] = []
    try:
        if metadata.series != settlement_spec.market_series:
            raise SettlementInputValidationError("market metadata series does not match spec")
        if metadata.index_ticker != settlement_spec.official_input_source.index_ticker:
            raise SettlementInputValidationError("market metadata index ticker does not match spec")
        if official_input.source.index_ticker != settlement_spec.official_input_source.index_ticker:
            raise SettlementInputValidationError("official input index ticker does not match spec")
        allowed_comparators = {rule.comparator for rule in settlement_spec.payout_comparator_rules}
        if metadata.comparator not in allowed_comparators:
            raise SettlementInputValidationError("market comparator is not allowed by spec")
        if settlement_spec.payout_threshold_rule.verification_status != "confirmed":
            raise SettlementInputValidationError("payout threshold rule is not confirmed")
        validate_market_thresholds(metadata=metadata, settlement_spec=settlement_spec)
    except SettlementInputValidationError:
        flags.append("ambiguous_market_metadata")
    return tuple(flags)


def invalid_payload_settlement_state_row(
    *,
    settlement_spec: SettlementSpec,
    metadata: MarketSettlementMetadata,
    official_input_payload: Mapping[str, Any],
    decision_time_utc: datetime,
    validation_error: ValidationError,
) -> SettlementStateRow:
    decision_time_utc = ensure_utc_datetime(decision_time_utc)
    expected_times = expected_final_window_times(
        expiration_time_utc=metadata.expiration_time_utc,
        settlement_spec=settlement_spec,
    )
    required_times = expected_locked_times(
        decision_time_utc=decision_time_utc,
        expected_times=expected_times,
    )
    flags = ordered_quality_flags(flags_from_validation_error(validation_error))
    source_payload = official_input_payload.get("source", {})
    if not isinstance(source_payload, Mapping):
        source_payload = {}
    return build_settlement_state_row(
        metadata=metadata,
        decision_time_utc=decision_time_utc,
        expected_times=expected_times,
        required_times=required_times,
        locked_prints=(),
        locked_sum=Decimal("0"),
        locked_average=None,
        source_quality_flags=flags,
        row_valid=False,
        invalid_reason=f"invalid_official_input:{','.join(flags)}",
        max_source_event_timestamp=None,
        source_lag_seconds=None,
        source_id=optional_string(source_payload.get("source_id")),
        source_version=optional_string(source_payload.get("source_version")),
        source_status=optional_string(source_payload.get("source_status")),
    )


def build_settlement_state_row(
    *,
    metadata: MarketSettlementMetadata,
    decision_time_utc: datetime,
    expected_times: Sequence[datetime],
    required_times: Sequence[datetime],
    locked_prints: Sequence[OfficialSettlementPrint],
    locked_sum: Decimal,
    locked_average: Decimal | None,
    source_quality_flags: tuple[SettlementStateQualityFlag, ...],
    row_valid: bool,
    invalid_reason: str | None,
    max_source_event_timestamp: datetime | None,
    source_lag_seconds: int | None,
    source_id: str | None,
    source_version: str | None,
    source_status: str | None,
) -> SettlementStateRow:
    locked_prints_hash = canonical_payload_hash(
        {
            "prints": [
                official_print.model_dump(mode="json") for official_print in locked_prints
            ]
        }
    )
    payload = {
        "schema_version": SETTLEMENT_STATE_ROW_SCHEMA_VERSION,
        "market_ticker": metadata.market_ticker,
        "series": metadata.series,
        "index_ticker": metadata.index_ticker,
        "decision_time_utc": decision_time_utc,
        "expiration_time_utc": metadata.expiration_time_utc,
        "payout_comparator": metadata.comparator,
        "payout_thresholds": metadata.thresholds,
        "threshold_precision": metadata.threshold_precision,
        "final_window_start_utc": expected_times[0],
        "final_window_end_utc": metadata.expiration_time_utc,
        "locked_count": len(locked_prints),
        "locked_sum": locked_sum,
        "locked_average": locked_average,
        "remaining_count": len(expected_times) - len(required_times),
        "expected_print_count": len(expected_times),
        "source_quality_flags": source_quality_flags,
        "row_valid": row_valid,
        "promotion_safe": row_valid,
        "invalid_reason": invalid_reason,
        "max_source_event_timestamp_utc": max_source_event_timestamp,
        "source_lag_seconds": source_lag_seconds,
        "source_id": source_id,
        "source_version": source_version,
        "source_status": source_status,
        "metadata_source_id": metadata.metadata_source_id,
        "metadata_source_version": metadata.metadata_source_version,
        "source_event_ids": source_event_ids(locked_prints),
        "locked_prints_hash": locked_prints_hash,
        "market_metadata_hash": metadata.content_hash(),
    }
    return SettlementStateRow(
        **payload,
        row_hash=canonical_payload_hash(json_ready_payload(payload)),
    )


def flags_from_validation_error(error: ValidationError) -> tuple[SettlementStateQualityFlag, ...]:
    message = str(error).lower()
    flags: list[SettlementStateQualityFlag] = []
    if "strictly ordered" in message or "duplicate" in message:
        flags.append("duplicate_timestamps")
    if "max observation lag" in message:
        flags.append("stale_source_timestamp")
    if "loaded_at_utc" in message or "before effective_time" in message:
        flags.append("future_effective_timestamp")
    if "index_ticker" in message:
        flags.append("wrong_index_ticker")
    if "at least one print" in message:
        flags.append("missing_prints")
    return tuple(flags or ["ambiguous_market_metadata"])


def ordered_quality_flags(
    flags: Sequence[SettlementStateQualityFlag],
) -> tuple[SettlementStateQualityFlag, ...]:
    order: tuple[SettlementStateQualityFlag, ...] = (
        "ambiguous_market_metadata",
        "missing_prints",
        "duplicate_timestamps",
        "incomplete_window",
        "stale_source_timestamp",
        "future_effective_timestamp",
        "wrong_index_ticker",
        "source_timestamp_after_decision",
    )
    present = set(flags)
    return tuple(flag for flag in order if flag in present)


def optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def json_ready_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return SettlementStateRow(**payload, row_hash="").model_dump(
        mode="json",
        exclude={"row_hash"},
    )
