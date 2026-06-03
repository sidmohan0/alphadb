from __future__ import annotations

import copy
import json
from pathlib import Path

from alphadb.markets.spec import kxbtc15m_settlement_spec
from alphadb.settlement.dataset import SettlementDatasetMarketInput, build_settlement_state_dataset
from alphadb.settlement.fixtures import kxbtc15m_synthetic_fixture_suite
from alphadb.settlement.manifest import (
    build_settlement_readiness_manifest,
    write_settlement_readiness_manifest,
)


def build_summary(
    tmp_path: Path,
    *,
    case_name: str,
    official_licensed: bool = False,
):
    case = kxbtc15m_synthetic_fixture_suite()[case_name]
    official_input_payload = copy.deepcopy(case.official_input_payload)
    if official_licensed:
        official_input_payload["source"]["source_status"] = "official_licensed"
        official_input_payload["source"]["license_status"] = "licensed"

    return build_settlement_state_dataset(
        settlement_spec=kxbtc15m_settlement_spec(),
        dataset_id=f"test-{case_name}",
        market_inputs=[
            SettlementDatasetMarketInput(
                market_metadata_payload=case.market_metadata_payload,
                official_input_payload=official_input_payload,
                decision_times_utc=case.decision_times_utc,
            )
        ],
        output_dir=tmp_path / case_name,
    ).summary


def test_manifest_can_emit_pass_for_clean_official_licensed_summary(tmp_path: Path) -> None:
    manifest = build_settlement_readiness_manifest(
        summary=build_summary(tmp_path, case_name="clean_above", official_licensed=True)
    )

    assert manifest.readiness_verdict == "PASS"
    assert manifest.readiness_reasons == ("all_rows_valid_with_official_licensed_source",)
    assert manifest.official_input_statuses == ("official_licensed",)
    assert manifest.valid_row_count == manifest.decision_row_count
    assert len(manifest.generated_dataset_hash) == 64
    assert len(manifest.manifest_hash) == 64


def test_manifest_emits_fail_for_non_rule_quality_failures(tmp_path: Path) -> None:
    manifest = build_settlement_readiness_manifest(
        summary=build_summary(tmp_path, case_name="missing_print")
    )

    assert manifest.readiness_verdict == "FAIL"
    assert any(reason.startswith("missing_prints:") for reason in manifest.readiness_reasons)
    assert manifest.invalid_row_count > 0
    assert manifest.exclusion_reasons


def test_manifest_emits_inconclusive_for_clean_synthetic_source(tmp_path: Path) -> None:
    manifest = build_settlement_readiness_manifest(
        summary=build_summary(tmp_path, case_name="clean_above")
    )

    assert manifest.readiness_verdict == "INCONCLUSIVE"
    assert manifest.readiness_reasons == (
        "official_licensed_source_required_for_promotion_grade_readiness",
    )
    assert manifest.official_input_statuses == ("synthetic_fixture",)


def test_manifest_file_is_public_safe_and_hash_based(tmp_path: Path) -> None:
    summary = build_summary(tmp_path, case_name="clean_between")
    manifest_path = tmp_path / "manifest.json"

    manifest = write_settlement_readiness_manifest(
        summary=summary,
        output_path=manifest_path,
    )

    payload_text = manifest_path.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    assert payload["manifest_hash"] == manifest.manifest_hash
    assert payload["input_hashes"]["official_settlement_input"]
    assert payload["artifact_locations"]["manifest"].endswith("manifest.json")
    assert "observed_value" not in payload_text
    assert "source_event_id" not in payload_text
    assert "source_bundle_sha256" not in payload_text
