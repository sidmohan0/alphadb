from __future__ import annotations

import json
from pathlib import Path

from alphadb.markets.spec import kxbtc15m_settlement_spec
from alphadb.settlement.dataset import SettlementDatasetMarketInput, build_settlement_state_dataset
from alphadb.settlement.fixtures import kxbtc15m_synthetic_fixture_suite


def market_input(case_name: str) -> SettlementDatasetMarketInput:
    case = kxbtc15m_synthetic_fixture_suite()[case_name]
    return SettlementDatasetMarketInput(
        market_metadata_payload=case.market_metadata_payload,
        official_input_payload=case.official_input_payload,
        decision_times_utc=case.decision_times_utc,
    )


def test_dataset_builder_writes_rows_and_summary_for_multiple_markets(tmp_path: Path) -> None:
    result = build_settlement_state_dataset(
        settlement_spec=kxbtc15m_settlement_spec(),
        dataset_id="test-clean-settlement-state",
        market_inputs=[market_input("clean_above"), market_input("clean_between")],
        output_dir=tmp_path,
    )

    rows_path = tmp_path / "settlement_state_rows.jsonl"
    summary_path = tmp_path / "settlement_state_summary.json"
    row_lines = rows_path.read_text(encoding="utf-8").splitlines()
    summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))

    assert len(result.rows) == 12
    assert len(row_lines) == 12
    assert result.summary.market_count == 2
    assert result.summary.decision_row_count == 12
    assert result.summary.valid_row_count == 12
    assert result.summary.invalid_row_count == 0
    assert result.summary.promotion_safe_row_count == 12
    assert result.summary.source_statuses == ("synthetic_fixture",)
    assert len(result.summary.generated_dataset_hash) == 64
    assert summary_payload["generated_dataset_hash"] == result.summary.generated_dataset_hash
    assert summary_payload["artifact_locations"]["rows"].endswith("settlement_state_rows.jsonl")
    assert all(json.loads(line)["row_hash"] for line in row_lines)


def test_dataset_builder_preserves_invalid_rows_for_auditability(tmp_path: Path) -> None:
    result = build_settlement_state_dataset(
        settlement_spec=kxbtc15m_settlement_spec(),
        dataset_id="test-invalid-settlement-state",
        market_inputs=[market_input("missing_print")],
        output_dir=tmp_path,
    )

    assert result.summary.decision_row_count == 6
    assert result.summary.valid_row_count > 0
    assert result.summary.invalid_row_count > 0
    assert result.summary.promotion_safe_row_count < result.summary.decision_row_count
    assert result.summary.quality_flag_counts["missing_prints"] > 0
    assert any("missing_prints" in reason for reason in result.summary.exclusion_reasons)

    rows = [
        json.loads(line)
        for line in (tmp_path / "settlement_state_rows.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(row["row_valid"] is False for row in rows)
    assert any(row["promotion_safe"] is False for row in rows)
