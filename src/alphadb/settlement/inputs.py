"""Normalized official settlement input contracts."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator

from alphadb.events.log import canonical_payload_hash
from alphadb.markets.spec import PayoutComparator, SettlementSpec

SETTLEMENT_INPUT_SCHEMA_VERSION = "normalized_official_settlement_input.v1"
MARKET_SETTLEMENT_METADATA_SCHEMA_VERSION = "market_settlement_metadata.v1"

SettlementSourceStatus = Literal["official_licensed", "official_unlicensed", "synthetic_fixture"]
SettlementLicenseStatus = Literal["licensed", "unlicensed", "synthetic"]


class SettlementInputValidationError(ValueError):
    """Raised when normalized settlement input cannot satisfy the contract."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def ensure_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def validate_positive_decimal(value: Decimal, *, label: str) -> None:
    if value <= Decimal("0"):
        raise ValueError(f"{label} must be positive")


def threshold_count_for_comparator(comparator: PayoutComparator) -> int:
    return 2 if comparator == "between" else 1


class SettlementInputSource(StrictModel):
    source_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_status: SettlementSourceStatus
    license_status: SettlementLicenseStatus
    index_ticker: str = Field(min_length=1)
    source_uri: str | None = Field(default=None, min_length=1)
    source_bundle_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    max_observation_lag_seconds: PositiveInt | None = None

    @model_validator(mode="after")
    def validate_source_status(self) -> SettlementInputSource:
        if self.source_status == "synthetic_fixture":
            if self.license_status != "synthetic":
                raise ValueError("synthetic fixtures must use synthetic license status")
            if self.source_uri is not None or self.source_bundle_sha256 is not None:
                raise ValueError("synthetic fixtures must not reference private source artifacts")
        if self.source_status.startswith("official") and self.license_status == "synthetic":
            raise ValueError("official settlement input must not use synthetic license status")
        return self


class OfficialSettlementPrint(StrictModel):
    index_ticker: str = Field(min_length=1)
    effective_time_utc: datetime
    observed_value: Decimal
    loaded_at_utc: datetime
    source_event_id: str | None = Field(default=None, min_length=1)

    @field_validator("effective_time_utc", "loaded_at_utc")
    @classmethod
    def timestamps_must_be_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def validate_print(self) -> OfficialSettlementPrint:
        validate_positive_decimal(self.observed_value, label="observed_value")
        if self.loaded_at_utc < self.effective_time_utc:
            raise ValueError("loaded_at_utc must not be before effective_time_utc")
        return self


class MarketSettlementMetadata(StrictModel):
    schema_version: Literal["market_settlement_metadata.v1"] = MARKET_SETTLEMENT_METADATA_SCHEMA_VERSION
    market_ticker: str = Field(min_length=1)
    series: str = Field(min_length=1)
    index_ticker: str = Field(min_length=1)
    comparator: PayoutComparator
    thresholds: tuple[Decimal, ...]
    threshold_precision: int = Field(ge=0)
    expiration_time_utc: datetime
    metadata_source_id: str = Field(min_length=1)
    metadata_source_version: str = Field(min_length=1)

    @field_validator("expiration_time_utc")
    @classmethod
    def expiration_time_must_be_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def validate_metadata(self) -> MarketSettlementMetadata:
        expected_thresholds = threshold_count_for_comparator(self.comparator)
        if len(self.thresholds) != expected_thresholds:
            raise ValueError("threshold count does not match payout comparator")
        for threshold in self.thresholds:
            validate_positive_decimal(threshold, label="threshold")
        if self.comparator == "between" and self.thresholds[0] > self.thresholds[1]:
            raise ValueError("between thresholds must be ordered low to high")
        return self

    def content_hash(self) -> str:
        return canonical_payload_hash(self.model_dump(mode="json"))


class NormalizedOfficialSettlementInput(StrictModel):
    schema_version: Literal["normalized_official_settlement_input.v1"] = (
        SETTLEMENT_INPUT_SCHEMA_VERSION
    )
    source: SettlementInputSource
    prints: tuple[OfficialSettlementPrint, ...]
    created_at_utc: datetime

    @field_validator("created_at_utc")
    @classmethod
    def created_at_must_be_utc(cls, value: datetime) -> datetime:
        return ensure_utc_datetime(value)

    @model_validator(mode="after")
    def validate_bundle(self) -> NormalizedOfficialSettlementInput:
        if not self.prints:
            raise ValueError("official settlement input must include at least one print")

        effective_times: list[datetime] = []
        source_event_ids: list[str] = []
        previous_time: datetime | None = None
        for official_print in self.prints:
            if official_print.index_ticker != self.source.index_ticker:
                raise ValueError("print index_ticker must match source index_ticker")
            if previous_time is not None and official_print.effective_time_utc <= previous_time:
                raise ValueError("prints must be strictly ordered by effective_time_utc")
            previous_time = official_print.effective_time_utc
            effective_times.append(official_print.effective_time_utc)
            if official_print.source_event_id is not None:
                source_event_ids.append(official_print.source_event_id)
            if self.source.max_observation_lag_seconds is not None:
                lag = official_print.loaded_at_utc - official_print.effective_time_utc
                if lag > timedelta(seconds=self.source.max_observation_lag_seconds):
                    raise ValueError("print loaded_at_utc exceeds max observation lag")

        if len(effective_times) != len(set(effective_times)):
            raise ValueError("duplicate effective_time_utc values are not allowed")
        if len(source_event_ids) != len(set(source_event_ids)):
            raise ValueError("duplicate source_event_id values are not allowed")
        return self

    def content_hash(self) -> str:
        return canonical_payload_hash(self.model_dump(mode="json"))


def expected_final_window_times(
    *,
    expiration_time_utc: datetime,
    settlement_spec: SettlementSpec,
) -> tuple[datetime, ...]:
    expiration_time_utc = ensure_utc_datetime(expiration_time_utc)
    window = settlement_spec.final_settlement_window
    start = expiration_time_utc - timedelta(seconds=window.duration_seconds)
    return tuple(
        start + timedelta(seconds=window.cadence_seconds * offset)
        for offset in range(window.expected_print_count)
    )


def validated_final_window_prints(
    *,
    metadata: MarketSettlementMetadata,
    official_input: NormalizedOfficialSettlementInput,
    settlement_spec: SettlementSpec,
) -> tuple[OfficialSettlementPrint, ...]:
    if metadata.series != settlement_spec.market_series:
        raise SettlementInputValidationError("market metadata series does not match settlement spec")
    if metadata.index_ticker != settlement_spec.official_input_source.index_ticker:
        raise SettlementInputValidationError("market metadata index ticker does not match spec")
    if official_input.source.index_ticker != settlement_spec.official_input_source.index_ticker:
        raise SettlementInputValidationError("official input index ticker does not match spec")

    allowed_comparators = {rule.comparator for rule in settlement_spec.payout_comparator_rules}
    if metadata.comparator not in allowed_comparators:
        raise SettlementInputValidationError("market comparator is not allowed by settlement spec")
    validate_market_thresholds(metadata=metadata, settlement_spec=settlement_spec)

    expected_times = expected_final_window_times(
        expiration_time_utc=metadata.expiration_time_utc,
        settlement_spec=settlement_spec,
    )
    prints_by_time = {official_print.effective_time_utc: official_print for official_print in official_input.prints}
    missing = [timestamp for timestamp in expected_times if timestamp not in prints_by_time]
    if missing:
        raise SettlementInputValidationError(
            f"missing {len(missing)} final-window official settlement prints"
        )
    return tuple(prints_by_time[timestamp] for timestamp in expected_times)


def validate_market_thresholds(
    *,
    metadata: MarketSettlementMetadata,
    settlement_spec: SettlementSpec,
) -> None:
    comparator_rules = {
        rule.comparator: rule for rule in settlement_spec.payout_comparator_rules
    }
    rule = comparator_rules[metadata.comparator]
    if len(metadata.thresholds) != rule.threshold_count:
        raise SettlementInputValidationError(
            "market threshold count does not match settlement comparator rule"
        )


def has_private_source_reference(source: SettlementInputSource) -> bool:
    return source.source_uri is not None or source.source_bundle_sha256 is not None


def source_event_ids(prints: Sequence[OfficialSettlementPrint]) -> tuple[str, ...]:
    return tuple(
        official_print.source_event_id
        for official_print in prints
        if official_print.source_event_id is not None
    )
