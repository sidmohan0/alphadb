from __future__ import annotations

import csv
from pathlib import Path

from alphadb.model_evaluation.cli import main as model_eval_main
from alphadb.research.execution_attribution import generate_execution_attribution


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "execution_attribution" / "live_runs"


def test_execution_attribution_generates_csv_and_markdown_report(tmp_path: Path) -> None:
    result = generate_execution_attribution(FIXTURE_ROOT, tmp_path)

    csv_path = tmp_path / "execution_attribution.csv"
    report_path = tmp_path / "execution_attribution_report.md"
    rows = read_csv_rows(csv_path)

    assert result.row_count == 4
    assert result.run_count == 1
    assert result.bottleneck_verdict == "quote_staleness_problem"
    assert csv_path.exists()
    assert report_path.exists()
    assert len(rows) == 4

    filled = next(row for row in rows if row["market_ticker"] == "KXBTC15M-SYN-FILLED")
    stale = next(row for row in rows if row["market_ticker"] == "KXBTC15M-SYN-STALE")
    risk_denied = next(row for row in rows if row["market_ticker"] == "KXBTC15M-SYN-RISK")

    assert filled["fill_count"] == "2"
    assert filled["quote_age_at_submit_seconds"] == "2.5"
    assert filled["submit_roundtrip_ms"] == "220.0"
    assert filled["realized_pnl"] == "-0.82"
    assert filled["phase_collection_seconds"] == "1.2"
    assert stale["skip_reason"] == "quote_stale"
    assert stale["order_status"] == "skipped"
    assert risk_denied["risk_admission_status"] == "denied"
    assert risk_denied["risk_admission_reason"] == "daily_loss_cap_reached"

    report = report_path.read_text(encoding="utf-8")
    assert "## Hot-path timing" in report
    assert "## Freshness at submit / decision" in report
    assert "## Fillability and adverse-selection checks" in report
    assert "## PnL / implementation-drag estimate" in report
    assert "`quote_staleness_problem`" in report
    assert "insufficient_data:implementation_drag_counterfactual_missing" in report


def test_model_eval_cli_execution_attribution_writes_artifacts(tmp_path: Path) -> None:
    exit_code = model_eval_main(
        [
            "execution-attribution",
            "--input",
            str(FIXTURE_ROOT),
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "execution_attribution.csv").exists()
    assert (tmp_path / "execution_attribution_report.md").exists()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
