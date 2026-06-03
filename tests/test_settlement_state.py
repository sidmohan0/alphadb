from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from alphadb.markets.spec import SettlementSpec, kxbtc15m_settlement_spec
from alphadb.settlement.fixtures import (
    KXBTC15M_SYNTHETIC_EXPIRATION,
    kxbtc15m_synthetic_fixture_suite,
)
from alphadb.settlement.inputs import MarketSettlementMetadata, NormalizedOfficialSettlementInput
from alphadb.settlement.state import (
    SETTLEMENT_STATE_ROW_SCHEMA_VERSION,
    calculate_settlement_state,
    calculate_settlement_state_from_payloads,
)


def clean_inputs(case_name: str = "clean_above") -> tuple[
    MarketSettlementMetadata,
    NormalizedOfficialSettlementInput,
]:
    case = kxbtc15m_synthetic_fixture_suite()[case_name]
    return (
        MarketSettlementMetadata(**case.market_metadata_payload),
        NormalizedOfficialSettlementInput(**case.official_input_payload),
    )


def test_clean_rows_support_boundary_decision_times() -> None:
    metadata, official_input = clean_inputs()
    settlement_spec = kxbtc15m_settlement_spec()

    rows = [
        calculate_settlement_state(
            settlement_spec=settlement_spec,
            metadata=metadata,
            official_input=official_input,
            decision_time_utc=decision_time,
        )
        for decision_time in kxbtc15m_synthetic_fixture_suite()["clean_above"].decision_times_utc
    ]

    assert [row.locked_count for row in rows] == [0, 1, 31, 60, 60, 60]
    assert [row.remaining_count for row in rows] == [60, 59, 29, 0, 0, 0]
    assert all(row.row_valid for row in rows)
    assert all(row.promotion_safe for row in rows)
    assert rows[0].locked_average is None
    assert rows[1].locked_sum == Decimal("100000.00")
    assert rows[1].locked_average == Decimal("100000.00")
    assert rows[-1].source_lag_seconds == 2


def test_clean_final_row_has_required_audit_fields_and_hashes() -> None:
    metadata, official_input = clean_inputs("clean_between")

    row = calculate_settlement_state(
        settlement_spec=kxbtc15m_settlement_spec(),
        metadata=metadata,
        official_input=official_input,
        decision_time_utc=KXBTC15M_SYNTHETIC_EXPIRATION + timedelta(seconds=1),
    )

    assert row.schema_version == SETTLEMENT_STATE_ROW_SCHEMA_VERSION
    assert row.market_ticker == "KXBTC15M-SYNTHETIC-BETWEEN"
    assert row.series == "KXBTC15M"
    assert row.index_ticker == "BRTI"
    assert row.payout_comparator == "between"
    assert row.payout_thresholds == (Decimal("99990.00"), Decimal("100010.00"))
    assert row.threshold_precision == 2
    assert row.final_window_start_utc == KXBTC15M_SYNTHETIC_EXPIRATION - timedelta(seconds=60)
    assert row.final_window_end_utc == KXBTC15M_SYNTHETIC_EXPIRATION
    assert row.expected_print_count == 60
    assert row.locked_count == 60
    assert row.locked_sum == Decimal("6000017.70")
    assert row.locked_average == Decimal("100000.295")
    assert row.remaining_count == 0
    assert row.source_quality_flags == ()
    assert row.invalid_reason is None
    assert row.max_source_event_timestamp_utc == KXBTC15M_SYNTHETIC_EXPIRATION - timedelta(seconds=1)
    assert row.source_id == "synthetic.cf-brti.kxbtc15m"
    assert row.source_version == "synthetic.v1"
    assert row.source_status == "synthetic_fixture"
    assert row.metadata_source_id == "synthetic.kalshi.market_metadata"
    assert len(row.source_event_ids) == 60
    assert len(row.locked_prints_hash) == 64
    assert len(row.market_metadata_hash) == 64
    assert len(row.row_hash) == 64
    assert row.as_dict()["row_hash"] == row.row_hash


def test_no_lookahead_future_print_values_do_not_change_partial_row() -> None:
    case = kxbtc15m_synthetic_fixture_suite()["clean_above"]
    metadata = MarketSettlementMetadata(**case.market_metadata_payload)
    official_input = NormalizedOfficialSettlementInput(**case.official_input_payload)
    decision_time = KXBTC15M_SYNTHETIC_EXPIRATION - timedelta(seconds=30)

    baseline = calculate_settlement_state(
        settlement_spec=kxbtc15m_settlement_spec(),
        metadata=metadata,
        official_input=official_input,
        decision_time_utc=decision_time,
    )
    changed_payload = {
        **case.official_input_payload,
        "prints": [dict(print_payload) for print_payload in case.official_input_payload["prints"]],
    }
    changed_payload["prints"][-1]["observed_value"] = "1.00"
    changed_input = NormalizedOfficialSettlementInput(**changed_payload)
    changed = calculate_settlement_state(
        settlement_spec=kxbtc15m_settlement_spec(),
        metadata=metadata,
        official_input=changed_input,
        decision_time_utc=decision_time,
    )

    assert baseline.locked_count == 31
    assert baseline.row_hash == changed.row_hash
    assert baseline.locked_prints_hash == changed.locked_prints_hash
    assert baseline.source_event_ids == changed.source_event_ids


def test_missing_and_incomplete_windows_return_invalid_audit_rows() -> None:
    settlement_spec = kxbtc15m_settlement_spec()
    decision_time = KXBTC15M_SYNTHETIC_EXPIRATION + timedelta(seconds=1)

    for case_name, locked_count in (("missing_print", 59), ("incomplete_window", 30)):
        case = kxbtc15m_synthetic_fixture_suite()[case_name]
        row = calculate_settlement_state(
            settlement_spec=settlement_spec,
            metadata=MarketSettlementMetadata(**case.market_metadata_payload),
            official_input=NormalizedOfficialSettlementInput(**case.official_input_payload),
            decision_time_utc=decision_time,
        )

        assert row.row_valid is False
        assert row.promotion_safe is False
        assert "missing_prints" in row.source_quality_flags
        assert "incomplete_window" in row.source_quality_flags
        assert row.invalid_reason is not None
        assert row.locked_count == locked_count
        assert row.remaining_count == 0
        assert len(row.row_hash) == 64


def test_payload_wrapper_returns_quality_flags_for_malformed_fixture_inputs() -> None:
    expected_flags = {
        "duplicate_timestamp": "duplicate_timestamps",
        "stale_loaded_timestamp": "stale_source_timestamp",
        "future_effective_timestamp": "future_effective_timestamp",
        "wrong_index_ticker": "wrong_index_ticker",
    }

    for case_name, expected_flag in expected_flags.items():
        case = kxbtc15m_synthetic_fixture_suite()[case_name]
        row = calculate_settlement_state_from_payloads(
            settlement_spec=kxbtc15m_settlement_spec(),
            market_metadata_payload=case.market_metadata_payload,
            official_input_payload=case.official_input_payload,
            decision_time_utc=KXBTC15M_SYNTHETIC_EXPIRATION + timedelta(seconds=1),
        )

        assert row.market_ticker == case.market_metadata_payload["market_ticker"]
        assert row.row_valid is False
        assert row.promotion_safe is False
        assert expected_flag in row.source_quality_flags
        assert row.invalid_reason is not None
        assert row.invalid_reason.startswith("invalid_official_input:")
        assert row.locked_count == 0
        assert row.source_id == "synthetic.cf-brti.kxbtc15m"
        assert len(row.row_hash) == 64


def test_clean_comparator_fixtures_preserve_threshold_and_comparator_metadata() -> None:
    for case_name in (
        "clean_above",
        "clean_below",
        "clean_exactly",
        "clean_at_least",
        "clean_between",
    ):
        case = kxbtc15m_synthetic_fixture_suite()[case_name]
        row = calculate_settlement_state_from_payloads(
            settlement_spec=kxbtc15m_settlement_spec(),
            market_metadata_payload=case.market_metadata_payload,
            official_input_payload=case.official_input_payload,
            decision_time_utc=KXBTC15M_SYNTHETIC_EXPIRATION + timedelta(seconds=1),
        )

        assert row.row_valid is True
        assert row.payout_comparator == case.market_metadata_payload["comparator"]
        assert row.payout_thresholds == tuple(
            Decimal(threshold) for threshold in case.market_metadata_payload["thresholds"]
        )


def test_unconfirmed_settlement_rule_returns_ambiguous_invalid_row() -> None:
    spec_payload = kxbtc15m_settlement_spec().model_dump(mode="json")
    spec_payload["payout_threshold_rule"]["verification_status"] = "requires_human_confirmation"
    settlement_spec = SettlementSpec(**spec_payload)
    metadata, official_input = clean_inputs()

    row = calculate_settlement_state(
        settlement_spec=settlement_spec,
        metadata=metadata,
        official_input=official_input,
        decision_time_utc=KXBTC15M_SYNTHETIC_EXPIRATION + timedelta(seconds=1),
    )

    assert row.row_valid is False
    assert row.promotion_safe is False
    assert row.source_quality_flags == ("ambiguous_market_metadata",)
    assert row.invalid_reason == "ambiguous_market_metadata"
