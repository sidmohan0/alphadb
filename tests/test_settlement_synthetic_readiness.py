from __future__ import annotations

import json
from pathlib import Path

from alphadb.settlement.cli import main, run_synthetic_readiness


def test_synthetic_readiness_run_emits_rows_manifest_report_and_notice(tmp_path: Path) -> None:
    report = run_synthetic_readiness(
        dataset_id="test-synthetic-readiness",
        output_dir=tmp_path,
    )

    assert (tmp_path / "settlement_state_rows.jsonl").exists()
    assert (tmp_path / "settlement_state_summary.json").exists()
    assert (tmp_path / "settlement_state_manifest.json").exists()
    assert (tmp_path / "synthetic_readiness_report.json").exists()
    assert report["public_fixture_only"] is True
    assert report["requires_private_inputs"] is False
    assert report["requires_credentials"] is False
    assert report["readiness_verdict"] == "FAIL"
    assert report["coverage_summary"]["valid_row_count"] > 0
    assert report["coverage_summary"]["invalid_row_count"] > 0
    assert "not a strategy promotion decision" in report["notice"]
    assert "H1/H2/H3" in report["notice"]

    manifest = json.loads((tmp_path / "settlement_state_manifest.json").read_text(encoding="utf-8"))
    assert manifest["readiness_verdict"] == report["readiness_verdict"]
    assert "observed_value" not in json.dumps(manifest)


def test_synthetic_readiness_cli_is_ci_friendly(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "synthetic-readiness",
            "--dataset-id",
            "test-cli-synthetic-readiness",
            "--output-dir",
            str(tmp_path),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["dataset_id"] == "test-cli-synthetic-readiness"
    assert output["artifact_locations"]["rows"].endswith("settlement_state_rows.jsonl")
    assert output["artifact_locations"]["manifest"].endswith("settlement_state_manifest.json")
    assert output["requires_private_inputs"] is False
