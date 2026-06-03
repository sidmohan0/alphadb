from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from alphadb.markets.spec import kxbtc15m_settlement_spec
from alphadb.settlement.fixtures import (
    KXBTC15M_SYNTHETIC_EXPIRATION,
    kxbtc15m_synthetic_fixture_suite,
)
from alphadb.settlement.inputs import (
    MarketSettlementMetadata,
    NormalizedOfficialSettlementInput,
    SettlementInputSource,
    SettlementInputValidationError,
    expected_final_window_times,
    has_private_source_reference,
    source_event_ids,
    validated_final_window_prints,
)


def test_clean_synthetic_fixture_validates_through_public_contract() -> None:
    case = kxbtc15m_synthetic_fixture_suite()["clean_above"]
    metadata = MarketSettlementMetadata(**case.market_metadata_payload)
    official_input = NormalizedOfficialSettlementInput(**case.official_input_payload)

    final_window = validated_final_window_prints(
        metadata=metadata,
        official_input=official_input,
        settlement_spec=kxbtc15m_settlement_spec(),
    )

    assert metadata.market_ticker == "KXBTC15M-SYNTHETIC-ABOVE"
    assert metadata.comparator == "above"
    assert metadata.thresholds[0] > 0
    assert metadata.content_hash()
    assert official_input.source.source_status == "synthetic_fixture"
    assert official_input.source.license_status == "synthetic"
    assert has_private_source_reference(official_input.source) is False
    assert official_input.content_hash()
    assert len(final_window) == 60
    assert len(source_event_ids(final_window)) == 60


def test_synthetic_fixture_suite_covers_required_cases() -> None:
    cases = kxbtc15m_synthetic_fixture_suite()

    assert {
        "clean_above",
        "clean_below",
        "clean_exactly",
        "clean_at_least",
        "clean_between",
        "missing_print",
        "duplicate_timestamp",
        "incomplete_window",
        "stale_loaded_timestamp",
        "future_effective_timestamp",
        "wrong_index_ticker",
    }.issubset(cases)

    comparators = {
        MarketSettlementMetadata(**case.market_metadata_payload).comparator
        for case in cases.values()
        if case.expected_input_valid
    }
    assert {"above", "below", "exactly", "at_least", "between"}.issubset(comparators)


def test_synthetic_fixture_validity_expectations_are_enforced() -> None:
    settlement_spec = kxbtc15m_settlement_spec()
    for case in kxbtc15m_synthetic_fixture_suite().values():
        metadata = MarketSettlementMetadata(**case.market_metadata_payload)
        if case.expected_input_valid:
            official_input = NormalizedOfficialSettlementInput(**case.official_input_payload)
        else:
            with pytest.raises(ValidationError):
                NormalizedOfficialSettlementInput(**case.official_input_payload)
            continue

        if case.expected_window_valid:
            final_window = validated_final_window_prints(
                metadata=metadata,
                official_input=official_input,
                settlement_spec=settlement_spec,
            )
            assert len(final_window) == settlement_spec.final_settlement_window.expected_print_count
        else:
            with pytest.raises(SettlementInputValidationError):
                validated_final_window_prints(
                    metadata=metadata,
                    official_input=official_input,
                    settlement_spec=settlement_spec,
                )


def test_expected_final_window_times_use_sixty_seconds_prior_to_expiration() -> None:
    times = expected_final_window_times(
        expiration_time_utc=KXBTC15M_SYNTHETIC_EXPIRATION,
        settlement_spec=kxbtc15m_settlement_spec(),
    )

    assert len(times) == 60
    assert times[0] == KXBTC15M_SYNTHETIC_EXPIRATION - timedelta(seconds=60)
    assert times[-1] == KXBTC15M_SYNTHETIC_EXPIRATION - timedelta(seconds=1)


def test_boundary_decision_times_are_public_fixture_data() -> None:
    case = kxbtc15m_synthetic_fixture_suite()["clean_above"]

    assert case.decision_times_utc == (
        KXBTC15M_SYNTHETIC_EXPIRATION - timedelta(seconds=61),
        KXBTC15M_SYNTHETIC_EXPIRATION - timedelta(seconds=60),
        KXBTC15M_SYNTHETIC_EXPIRATION - timedelta(seconds=30),
        KXBTC15M_SYNTHETIC_EXPIRATION - timedelta(seconds=1),
        KXBTC15M_SYNTHETIC_EXPIRATION,
        KXBTC15M_SYNTHETIC_EXPIRATION + timedelta(seconds=1),
    )


def test_market_metadata_rejects_malformed_thresholds() -> None:
    payload = dict(kxbtc15m_synthetic_fixture_suite()["clean_above"].market_metadata_payload)
    payload["thresholds"] = ["99999.00", "100000.00"]

    with pytest.raises(ValidationError, match="threshold count"):
        MarketSettlementMetadata(**payload)


def test_market_metadata_rejects_unordered_between_thresholds() -> None:
    payload = dict(kxbtc15m_synthetic_fixture_suite()["clean_between"].market_metadata_payload)
    payload["thresholds"] = ["100010.00", "99990.00"]

    with pytest.raises(ValidationError, match="ordered"):
        MarketSettlementMetadata(**payload)


def test_official_input_rejects_missing_prints() -> None:
    payload = dict(kxbtc15m_synthetic_fixture_suite()["clean_above"].official_input_payload)
    payload["prints"] = []

    with pytest.raises(ValidationError, match="at least one print"):
        NormalizedOfficialSettlementInput(**payload)


def test_official_input_rejects_duplicate_timestamp_fixture() -> None:
    case = kxbtc15m_synthetic_fixture_suite()["duplicate_timestamp"]

    with pytest.raises(ValidationError, match="strictly ordered|duplicate"):
        NormalizedOfficialSettlementInput(**case.official_input_payload)


def test_final_window_validation_rejects_missing_and_incomplete_windows() -> None:
    settlement_spec = kxbtc15m_settlement_spec()
    for case_name in ("missing_print", "incomplete_window"):
        case = kxbtc15m_synthetic_fixture_suite()[case_name]
        metadata = MarketSettlementMetadata(**case.market_metadata_payload)
        official_input = NormalizedOfficialSettlementInput(**case.official_input_payload)

        with pytest.raises(SettlementInputValidationError, match="missing"):
            validated_final_window_prints(
                metadata=metadata,
                official_input=official_input,
                settlement_spec=settlement_spec,
            )


def test_official_input_rejects_stale_and_future_timestamps() -> None:
    cases = kxbtc15m_synthetic_fixture_suite()

    with pytest.raises(ValidationError, match="max observation lag"):
        NormalizedOfficialSettlementInput(**cases["stale_loaded_timestamp"].official_input_payload)

    with pytest.raises(ValidationError, match="loaded_at_utc"):
        NormalizedOfficialSettlementInput(**cases["future_effective_timestamp"].official_input_payload)


def test_official_input_rejects_wrong_index_ticker() -> None:
    case = kxbtc15m_synthetic_fixture_suite()["wrong_index_ticker"]

    with pytest.raises(ValidationError, match="index_ticker"):
        NormalizedOfficialSettlementInput(**case.official_input_payload)


def test_content_hash_changes_when_official_print_changes() -> None:
    payload = dict(kxbtc15m_synthetic_fixture_suite()["clean_above"].official_input_payload)
    baseline = NormalizedOfficialSettlementInput(**payload)
    changed_payload = {
        **payload,
        "prints": [dict(print_payload) for print_payload in payload["prints"]],
    }
    changed_payload["prints"][0]["observed_value"] = "99999.99"
    changed = NormalizedOfficialSettlementInput(**changed_payload)

    assert baseline.content_hash() != changed.content_hash()


def test_synthetic_source_cannot_reference_private_artifacts() -> None:
    source_payload = dict(
        kxbtc15m_synthetic_fixture_suite()["clean_above"].official_input_payload["source"]
    )
    source_payload["source_uri"] = "file:///private/brti.csv"

    with pytest.raises(ValidationError, match="synthetic fixtures"):
        SettlementInputSource(**source_payload)
