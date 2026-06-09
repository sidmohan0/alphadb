from __future__ import annotations

import csv
import json
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


def test_execution_attribution_reports_candidate_latency_and_context_buckets(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "input" / "fv_live_candidates"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "fv_live_candidates",
                "strategy": "fair_value_live",
                "generated_at": "2026-06-04T15:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "live_order_attempts.json").write_text(
        json.dumps({"run_id": "fv_live_candidates", "attempts": []}),
        encoding="utf-8",
    )
    (run_dir / "decision_rows.json").write_text(
        json.dumps(
            {
                "run_id": "fv_live_candidates",
                "generated_at": "2026-06-04T15:00:00+00:00",
                "rows": [
                    candidate_row(
                        ticker="KXBTC15M-CAND-STALE-QUOTE",
                        quote_age=40.0,
                        active_age=2.0,
                        active_status="fresh",
                        diagnostic_class="quote_freshness_suspect",
                        edge=0.08,
                        reason="edge_met",
                        total_seconds=1.0,
                    ),
                    candidate_row(
                        ticker="KXBTC15M-CAND-STALE-CONTEXT",
                        quote_age=2.0,
                        active_age=120.0,
                        active_status="stale",
                        diagnostic_class="coinbase_freshness_suspect",
                        edge=0.08,
                        reason="edge_met",
                        total_seconds=1.0,
                    ),
                    candidate_row(
                        ticker="KXBTC15M-CAND-SLOW",
                        quote_age=2.0,
                        active_age=2.0,
                        active_status="fresh",
                        diagnostic_class="edge_cleared",
                        edge=0.08,
                        reason="edge_met",
                        total_seconds=12.0,
                    ),
                    candidate_row(
                        ticker="KXBTC15M-CAND-BELOW-HURDLE",
                        quote_age=2.0,
                        active_age=2.0,
                        active_status="fresh",
                        diagnostic_class="threshold_drag",
                        edge=0.03,
                        reason="edge_below_min",
                        total_seconds=1.0,
                    ),
                ],
            }
        ),
        encoding="utf-8",
    )

    result = generate_execution_attribution(run_dir.parent, tmp_path / "output")
    rows = read_csv_rows(Path(result.csv_path))
    report = Path(result.report_path).read_text(encoding="utf-8")

    assert result.row_count == 4
    assert {row["evidence_type"] for row in rows} == {"candidate"}
    assert any(
        row["market_ticker"] == "KXBTC15M-CAND-STALE-CONTEXT"
        and row["active_context_status"] == "stale"
        for row in rows
    )
    assert bucket_count(result, "quote_age_bucket_summary", "15_60s") == 1
    assert bucket_count(result, "active_context_age_bucket_summary", "60s_plus") == 1
    assert bucket_count(result, "hot_path_total_latency_bucket_summary", "10s_plus") == 1
    assert bucket_count(result, "edge_bucket_summary", "2_5pct") == 1
    assert bucket_count(result, "diagnostic_class_summary", "threshold_drag") == 1
    assert result.summaries["fresh_quote_counterfactual"]["status"] == "unavailable"
    assert "Active context age buckets:" in report
    assert "Hot-path total latency buckets:" in report
    assert "Diagnostic class buckets:" in report
    assert "- Fresh-quote counterfactual status: `unavailable`" in report
    assert "- Status: `unavailable`" in report


def candidate_row(
    *,
    ticker: str,
    quote_age: float,
    active_age: float,
    active_status: str,
    diagnostic_class: str,
    edge: float,
    reason: str,
    total_seconds: float,
) -> dict:
    return {
        "row_type": "decision",
        "ticker": ticker,
        "market_ticker": ticker,
        "decision_timestamp": "2026-06-04T15:00:00+00:00",
        "quote_observed_at": "2026-06-04T14:59:58+00:00",
        "close_time": "2026-06-04T15:05:00+00:00",
        "live_edge_attribution": {
            "decision": "skip" if reason == "edge_below_min" else "trade",
            "reason": reason,
            "side": "yes",
            "price": 0.45,
            "edge": edge,
            "min_edge": 0.05,
            "edge_shortfall": max(0.0, round(0.05 - edge, 6)),
            "attribution_class": diagnostic_class,
            "freshness": {
                "quote_seen_at": "2026-06-04T14:59:58+00:00",
                "quote_age_seconds": quote_age,
                "coinbase_max_source_event_timestamp": "2026-06-04T14:59:58+00:00",
                "coinbase_feature_age_seconds": active_age,
                "active_context": {
                    "market_context_source": "coinbase_primary",
                    "evidence_source": "coinbase_features",
                    "status": active_status,
                    "age_seconds": active_age,
                    "stale_seconds": 90.0,
                },
            },
            "timing": {
                "total_elapsed_seconds": total_seconds,
                "phase_seconds": {"collection": total_seconds},
            },
            "fresh_quote_counterfactual": {
                "status": "unavailable",
                "basis": "independent_fresh_quote_evidence_missing",
            },
        },
    }


def bucket_count(result, summary_name: str, bucket: str) -> int:
    for row in result.summaries[summary_name]:
        if row["bucket"] == bucket:
            return row["count"]
    return 0


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
