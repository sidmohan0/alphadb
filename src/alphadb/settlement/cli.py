"""Settlement-state readiness command-line workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from alphadb.markets.spec import kxbtc15m_settlement_spec
from alphadb.settlement.dataset import (
    DEFAULT_SETTLEMENT_DATASET_ROOT,
    SettlementDatasetMarketInput,
    build_settlement_state_dataset,
    public_artifact_location,
)
from alphadb.settlement.fixtures import kxbtc15m_synthetic_fixture_suite
from alphadb.settlement.manifest import write_settlement_readiness_manifest

SYNTHETIC_READINESS_NOTICE = (
    "Synthetic settlement-state readiness uses public fixtures only. It is not a "
    "strategy promotion decision and does not imply H1/H2/H3 results."
)


def run_synthetic_readiness(
    *,
    dataset_id: str = "synthetic-kxbtc15m-settlement-readiness",
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    output_root = (
        Path(output_dir)
        if output_dir is not None
        else DEFAULT_SETTLEMENT_DATASET_ROOT / dataset_id
    )
    fixtures = kxbtc15m_synthetic_fixture_suite()
    market_inputs = [
        SettlementDatasetMarketInput(
            market_metadata_payload=fixtures["clean_above"].market_metadata_payload,
            official_input_payload=fixtures["clean_above"].official_input_payload,
            decision_times_utc=fixtures["clean_above"].decision_times_utc,
        ),
        SettlementDatasetMarketInput(
            market_metadata_payload=fixtures["missing_print"].market_metadata_payload,
            official_input_payload=fixtures["missing_print"].official_input_payload,
            decision_times_utc=fixtures["missing_print"].decision_times_utc,
        ),
    ]
    result = build_settlement_state_dataset(
        settlement_spec=kxbtc15m_settlement_spec(),
        dataset_id=dataset_id,
        market_inputs=market_inputs,
        output_dir=output_root,
    )
    manifest_path = output_root / "settlement_state_manifest.json"
    manifest = write_settlement_readiness_manifest(
        summary=result.summary,
        output_path=manifest_path,
    )
    report = {
        "dataset_id": dataset_id,
        "readiness_verdict": manifest.readiness_verdict,
        "readiness_reasons": list(manifest.readiness_reasons),
        "coverage_summary": {
            "market_count": result.summary.market_count,
            "decision_row_count": result.summary.decision_row_count,
            "valid_row_count": result.summary.valid_row_count,
            "invalid_row_count": result.summary.invalid_row_count,
            "promotion_safe_row_count": result.summary.promotion_safe_row_count,
            "exclusion_reasons": result.summary.exclusion_reasons,
            "quality_flag_counts": result.summary.quality_flag_counts,
        },
        "artifact_locations": {
            **manifest.artifact_locations,
            "report": public_artifact_location(output_root / "synthetic_readiness_report.json"),
        },
        "public_fixture_only": True,
        "requires_private_inputs": False,
        "requires_credentials": False,
        "notice": SYNTHETIC_READINESS_NOTICE,
    }
    report_path = output_root / "synthetic_readiness_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-settlement")
    subparsers = parser.add_subparsers(dest="command", required=True)

    synthetic = subparsers.add_parser(
        "synthetic-readiness",
        help="Run public synthetic settlement-state readiness end to end",
    )
    synthetic.add_argument(
        "--dataset-id",
        default="synthetic-kxbtc15m-settlement-readiness",
    )
    synthetic.add_argument(
        "--output-dir",
        default=None,
        help="Output directory; defaults to ignored artifacts/settlement-state/<dataset-id>",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "synthetic-readiness":
        report = run_synthetic_readiness(
            dataset_id=args.dataset_id,
            output_dir=args.output_dir,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
