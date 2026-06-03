"""Lean Edge verdict reports for KXBTC15M Coinbase/BTC research."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from alphadb.model_evaluation.features import (
    default_model_feature_columns,
    engineer_kxbtc_features,
    resolve_feature_groups,
)
from alphadb.model_evaluation.metrics import (
    calibration_buckets,
    optional_float,
    probability_metrics,
    simulate_policy,
    summarize_policy_metrics,
)
from alphadb.model_evaluation.models import (
    append_engineered_group_columns,
    build_direct_policy_stress_scenarios,
    fit_and_report_candidate,
    prefixed_metric_delta,
    rename_prediction_candidate,
    rows_for_markets,
    rows_with_numeric_features,
)
from alphadb.model_evaluation.walk_forward import build_walk_forward_windows

EdgeVerdict = Literal["edge_candidate", "revise", "stop", "inconclusive"]

EDGE_VERDICTS: tuple[EdgeVerdict, ...] = (
    "edge_candidate",
    "revise",
    "stop",
    "inconclusive",
)
NON_PROMOTION_NOTICE = (
    "This Edge verdict report informs research only and does not authorize model promotion, "
    "live trading, Current MVP changes, or target-platform cutover."
)
COINBASE_BTC_GROUP = "coinbase_btc_market_structure"


def build_edge_verdict_report(
    evidence: Mapping[str, Any],
    *,
    feature_pruning_report: Mapping[str, Any] | None = None,
    raw_x_status: str = "frozen_failed_branch",
) -> dict[str, Any]:
    probability_delta = mapping_from(evidence.get("aggregate_probability_delta"))
    policy_delta = mapping_from(evidence.get("aggregate_policy_delta"))
    stress_delta_raw = mapping_from(evidence.get("aggregate_stress_delta"))
    stress_delta = mapping_from(
        stress_delta_raw.get("worse_spread_1_cents")
        or stress_delta_raw.get("base_holdout")
        or stress_delta_raw
    )
    window_count = int(optional_float(evidence.get("complete_window_count")) or 0)
    verdict = choose_edge_verdict(
        probability_delta=probability_delta,
        policy_delta=policy_delta,
        stress_delta=stress_delta,
        complete_window_count=window_count,
    )
    return {
        "schema_version": "kxbtc_edge_verdict_report_v1",
        "verdict": verdict,
        "verdict_contract": {
            "allowed_values": list(EDGE_VERDICTS),
            "edge_candidate_rule": (
                "Requires non-worse probability quality, positive taker-policy delta, and "
                "no material fee/spread-stress deterioration."
            ),
        },
        "raw_x_count_branch_status": raw_x_status,
        "feature_pruning_summary": summarize_feature_pruning(feature_pruning_report),
        "evidence_summary": dict(evidence),
        "rationale": edge_verdict_rationale(verdict, probability_delta, policy_delta, stress_delta),
        "non_promotion_notice": NON_PROMOTION_NOTICE,
    }


def choose_edge_verdict(
    *,
    probability_delta: Mapping[str, Any],
    policy_delta: Mapping[str, Any],
    stress_delta: Mapping[str, Any] | None = None,
    complete_window_count: int = 0,
) -> dict[str, Any]:
    if complete_window_count < 1 or not probability_delta or not policy_delta:
        return {
            "value": "inconclusive",
            "reason": "missing_or_insufficient_windowed_evidence",
        }
    probability = probability_direction(probability_delta)
    policy = policy_direction(policy_delta)
    stress = stress_direction(stress_delta or {})
    if probability in {"better", "flat"} and policy == "better" and stress in {"better", "flat"}:
        return {"value": "edge_candidate", "reason": "probability_and_policy_improved"}
    if probability == "worse" and policy == "worse":
        return {"value": "stop", "reason": "probability_and_policy_worsened"}
    if probability == "better" and policy == "worse":
        return {"value": "revise", "reason": "probability_improved_but_policy_worsened"}
    return {"value": "revise", "reason": "mixed_edge_evidence_needs_revision"}


def probability_direction(delta: Mapping[str, Any]) -> str:
    improvements = 0
    regressions = 0
    for key in ("brier_score", "log_loss"):
        value = optional_float(delta.get(key))
        if value is not None:
            improvements += int(value < 0)
            regressions += int(value > 0)
    for key in ("roc_auc", "average_precision", "accuracy_50"):
        value = optional_float(delta.get(key))
        if value is not None:
            improvements += int(value > 0)
            regressions += int(value < 0)
    if improvements and not regressions:
        return "better"
    if regressions and not improvements:
        return "worse"
    return "flat" if improvements == regressions else "mixed"


def policy_direction(delta: Mapping[str, Any]) -> str:
    net_pnl = optional_float(delta.get("net_pnl"))
    profit_factor = optional_float(delta.get("profit_factor"))
    win_rate = optional_float(delta.get("win_rate"))
    drawdown = optional_float(delta.get("max_drawdown"))
    positives = sum(
        (
            int(net_pnl is not None and net_pnl > 0),
            int(profit_factor is not None and profit_factor > 0),
            int(win_rate is not None and win_rate > 0),
            int(drawdown is not None and drawdown < 0),
        )
    )
    negatives = sum(
        (
            int(net_pnl is not None and net_pnl < 0),
            int(profit_factor is not None and profit_factor < 0),
            int(win_rate is not None and win_rate < 0),
            int(drawdown is not None and drawdown > 0),
        )
    )
    if positives and not negatives:
        return "better"
    if negatives and not positives:
        return "worse"
    if positives == negatives:
        return "flat"
    return "better" if positives > negatives else "worse"


def stress_direction(delta: Mapping[str, Any]) -> str:
    if not delta:
        return "flat"
    return policy_direction(delta)


def edge_verdict_rationale(
    verdict: Mapping[str, Any],
    probability_delta: Mapping[str, Any],
    policy_delta: Mapping[str, Any],
    stress_delta: Mapping[str, Any],
) -> list[str]:
    value = verdict.get("value")
    if value == "edge_candidate":
        return [
            "Probability quality did not deteriorate.",
            "Taker-policy outcomes improved after fees and spread stress.",
        ]
    if value == "stop":
        return [
            "Probability quality deteriorated.",
            "Taker-policy outcomes deteriorated after fees or spread stress.",
        ]
    if value == "inconclusive":
        return ["The report did not contain enough complete windowed evidence."]
    if probability_direction(probability_delta) == "better" and policy_direction(policy_delta) == "worse":
        return [
            "Probability quality improved, but taker-policy outcomes worsened.",
            "Revise feature selection, calibration, side selection, or policy thresholds before claiming edge.",
        ]
    return [
        "Evidence is mixed.",
        "Revise the branch before treating it as a tradable edge candidate.",
    ]


def build_feature_pruning_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_columns: Sequence[str],
    top_n: int = 8,
    comparison_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    engineered = engineer_kxbtc_features(rows)
    default_columns = default_model_feature_columns(feature_columns)
    all_columns = append_engineered_group_columns(default_columns, engineered, COINBASE_BTC_GROUP)
    groups = resolve_feature_groups(all_columns)
    coinbase_columns = groups.get(COINBASE_BTC_GROUP, [])
    rankings = [
        rank_feature_column(engineered, column)
        for column in coinbase_columns
    ]
    rankings = sorted(rankings, key=lambda item: item["score"], reverse=True)
    retained = [
        item["feature"]
        for item in rankings
        if optional_float(item.get("score")) is not None and float(item["score"]) > 0
    ][: max(1, top_n)]
    if not retained and rankings:
        retained = [str(rankings[0]["feature"])]
    retained_set = set(retained)
    return {
        "schema_version": "kxbtc_coinbase_btc_feature_pruning_report_v1",
        "source_feature_group": COINBASE_BTC_GROUP,
        "raw_row_count": len(rows),
        "candidate_feature_count": len(coinbase_columns),
        "retained_feature_count": len(retained),
        "slim_feature_columns": retained,
        "excluded_feature_columns": [
            column for column in coinbase_columns if column not in retained_set
        ],
        "rankings": rankings,
        "policy_mismatch_diagnostics": build_policy_mismatch_diagnostics(comparison_report),
        "default_excluded_feature_groups": ["x_external_signal_state"],
        "non_promotion_notice": NON_PROMOTION_NOTICE,
    }


def rank_feature_column(rows: Sequence[Mapping[str, Any]], column: str) -> dict[str, Any]:
    values: list[float] = []
    labels: list[float] = []
    missing = 0
    for row in rows:
        value = optional_float(row.get(column))
        label = optional_float(row.get("yes"))
        if value is None or label not in (0.0, 1.0):
            missing += 1
            continue
        values.append(value)
        labels.append(label)
    coverage = len(values) / len(rows) if rows else 0.0
    correlation = abs(pearson(values, labels)) if len(values) >= 2 else 0.0
    variance = sample_variance(values)
    return {
        "feature": column,
        "coverage": coverage,
        "missing_count": missing,
        "abs_label_correlation": correlation,
        "variance": variance,
        "score": coverage * correlation,
    }


def build_policy_mismatch_diagnostics(
    comparison_report: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not comparison_report:
        return {
            "status": "not_evaluated",
            "notes": ["No baseline-vs-feature-set comparison report was provided."],
        }
    holdout_delta = normalize_prefixed_delta(comparison_report.get("holdout_summary", {}))
    policy_delta = normalize_prefixed_delta(comparison_report.get("policy_summary", {}))
    notes: list[str] = []
    if probability_direction(holdout_delta) == "better" and policy_direction(policy_delta) == "worse":
        notes.append("probability_improved_policy_worsened")
    if optional_float(policy_delta.get("fee_total")) and float(policy_delta["fee_total"]) > 0:
        notes.append("fee_sensitivity_or_trade_mix_shift")
    if optional_float(policy_delta.get("max_drawdown")) and float(policy_delta["max_drawdown"]) > 0:
        notes.append("drawdown_worsened")
    if optional_float(policy_delta.get("trade_count")) and float(policy_delta["trade_count"]) < 0:
        notes.append("trade_count_shifted_down")
    if not notes:
        notes.append("no_obvious_probability_policy_mismatch")
    return {
        "status": "complete",
        "probability_delta": holdout_delta,
        "policy_delta": policy_delta,
        "notes": notes,
        "non_promotion_notice": NON_PROMOTION_NOTICE,
    }


def build_focused_edge_walk_forward_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    baseline_feature_columns: Sequence[str],
    slim_feature_columns: Sequence[str],
    selection_market_count: int,
    holdout_market_count: int,
    step_market_count: int | None = None,
    candidate_names: Sequence[str] = ("fast_logistic",),
    feature_pruning_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    engineered = engineer_kxbtc_features(rows)
    baseline_columns = default_model_feature_columns(baseline_feature_columns)
    slim_columns = [column for column in slim_feature_columns if column not in baseline_columns]
    candidate_columns = baseline_columns + slim_columns
    modeled = rows_with_numeric_features(engineered, candidate_columns)
    windows = build_walk_forward_windows(
        modeled,
        selection_market_count=selection_market_count,
        holdout_market_count=holdout_market_count,
        step_market_count=step_market_count or holdout_market_count,
    )
    window_reports = [
        build_edge_window_report(
            modeled,
            window,
            baseline_columns=baseline_columns,
            candidate_columns=candidate_columns,
            candidate_names=candidate_names,
        )
        for window in windows
    ]
    aggregate = aggregate_edge_windows(window_reports)
    verdict_report = build_edge_verdict_report(
        aggregate,
        feature_pruning_report=feature_pruning_report,
    )
    return {
        "schema_version": "kxbtc_focused_edge_walk_forward_report_v1",
        "raw_row_count": len(rows),
        "modeled_row_count_after_required_feature_dropna": len(modeled),
        "baseline_feature_count": len(baseline_columns),
        "slim_feature_count": len(slim_columns),
        "slim_feature_columns": list(slim_columns),
        "candidate_model_families": list(candidate_names),
        "selection_market_count": selection_market_count,
        "holdout_market_count": holdout_market_count,
        "step_market_count": step_market_count or holdout_market_count,
        "window_count": len(windows),
        "complete_window_count": sum(1 for item in window_reports if item["status"] == "complete"),
        "aggregate": aggregate,
        "edge_verdict": verdict_report["verdict"],
        "edge_verdict_rationale": verdict_report["rationale"],
        "model_family_instability": aggregate.get("model_family_instability"),
        "windows": window_reports,
        "non_promotion_notice": NON_PROMOTION_NOTICE,
    }


def build_edge_window_report(
    rows: Sequence[Mapping[str, Any]],
    window: Any,
    *,
    baseline_columns: Sequence[str],
    candidate_columns: Sequence[str],
    candidate_names: Sequence[str],
) -> dict[str, Any]:
    market_set = set(window.selection_markets + window.holdout_markets)
    window_rows = [dict(row) for row in rows if str(row.get("ticker")) in market_set]
    selection_rows = rows_for_markets(window_rows, window.selection_markets)
    holdout_rows = rows_for_markets(window_rows, window.holdout_markets)
    try:
        baseline = select_best_edge_arm(
            "baseline",
            train_rows=selection_rows,
            selection_rows=selection_rows,
            holdout_rows=holdout_rows,
            feature_columns=baseline_columns,
            candidate_names=candidate_names,
        )
        challenger = select_best_edge_arm(
            "baseline_plus_slim_coinbase_btc_market_structure",
            train_rows=selection_rows,
            selection_rows=selection_rows,
            holdout_rows=holdout_rows,
            feature_columns=candidate_columns,
            candidate_names=candidate_names,
        )
        return {
            "window": window.as_dict(),
            "status": "complete",
            "failure_reason": None,
            "baseline": baseline,
            "candidate": challenger,
            "probability_delta": prefixed_metric_delta(
                challenger["holdout_probability_metrics"],
                baseline["holdout_probability_metrics"],
                prefix="candidate_minus_baseline",
                keys=("brier_score", "log_loss", "roc_auc", "average_precision", "accuracy_50"),
            ),
            "policy_delta": prefixed_metric_delta(
                challenger["holdout_policy_metrics"],
                baseline["holdout_policy_metrics"],
                prefix="candidate_minus_baseline",
                keys=("net_pnl", "trade_count", "win_rate", "profit_factor", "max_drawdown"),
            ),
        }
    except Exception as exc:
        return {
            "window": window.as_dict(),
            "status": "skipped",
            "failure_reason": f"{exc.__class__.__name__}: {exc}",
        }


def select_best_edge_arm(
    arm_name: str,
    *,
    train_rows: Sequence[Mapping[str, Any]],
    selection_rows: Sequence[Mapping[str, Any]],
    holdout_rows: Sequence[Mapping[str, Any]],
    feature_columns: Sequence[str],
    candidate_names: Sequence[str],
) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    for candidate_name in candidate_names:
        report, trained = fit_and_report_candidate(
            candidate_name,
            train_rows=train_rows,
            evaluation_rows=list(selection_rows) + list(holdout_rows),
            feature_columns=feature_columns,
        )
        if trained is None:
            reports.append(report)
            continue
        predicted = rename_prediction_candidate(trained.predict_rows(selection_rows + holdout_rows), candidate_name)
        selection_predicted = rows_for_markets(
            predicted,
            [str(row.get("ticker")) for row in selection_rows if row.get("ticker")],
        )
        holdout_predicted = rows_for_markets(
            predicted,
            [str(row.get("ticker")) for row in holdout_rows if row.get("ticker")],
        )
        reports.append(
            {
                "candidate": candidate_name,
                "status": "complete",
                "selection_policy_metrics": summarize_policy_metrics(
                    simulate_policy(selection_predicted)
                ),
                "holdout_policy_metrics": summarize_policy_metrics(
                    simulate_policy(holdout_predicted)
                ),
                "selection_probability_metrics": probability_metrics(selection_predicted),
                "holdout_probability_metrics": probability_metrics(holdout_predicted),
                "holdout_calibration": calibration_buckets(holdout_predicted),
                "stress_scenarios": build_direct_policy_stress_scenarios(holdout_predicted),
            }
        )
    complete = [report for report in reports if report.get("status") == "complete"]
    if not complete:
        raise ValueError(f"no candidates completed for {arm_name}")
    selected = max(
        complete,
        key=lambda report: (
            optional_float(mapping_from(report["selection_policy_metrics"]).get("net_pnl")) or 0.0,
            optional_float(mapping_from(report["selection_policy_metrics"]).get("profit_factor")) or 0.0,
        ),
    )
    return {
        "name": arm_name,
        "selected_candidate": selected["candidate"],
        "candidate_reports": reports,
        "selection_probability_metrics": selected["selection_probability_metrics"],
        "holdout_probability_metrics": selected["holdout_probability_metrics"],
        "holdout_calibration": selected["holdout_calibration"],
        "selection_policy_metrics": selected["selection_policy_metrics"],
        "holdout_policy_metrics": selected["holdout_policy_metrics"],
        "stress_scenarios": selected["stress_scenarios"],
    }


def aggregate_edge_windows(window_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    complete = [report for report in window_reports if report.get("status") == "complete"]
    baseline_policy = aggregate_policy_metrics([report["baseline"] for report in complete])
    candidate_policy = aggregate_policy_metrics([report["candidate"] for report in complete])
    baseline_probability = aggregate_probability_metrics([report["baseline"] for report in complete])
    candidate_probability = aggregate_probability_metrics([report["candidate"] for report in complete])
    baseline_calibration = aggregate_calibration_metrics([report["baseline"] for report in complete])
    candidate_calibration = aggregate_calibration_metrics([report["candidate"] for report in complete])
    policy_delta = metric_delta(candidate_policy, baseline_policy)
    probability_delta = metric_delta(candidate_probability, baseline_probability)
    calibration_delta = metric_delta(candidate_calibration, baseline_calibration)
    stress_delta = aggregate_stress_delta(complete)
    selected_candidates = [
        str(report["candidate"].get("selected_candidate"))
        for report in complete
        if report.get("candidate")
    ]
    return {
        "complete_window_count": len(complete),
        "baseline_policy_metrics": baseline_policy,
        "candidate_policy_metrics": candidate_policy,
        "aggregate_policy_delta": policy_delta,
        "baseline_probability_metrics": baseline_probability,
        "candidate_probability_metrics": candidate_probability,
        "aggregate_probability_delta": probability_delta,
        "baseline_calibration_metrics": baseline_calibration,
        "candidate_calibration_metrics": candidate_calibration,
        "aggregate_calibration_delta": calibration_delta,
        "aggregate_stress_delta": stress_delta,
        "model_family_instability": {
            "selected_candidate_counts": count_values_text(selected_candidates),
            "selected_candidate_family_count": len(set(selected_candidates)),
            "status": "unstable" if len(set(selected_candidates)) > 1 else "stable_single_family",
        },
        "non_promotion_notice": NON_PROMOTION_NOTICE,
    }


def aggregate_policy_metrics(arms: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = [mapping_from(arm.get("holdout_policy_metrics")) for arm in arms]
    trade_count = sum(int(optional_float(item.get("trade_count")) or 0) for item in metrics)
    net_pnl = sum(optional_float(item.get("net_pnl")) or 0.0 for item in metrics)
    fee_total = sum(optional_float(item.get("fee_total")) or 0.0 for item in metrics)
    return {
        "window_count": len(metrics),
        "trade_count": trade_count,
        "net_pnl": net_pnl,
        "fee_total": fee_total,
        "win_rate": mean_metric(metrics, "win_rate"),
        "profit_factor": mean_metric(metrics, "profit_factor"),
        "max_drawdown": max(
            (optional_float(item.get("max_drawdown")) or 0.0 for item in metrics),
            default=0.0,
        ),
    }


def aggregate_probability_metrics(arms: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = [mapping_from(arm.get("holdout_probability_metrics")) for arm in arms]
    return {
        "window_count": len(metrics),
        "rows": sum(int(optional_float(item.get("rows")) or 0) for item in metrics),
        "brier_score": mean_metric(metrics, "brier_score"),
        "log_loss": mean_metric(metrics, "log_loss"),
        "roc_auc": mean_metric(metrics, "roc_auc"),
        "average_precision": mean_metric(metrics, "average_precision"),
        "accuracy_50": mean_metric(metrics, "accuracy_50"),
    }


def aggregate_calibration_metrics(arms: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = [mapping_from(arm.get("holdout_calibration")) for arm in arms]
    return {
        "window_count": len(metrics),
        "expected_calibration_error": mean_metric(metrics, "expected_calibration_error"),
    }


def aggregate_stress_delta(window_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    baseline = aggregate_named_stress(window_reports, "baseline")
    candidate = aggregate_named_stress(window_reports, "candidate")
    return {
        name: metric_delta(candidate.get(name, {}), baseline.get(name, {}))
        for name in sorted(set(baseline) | set(candidate))
    }


def aggregate_named_stress(
    window_reports: Sequence[Mapping[str, Any]],
    arm_name: str,
) -> dict[str, dict[str, Any]]:
    output: dict[str, list[Mapping[str, Any]]] = {}
    for report in window_reports:
        arm = mapping_from(report.get(arm_name))
        for scenario in arm.get("stress_scenarios", ()):
            if not isinstance(scenario, Mapping):
                continue
            name = str(scenario.get("name"))
            output.setdefault(name, []).append(mapping_from(scenario.get("metrics")))
    return {name: aggregate_policy_metric_rows(rows) for name, rows in output.items()}


def aggregate_policy_metric_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "net_pnl": sum(optional_float(row.get("net_pnl")) or 0.0 for row in rows),
        "trade_count": sum(int(optional_float(row.get("trade_count")) or 0) for row in rows),
        "win_rate": mean_metric(rows, "win_rate"),
        "profit_factor": mean_metric(rows, "profit_factor"),
        "max_drawdown": max((optional_float(row.get("max_drawdown")) or 0.0 for row in rows), default=0.0),
    }


def metric_delta(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    keys = sorted(set(candidate) | set(baseline))
    output: dict[str, Any] = {}
    for key in keys:
        candidate_value = optional_float(candidate.get(key))
        baseline_value = optional_float(baseline.get(key))
        if candidate_value is not None and baseline_value is not None:
            output[key] = candidate_value - baseline_value
    return output


def normalize_prefixed_delta(value: Any) -> dict[str, Any]:
    output: dict[str, Any] = {}
    if not isinstance(value, Mapping):
        return output
    for key, metric_value in value.items():
        metric = str(key).split("_coinbase_btc_market_structure_minus_baseline")[0]
        metric = metric.split("_candidate_minus_baseline")[0]
        output[metric] = metric_value
    return output


def summarize_feature_pruning(report: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    return {
        "schema_version": report.get("schema_version"),
        "retained_feature_count": report.get("retained_feature_count"),
        "slim_feature_columns": list(report.get("slim_feature_columns", ())),
        "policy_mismatch_diagnostics": report.get("policy_mismatch_diagnostics"),
    }


def mapping_from(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def mean_metric(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    values = [optional_float(row.get(key)) for row in rows]
    real_values = [value for value in values if value is not None]
    return sum(real_values) / len(real_values) if real_values else None


def pearson(values: Sequence[float], labels: Sequence[float]) -> float:
    if len(values) != len(labels) or len(values) < 2:
        return 0.0
    mean_values = sum(values) / len(values)
    mean_labels = sum(labels) / len(labels)
    numerator = sum(
        (value - mean_values) * (label - mean_labels)
        for value, label in zip(values, labels, strict=True)
    )
    value_var = sum((value - mean_values) ** 2 for value in values)
    label_var = sum((label - mean_labels) ** 2 for label in labels)
    denominator = (value_var * label_var) ** 0.5
    return numerator / denominator if denominator else 0.0


def sample_variance(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean_value = sum(values) / len(values)
    return sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)


def count_values_text(values: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts
