"""Public synthetic settlement input fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from alphadb.markets.spec import PayoutComparator
from alphadb.settlement.inputs import (
    MARKET_SETTLEMENT_METADATA_SCHEMA_VERSION,
    SETTLEMENT_INPUT_SCHEMA_VERSION,
)

KXBTC15M_SYNTHETIC_EXPIRATION = datetime(2026, 6, 1, 12, 15, tzinfo=UTC)
KXBTC15M_SYNTHETIC_SOURCE_ID = "synthetic.cf-brti.kxbtc15m"
KXBTC15M_SYNTHETIC_SOURCE_VERSION = "synthetic.v1"


@dataclass(frozen=True)
class SyntheticSettlementFixtureCase:
    name: str
    description: str
    market_metadata_payload: dict[str, Any]
    official_input_payload: dict[str, Any]
    decision_times_utc: tuple[datetime, ...]
    expected_input_valid: bool
    expected_window_valid: bool


def kxbtc15m_synthetic_fixture_suite() -> dict[str, SyntheticSettlementFixtureCase]:
    clean_prints = synthetic_print_payloads()
    return {
        "clean_above": synthetic_case(
            name="clean_above",
            description="Clean final window with a listed above threshold.",
            comparator="above",
            thresholds=(Decimal("100000.00"),),
            prints=clean_prints,
        ),
        "clean_below": synthetic_case(
            name="clean_below",
            description="Clean final window with a listed below threshold.",
            comparator="below",
            thresholds=(Decimal("100000.00"),),
            prints=clean_prints,
        ),
        "clean_exactly": synthetic_case(
            name="clean_exactly",
            description="Clean final window with an exact-threshold comparator.",
            comparator="exactly",
            thresholds=(Decimal("100000.00"),),
            prints=clean_prints,
        ),
        "clean_at_least": synthetic_case(
            name="clean_at_least",
            description="Clean final window with an inclusive at-least comparator.",
            comparator="at_least",
            thresholds=(Decimal("100000.00"),),
            prints=clean_prints,
        ),
        "clean_between": synthetic_case(
            name="clean_between",
            description="Clean final window with inclusive between thresholds.",
            comparator="between",
            thresholds=(Decimal("99990.00"), Decimal("100010.00")),
            prints=clean_prints,
        ),
        "missing_print": synthetic_case(
            name="missing_print",
            description="Final window is missing one expected official print.",
            comparator="above",
            thresholds=(Decimal("100000.00"),),
            prints=without_print(clean_prints, offset=10),
            expected_window_valid=False,
        ),
        "duplicate_timestamp": synthetic_case(
            name="duplicate_timestamp",
            description="Official input contains a duplicate effective timestamp.",
            comparator="above",
            thresholds=(Decimal("100000.00"),),
            prints=with_duplicate_print(clean_prints, offset=10),
            expected_input_valid=False,
            expected_window_valid=False,
        ),
        "incomplete_window": synthetic_case(
            name="incomplete_window",
            description="Official input contains only the first half of the final window.",
            comparator="above",
            thresholds=(Decimal("100000.00"),),
            prints=clean_prints[:30],
            expected_window_valid=False,
        ),
        "stale_loaded_timestamp": synthetic_case(
            name="stale_loaded_timestamp",
            description="One official print exceeds the synthetic max observation lag.",
            comparator="above",
            thresholds=(Decimal("100000.00"),),
            prints=with_stale_loaded_timestamp(clean_prints, offset=20),
            expected_input_valid=False,
            expected_window_valid=False,
        ),
        "future_effective_timestamp": synthetic_case(
            name="future_effective_timestamp",
            description="One official print has a loaded timestamp before its effective timestamp.",
            comparator="above",
            thresholds=(Decimal("100000.00"),),
            prints=with_future_effective_timestamp(clean_prints, offset=20),
            expected_input_valid=False,
            expected_window_valid=False,
        ),
        "wrong_index_ticker": synthetic_case(
            name="wrong_index_ticker",
            description="One official print uses the wrong index ticker.",
            comparator="above",
            thresholds=(Decimal("100000.00"),),
            prints=with_wrong_index_ticker(clean_prints, offset=20),
            expected_input_valid=False,
            expected_window_valid=False,
        ),
    }


def synthetic_case(
    *,
    name: str,
    description: str,
    comparator: PayoutComparator,
    thresholds: tuple[Decimal, ...],
    prints: list[dict[str, Any]],
    expected_input_valid: bool = True,
    expected_window_valid: bool = True,
) -> SyntheticSettlementFixtureCase:
    return SyntheticSettlementFixtureCase(
        name=name,
        description=description,
        market_metadata_payload=synthetic_market_metadata_payload(
            comparator=comparator,
            thresholds=thresholds,
        ),
        official_input_payload=synthetic_official_input_payload(prints),
        decision_times_utc=synthetic_boundary_decision_times(),
        expected_input_valid=expected_input_valid,
        expected_window_valid=expected_window_valid,
    )


def synthetic_market_metadata_payload(
    *,
    comparator: PayoutComparator,
    thresholds: tuple[Decimal, ...],
) -> dict[str, Any]:
    return {
        "schema_version": MARKET_SETTLEMENT_METADATA_SCHEMA_VERSION,
        "market_ticker": f"KXBTC15M-SYNTHETIC-{comparator.upper()}",
        "series": "KXBTC15M",
        "index_ticker": "BRTI",
        "comparator": comparator,
        "thresholds": [str(threshold) for threshold in thresholds],
        "threshold_precision": 2,
        "expiration_time_utc": KXBTC15M_SYNTHETIC_EXPIRATION.isoformat(),
        "metadata_source_id": "synthetic.kalshi.market_metadata",
        "metadata_source_version": "synthetic.v1",
    }


def synthetic_official_input_payload(prints: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SETTLEMENT_INPUT_SCHEMA_VERSION,
        "source": {
            "source_id": KXBTC15M_SYNTHETIC_SOURCE_ID,
            "source_name": "Synthetic CF Benchmarks RTI",
            "source_version": KXBTC15M_SYNTHETIC_SOURCE_VERSION,
            "source_status": "synthetic_fixture",
            "license_status": "synthetic",
            "index_ticker": "BRTI",
            "source_uri": None,
            "source_bundle_sha256": None,
            "max_observation_lag_seconds": 5,
        },
        "prints": prints,
        "created_at_utc": KXBTC15M_SYNTHETIC_EXPIRATION.isoformat(),
    }


def synthetic_print_payloads() -> list[dict[str, Any]]:
    start = KXBTC15M_SYNTHETIC_EXPIRATION - timedelta(seconds=60)
    return [
        synthetic_print_payload(
            effective_time_utc=start + timedelta(seconds=offset),
            observed_value=Decimal("100000.00") + Decimal(offset) / Decimal("100"),
            offset=offset,
        )
        for offset in range(60)
    ]


def synthetic_print_payload(
    *,
    effective_time_utc: datetime,
    observed_value: Decimal,
    offset: int,
) -> dict[str, Any]:
    return {
        "index_ticker": "BRTI",
        "effective_time_utc": effective_time_utc.isoformat(),
        "observed_value": str(observed_value),
        "loaded_at_utc": (effective_time_utc + timedelta(seconds=1)).isoformat(),
        "source_event_id": f"synthetic-brti-{offset:02d}",
    }


def synthetic_boundary_decision_times() -> tuple[datetime, ...]:
    return (
        KXBTC15M_SYNTHETIC_EXPIRATION - timedelta(seconds=61),
        KXBTC15M_SYNTHETIC_EXPIRATION - timedelta(seconds=60),
        KXBTC15M_SYNTHETIC_EXPIRATION - timedelta(seconds=30),
        KXBTC15M_SYNTHETIC_EXPIRATION - timedelta(seconds=1),
        KXBTC15M_SYNTHETIC_EXPIRATION,
        KXBTC15M_SYNTHETIC_EXPIRATION + timedelta(seconds=1),
    )


def without_print(prints: list[dict[str, Any]], *, offset: int) -> list[dict[str, Any]]:
    return [dict(print_payload) for index, print_payload in enumerate(prints) if index != offset]


def with_duplicate_print(prints: list[dict[str, Any]], *, offset: int) -> list[dict[str, Any]]:
    duplicated = [dict(print_payload) for print_payload in prints]
    duplicate = dict(duplicated[offset])
    duplicate["source_event_id"] = "synthetic-brti-duplicate"
    duplicated.insert(offset + 1, duplicate)
    return duplicated


def with_stale_loaded_timestamp(
    prints: list[dict[str, Any]],
    *,
    offset: int,
) -> list[dict[str, Any]]:
    stale = [dict(print_payload) for print_payload in prints]
    effective_time = datetime.fromisoformat(stale[offset]["effective_time_utc"])
    stale[offset]["loaded_at_utc"] = (effective_time + timedelta(seconds=60)).isoformat()
    return stale


def with_future_effective_timestamp(
    prints: list[dict[str, Any]],
    *,
    offset: int,
) -> list[dict[str, Any]]:
    future = [dict(print_payload) for print_payload in prints]
    effective_time = datetime.fromisoformat(future[offset]["effective_time_utc"])
    future[offset]["loaded_at_utc"] = (effective_time - timedelta(seconds=1)).isoformat()
    return future


def with_wrong_index_ticker(
    prints: list[dict[str, Any]],
    *,
    offset: int,
) -> list[dict[str, Any]]:
    wrong = [dict(print_payload) for print_payload in prints]
    wrong[offset]["index_ticker"] = "ETH_RTI"
    return wrong
