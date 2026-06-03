import json
from pathlib import Path

import pytest

from alphadb.model_evaluation.artifacts import COMPARABILITY_FIELDS, audit_model_artifacts
from alphadb.model_evaluation.edge import (
    build_edge_verdict_report,
    build_feature_pruning_report,
    build_focused_edge_walk_forward_report,
)
from alphadb.model_evaluation.features import (
    default_model_feature_columns,
    engineer_kxbtc_features,
    resolve_feature_groups,
)
from alphadb.model_evaluation.live_attribution import summary_from_payload
from alphadb.model_evaluation.metrics import simulate_policy
from alphadb.model_evaluation.models import (
    build_feature_ablation_report,
    build_feature_set_comparison_report,
    compare_candidate_model_families,
)
from alphadb.model_evaluation.money_printer import (
    build_fillability_probe_report,
    build_nested_oos_edge_verdict_report,
    build_stale_quote_alpha_report,
    build_top_ev_sniper_policy_report,
)
from alphadb.model_evaluation.policy import build_holdout_policy_selection_report
from alphadb.model_evaluation.walk_forward import build_walk_forward_report


def prediction_rows(markets: int = 8) -> list[dict]:
    rows = []
    for market_index in range(markets):
        yes = market_index % 2
        for candidate in ("weak", "strong"):
            for offset in (1, 2):
                if candidate == "strong":
                    probability = 0.82 if yes else 0.18
                else:
                    probability = 0.54 if yes else 0.46
                rows.append(
                    {
                        "ticker": f"KXBTC15M-{market_index:03d}",
                        "market_open_time": f"2026-05-30T{market_index:02d}:00:00Z",
                        "decision_timestamp": f"2026-05-30T{market_index:02d}:12:00Z",
                        "candidate": candidate,
                        "decision_minute_offset": offset,
                        "yes": yes,
                        "p_yes": probability,
                        "yes_ask": 0.45 if yes else 0.55,
                        "no_ask": 0.55 if yes else 0.45,
                    }
                )
    return rows


def training_rows(markets: int = 12) -> list[dict]:
    rows = []
    for market_index in range(markets):
        yes = market_index % 2
        signal = 1.0 if yes else -1.0
        rows.append(
            {
                "ticker": f"KXBTC15M-{market_index:03d}",
                "market_open_time": f"2026-05-30T{market_index:02d}:00:00Z",
                "decision_timestamp": f"2026-05-30T{market_index:02d}:12:00Z",
                "decision_minute_offset": 12,
                "time_since_open_seconds": 720,
                "time_to_close_seconds": 180,
                "yes": yes,
                "yes_bid": 0.39 + (0.05 * yes),
                "yes_ask": 0.43 + (0.05 * yes),
                "no_bid": 0.53 - (0.05 * yes),
                "no_ask": 0.57 - (0.05 * yes),
                "last_trade_count_fp": 3 + market_index,
                "last_trade_timestamp": f"2026-05-30T{market_index:02d}:10:00Z",
                "external_return_1": signal * 0.02,
                "external_log_return_1": signal * 0.019,
                "external_close_to_open_return": signal * 0.015,
                "external_realized_vol_5": 0.01 + market_index * 0.001,
                "external_realized_vol_15": 0.02 + market_index * 0.001,
                "external_volume": 10 + market_index,
                "external_close": 100.0 + signal,
                "payout_threshold": 100.0,
                "signal": signal,
            }
        )
    return rows


def add_dataset_contract(row: dict) -> dict:
    output = dict(row)
    for field in COMPARABILITY_FIELDS:
        output[field] = f"{field}.v1"
    output["dataset_id"] = "dataset-test"
    return output


def test_artifact_audit_separates_current_artifacts_from_legacy_backtests(tmp_path: Path) -> None:
    root = tmp_path / "research" / "btc_kalshi"
    training_dir = root / "results" / "20260530T172835Z_kxbtc_model_training_baseline"
    training_dir.mkdir(parents=True)
    (training_dir / "metrics.json").write_text(
        json.dumps({"schema_version": "kxbtc_model_training_v1", "row_count": 12}),
        encoding="utf-8",
    )
    (training_dir / "predictions.json").write_text(
        json.dumps([add_dataset_contract(row) for row in prediction_rows(4)]),
        encoding="utf-8",
    )
    (training_dir / "model_logistic.joblib").write_text("binary-placeholder", encoding="utf-8")
    legacy_dir = root / "results" / "20260529T220709Z_backtest"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "metrics.json").write_text(
        json.dumps({"selected_model": "logistic", "rows": 8605}),
        encoding="utf-8",
    )

    report = audit_model_artifacts(root).as_dict()

    records = {record["artifact_type"]: record for record in report["records"]}
    assert report["counts"]["current_kxbtc15m"] >= 3
    assert records["prediction_artifact"]["dataset_contract_status"] == "complete"
    assert records["legacy_backtest_report"]["evidence_track"] == "legacy_exploratory"
    assert records["legacy_backtest_report"]["promotion_grade_eligible"] is False


def test_holdout_policy_selection_selects_on_selection_and_scores_holdout() -> None:
    report = build_holdout_policy_selection_report(prediction_rows())

    assert report["schema_version"] == "kxbtc_model_holdout_policy_selection_v1"
    assert set(report["split"]["selection_markets"]).isdisjoint(report["split"]["holdout_markets"])
    assert report["selected_policy"]["candidate"] == "strong"
    assert report["holdout"]["split_role"] == "holdout"
    assert report["holdout"]["policy_metrics"]["trade_count"] > 0
    assert {scenario["split_role"] for scenario in report["stress_scenarios"]} == {
        "holdout_stress"
    }
    assert "does not authorize" in report["non_promotion_notice"]


def test_walk_forward_report_aggregates_complete_windows() -> None:
    report = build_walk_forward_report(
        prediction_rows(10),
        selection_market_count=3,
        holdout_market_count=2,
        step_market_count=2,
    )

    assert report["schema_version"] == "kxbtc_model_walk_forward_report_v1"
    assert report["complete_window_count"] >= 2
    assert report["aggregate"]["net_pnl_total"] > 0
    assert report["aggregate"]["selected_candidate_counts"]["strong"] >= 1


def test_feature_engineering_adds_public_safe_features_and_rejects_lookahead() -> None:
    engineered = engineer_kxbtc_features(training_rows(1))

    assert engineered[0]["yes_spread"] == pytest.approx(0.04)
    assert engineered[0]["last_trade_age_seconds"] == 120
    assert "moneyness_dollars" in engineered[0]
    assert engineered[0]["coinbase_btc_momentum_1m"] == pytest.approx(-0.02)
    assert engineered[0]["coinbase_btc_threshold_distance_pct"] == pytest.approx(-0.01)
    assert engineered[0]["coinbase_btc_candle_shock_5m"] > 0

    leaky = training_rows(1)[0]
    with pytest.raises(ValueError, match="no-lookahead"):
        engineer_kxbtc_features(
            [
                {
                    **leaky,
                    "external_source_event_timestamp_utc": "2026-05-30T00:13:00Z",
                }
            ]
        )


def test_feature_group_ablation_report_and_leaky_column_rejection() -> None:
    feature_columns = [
        "decision_minute_offset",
        "time_since_open_seconds",
        "yes_bid",
        "yes_ask",
        "external_return_1",
        "signal",
    ]

    report = build_feature_ablation_report(
        training_rows(),
        feature_columns=feature_columns,
        candidate_name="logistic",
    )

    assert report["schema_version"] == "kxbtc_feature_group_ablation_report_v1"
    assert any(item["name"] == "full" and item["status"] == "complete" for item in report["ablations"])
    assert any(item["name"] == "without_kalshi_quote_state" for item in report["ablations"])

    with pytest.raises(ValueError, match="leaky"):
        resolve_feature_groups(["external_return_1", "settlement_value_dollars"])


def test_default_model_features_freeze_raw_x_counts_but_keep_explicit_grouping() -> None:
    feature_columns = [
        "decision_minute_offset",
        "time_since_open_seconds",
        "x_counts_btc_general_15m",
        "x_attention_btc_general_15m_vs_24h_z",
        "coinbase_btc_momentum_1m",
    ]

    default_columns = default_model_feature_columns(feature_columns)
    explicit_groups = resolve_feature_groups(feature_columns)

    assert "x_counts_btc_general_15m" not in default_columns
    assert "x_attention_btc_general_15m_vs_24h_z" not in default_columns
    assert "coinbase_btc_momentum_1m" in default_columns
    assert explicit_groups["x_external_signal_state"] == [
        "x_counts_btc_general_15m",
        "x_attention_btc_general_15m_vs_24h_z",
    ]


def test_coinbase_btc_feature_set_comparison_report_uses_same_split_and_deltas() -> None:
    report = build_feature_set_comparison_report(
        training_rows(12),
        feature_columns=[
            "decision_minute_offset",
            "time_since_open_seconds",
            "yes_bid",
            "yes_ask",
            "no_ask",
            "signal",
            "external_return_1",
            "external_log_return_1",
            "external_close_to_open_return",
            "external_realized_vol_5",
            "external_realized_vol_15",
            "external_volume",
            "external_close",
            "payout_threshold",
            "x_counts_btc_general_15m",
        ],
    )

    assert report["schema_version"] == "kxbtc_feature_set_comparison_report_v1"
    assert report["modeled_row_count_after_required_feature_dropna"] == 12
    assert "x_counts_btc_general_15m" in report["default_excluded_feature_columns"]
    assert report["added_feature_group"] == "coinbase_btc_market_structure"
    assert report["added_feature_columns"]
    assert report["baseline"]["feature_count"] < report[
        "baseline_plus_coinbase_btc_market_structure"
    ]["feature_count"]
    assert "brier_score_coinbase_btc_market_structure_minus_baseline" in report[
        "holdout_summary"
    ]
    assert "does not authorize" in report["non_promotion_notice"]


def test_coinbase_btc_feature_group_is_ablatable() -> None:
    report = build_feature_ablation_report(
        training_rows(),
        feature_columns=[
            "decision_minute_offset",
            "time_since_open_seconds",
            "yes_bid",
            "yes_ask",
            "no_ask",
            "coinbase_btc_momentum_1m",
            "coinbase_btc_candle_shock_5m",
        ],
        candidate_name="logistic",
    )

    assert any(
        item["name"] == "without_coinbase_btc_market_structure"
        for item in report["ablations"]
    )
    assert any(
        item["name"] == "only_coinbase_btc_market_structure"
        for item in report["ablations"]
    )


def test_policy_fee_stress_can_recompute_stale_fee_columns() -> None:
    rows = [
        {
            "ticker": "KXBTC15M-FEE",
            "decision_minute_offset": 12,
            "yes": 1,
            "p_yes": 0.7,
            "yes_ask": 0.5,
            "no_ask": 0.5,
            "yes_fee": 0.0,
            "no_fee": 0.0,
        }
    ]

    base = simulate_policy(rows)
    stressed = simulate_policy(rows, taker_fee_multiplier=0.14, recompute_fees=True)

    assert base["fee_total"] == 0.0
    assert stressed["fee_total"] > base["fee_total"]
    assert stressed["net_pnl"] < base["net_pnl"]


def test_candidate_model_family_comparison_reports_candidates_and_optional_skips() -> None:
    report = compare_candidate_model_families(
        training_rows(),
        feature_columns=["decision_minute_offset", "time_since_open_seconds", "signal"],
        candidate_names=[
            "logistic",
            "extra_trees",
            "hist_gradient_boosting",
            "lightgbm",
            "simple_ensemble",
            "catboost",
        ],
    )

    statuses = {item["candidate"]: item["status"] for item in report["candidate_reports"]}
    assert statuses["logistic"] == "complete"
    assert statuses["extra_trees"] == "complete"
    assert statuses["hist_gradient_boosting"] == "complete"
    assert statuses["lightgbm"] in {"complete", "skipped"}
    assert statuses["simple_ensemble"] == "complete"
    assert statuses["catboost"] in {"complete", "skipped"}
    assert report["policy_selection_report"]["selected_policy"]["candidate"] in {
        "logistic",
        "extra_trees",
        "simple_ensemble",
        "catboost",
    }
    assert "does not authorize" in report["non_promotion_notice"]
    assert report["model_family_instability"]["status"] == "single_split_only"


def test_live_attribution_context_is_informational_and_warns_on_small_samples() -> None:
    summary = summary_from_payload(
        {
            "headline": {
                "actual_dollar_pnl": 8.45,
                "one_contract_normalized_pnl": 1.63,
                "total_markets": 98,
            },
            "data_quality": {
                "total_rows": 98,
                "pnl_included_rows": 83,
                "excluded_from_pnl": 15,
            },
            "filled_trade_breakdowns": {
                "by_selected_side": [{"bucket": "yes", "count": 10}],
            },
        }
    ).as_dict()

    assert summary["promotion_status"] == "informational_only"
    assert "small_sample" in summary["warnings"]
    assert "excluded_coverage_present" in summary["warnings"]
    assert summary["pnl"]["actual_dollar_pnl"] == 8.45
    assert summary["breakdowns"]["by_selected_side"][0]["bucket"] == "yes"


def test_edge_verdict_contract_covers_all_outcomes() -> None:
    common = {"complete_window_count": 3}

    edge = build_edge_verdict_report(
        {
            **common,
            "aggregate_probability_delta": {"brier_score": -0.01, "log_loss": -0.01},
            "aggregate_policy_delta": {
                "net_pnl": 10.0,
                "profit_factor": 0.2,
                "win_rate": 0.1,
                "max_drawdown": -0.01,
            },
            "aggregate_stress_delta": {"worse_spread_1_cents": {"net_pnl": 3.0}},
        }
    )
    revise = build_edge_verdict_report(
        {
            **common,
            "aggregate_probability_delta": {"brier_score": -0.01, "log_loss": -0.01},
            "aggregate_policy_delta": {
                "net_pnl": -5.0,
                "profit_factor": -0.1,
                "win_rate": -0.1,
                "max_drawdown": 0.1,
            },
        }
    )
    stop = build_edge_verdict_report(
        {
            **common,
            "aggregate_probability_delta": {"brier_score": 0.01, "log_loss": 0.01},
            "aggregate_policy_delta": {
                "net_pnl": -5.0,
                "profit_factor": -0.1,
                "win_rate": -0.1,
                "max_drawdown": 0.1,
            },
        }
    )
    inconclusive = build_edge_verdict_report(
        {
            "complete_window_count": 0,
            "aggregate_probability_delta": {},
            "aggregate_policy_delta": {},
        }
    )

    assert edge["verdict"]["value"] == "edge_candidate"
    assert revise["verdict"]["value"] == "revise"
    assert revise["verdict"]["reason"] == "probability_improved_but_policy_worsened"
    assert stop["verdict"]["value"] == "stop"
    assert inconclusive["verdict"]["value"] == "inconclusive"
    assert set(edge["verdict_contract"]["allowed_values"]) == {
        "edge_candidate",
        "revise",
        "stop",
        "inconclusive",
    }
    assert "does not authorize" in edge["non_promotion_notice"]


def edge_feature_columns() -> list[str]:
    return [
        "decision_minute_offset",
        "time_since_open_seconds",
        "yes_bid",
        "yes_ask",
        "no_ask",
        "external_return_1",
        "external_log_return_1",
        "external_close_to_open_return",
        "external_realized_vol_5",
        "external_realized_vol_15",
        "external_volume",
        "external_close",
        "payout_threshold",
        "x_counts_btc_general_15m",
    ]


def leakage_feature_columns() -> list[str]:
    return edge_feature_columns() + [
        "coinbase_btc_train_signal",
        "coinbase_btc_holdout_leak_signal",
    ]


def leakage_rows(markets: int = 12) -> list[dict]:
    rows = []
    for market_index in range(markets):
        yes = market_index % 2
        signal = 1.0 if yes else -1.0
        row = training_rows(markets)[market_index]
        row["external_return_1"] = 0.0
        row["external_log_return_1"] = 0.0
        row["external_close_to_open_return"] = 0.0
        row["external_close"] = 100.0
        row["coinbase_btc_train_signal"] = signal if market_index < 4 else 0.0
        row["coinbase_btc_holdout_leak_signal"] = 0.0 if market_index < 4 else signal
        rows.append(row)
    return rows


def test_feature_pruning_produces_slim_set_and_policy_mismatch_notes() -> None:
    report = build_feature_pruning_report(
        training_rows(14),
        feature_columns=edge_feature_columns(),
        top_n=4,
        comparison_report={
            "holdout_summary": {
                "brier_score_coinbase_btc_market_structure_minus_baseline": -0.01,
                "log_loss_coinbase_btc_market_structure_minus_baseline": -0.02,
            },
            "policy_summary": {
                "net_pnl_coinbase_btc_market_structure_minus_baseline": -10.0,
                "fee_total_coinbase_btc_market_structure_minus_baseline": 2.0,
                "max_drawdown_coinbase_btc_market_structure_minus_baseline": 0.1,
                "trade_count_coinbase_btc_market_structure_minus_baseline": -1,
            },
        },
    )

    assert report["schema_version"] == "kxbtc_coinbase_btc_feature_pruning_report_v1"
    assert 0 < report["retained_feature_count"] <= 4
    assert all(column.startswith("coinbase_btc_") for column in report["slim_feature_columns"])
    assert "x_counts_btc_general_15m" not in report["slim_feature_columns"]
    assert "probability_improved_policy_worsened" in report[
        "policy_mismatch_diagnostics"
    ]["notes"]
    assert "does not authorize" in report["non_promotion_notice"]


def test_nested_oos_edge_verdict_selects_features_inside_each_window() -> None:
    rows = leakage_rows(12)
    global_pruning = build_feature_pruning_report(
        rows,
        feature_columns=leakage_feature_columns(),
        top_n=1,
    )

    report = build_nested_oos_edge_verdict_report(
        rows,
        feature_columns=leakage_feature_columns(),
        top_n=1,
        selection_market_count=4,
        holdout_market_count=2,
        step_market_count=2,
        candidate_names=("fast_logistic",),
    )

    assert report["schema_version"] == "kxbtc_nested_oos_edge_verdict_report_v1"
    assert global_pruning["slim_feature_columns"] == ["coinbase_btc_holdout_leak_signal"]
    assert report["windows"][0]["selected_slim_feature_columns"] == [
        "coinbase_btc_train_signal"
    ]
    assert report["diagnostics"]["required_positive_window_count"] >= 1
    assert report["money_printer_verdict"]["value"] in {"continue", "revise", "kill"}
    assert "x_external_signal_state" in report["default_excluded_feature_groups"]
    assert "does not authorize" in report["non_promotion_notice"]


def test_focused_edge_walk_forward_report_uses_slim_features_and_contract() -> None:
    pruning = build_feature_pruning_report(
        training_rows(16),
        feature_columns=edge_feature_columns(),
        top_n=3,
    )

    report = build_focused_edge_walk_forward_report(
        training_rows(16),
        baseline_feature_columns=edge_feature_columns(),
        slim_feature_columns=pruning["slim_feature_columns"],
        selection_market_count=4,
        holdout_market_count=2,
        step_market_count=2,
        candidate_names=("fast_logistic",),
        feature_pruning_report=pruning,
    )

    assert report["schema_version"] == "kxbtc_focused_edge_walk_forward_report_v1"
    assert report["complete_window_count"] >= 1
    assert report["slim_feature_columns"] == pruning["slim_feature_columns"]
    assert "aggregate_probability_delta" in report["aggregate"]
    assert "aggregate_calibration_delta" in report["aggregate"]
    assert "aggregate_policy_delta" in report["aggregate"]
    assert "worse_spread_1_cents" in report["aggregate"]["aggregate_stress_delta"]
    assert report["model_family_instability"]["status"] == "stable_single_family"
    assert report["edge_verdict"]["value"] in {
        "edge_candidate",
        "revise",
        "stop",
        "inconclusive",
    }
    assert "does not authorize" in report["non_promotion_notice"]


def stale_quote_fixture_rows() -> list[dict]:
    base = {
        "ticker": "KXBTC15M-STALENESS",
        "market_open_time": "2026-05-30T00:00:00Z",
        "decision_minute_offset": 1,
        "time_since_open_seconds": 60,
        "time_to_close_seconds": 840,
        "yes": 1,
        "yes_bid": 0.48,
        "yes_ask": 0.50,
        "no_bid": 0.48,
        "no_ask": 0.50,
        "last_trade_count_fp": 10,
        "last_trade_timestamp": "2026-05-30T00:00:30Z",
        "external_open": 100.0,
        "external_high": 100.0,
        "external_low": 100.0,
        "external_volume": 10,
        "external_return_1": 0.0,
        "external_log_return_1": 0.0,
        "external_close_to_open_return": 0.0,
        "external_realized_vol_5": 0.01,
        "external_realized_vol_15": 0.02,
        "external_close": 100.0,
        "payout_threshold": 102.0,
    }
    moved = {
        **base,
        "decision_timestamp": "2026-05-30T00:01:00Z",
    }
    stale = {
        **base,
        "decision_timestamp": "2026-05-30T00:01:30Z",
        "time_since_open_seconds": 90,
        "time_to_close_seconds": 810,
        "external_close": 102.0,
        "external_return_1": 0.02,
        "external_log_return_1": 0.0198,
        "external_close_to_open_return": 0.02,
        "yes_bid": 0.481,
        "yes_ask": 0.501,
        "no_bid": 0.479,
        "no_ask": 0.499,
    }
    return [moved, stale]


def test_stale_quote_alpha_detector_finds_btc_move_before_quote_reaction() -> None:
    report = build_stale_quote_alpha_report(
        stale_quote_fixture_rows(),
        windows_seconds=(30, 60),
        min_btc_move_cents=0.5,
        quote_reaction_ratio=0.5,
    )

    assert report["schema_version"] == "kxbtc_stale_quote_alpha_report_v1"
    assert report["candidate_row_count"] == 1
    candidate = report["candidate_rows"][0]
    assert candidate["side"] == "yes"
    assert candidate["btc_implied_probability_move_cents"] > candidate[
        "kalshi_quote_move_cents"
    ]
    assert candidate["threshold_proximity_bucket"] == "near_threshold"
    assert report["regime_breakdowns"]["side"]["yes"]["count"] == 1
    assert "does not authorize" in report["non_promotion_notice"]


def test_top_ev_sniper_policy_report_buckets_holdout_opportunities() -> None:
    rows = training_rows(16)
    nested = build_nested_oos_edge_verdict_report(
        rows,
        feature_columns=edge_feature_columns(),
        top_n=3,
        selection_market_count=4,
        holdout_market_count=2,
        step_market_count=2,
        candidate_names=("fast_logistic",),
    )

    report = build_top_ev_sniper_policy_report(
        rows,
        feature_columns=edge_feature_columns(),
        nested_oos_report=nested,
        fee_multiplier=0.14,
        friction_spread_cents=1.0,
    )

    assert report["schema_version"] == "kxbtc_top_ev_sniper_policy_report_v1"
    assert report["ranking"] == "predicted_ev_at_executable_ask_after_fees_and_friction"
    assert "top_10_pct" in report["buckets"]
    assert "realized_ev_per_trade" in report["buckets"]["top_10_pct"]
    assert report["policy_filters"]["selection_scope"] == "fixed_before_holdout_bucket_scoring"
    assert report["decision"]["value"] in {"continue", "revise", "kill"}
    assert "does not authorize" in report["non_promotion_notice"]


def test_fillability_probe_report_compares_simulated_fillable_and_filled() -> None:
    report = build_fillability_probe_report(
        [
            {
                "decision_timestamp": "2026-05-30T00:01:00Z",
                "btc_reference_price": 100.0,
                "kalshi_best_ask": 0.50,
                "simulated_ask": 0.50,
                "available_size": 5,
                "spread": 0.02,
                "predicted_probability": 0.58,
                "predicted_ev": 0.05,
                "stale_quote_score": 3.0,
                "order_intent": "buy_yes",
                "order_sent": True,
                "fill_status": "partial",
                "filled_quantity": 2,
                "intended_contracts": 5,
                "latency_ms": 45,
                "post_trade_quote_movement": 0.03,
                "settlement_result": "yes",
                "realized_pnl": 0.9,
            },
            {
                "decision_timestamp": "2026-05-30T00:02:00Z",
                "kalshi_best_ask": 0.54,
                "simulated_ask": 0.50,
                "available_size": 0,
                "predicted_ev": 0.04,
            },
        ]
    )

    assert report["schema_version"] == "kxbtc_fillability_probe_report_v1"
    assert report["counts"]["simulated_opportunities"] == 2
    assert report["counts"]["fillable_opportunities"] == 1
    assert report["counts"]["filled_opportunities"] == 1
    assert report["counts"]["partial_fill_count"] == 1
    assert report["pnl"]["realized_pnl_per_filled_trade"] == pytest.approx(0.9)
    assert report["mode"] == "live_data_paper_or_observation_only"
    assert "does not authorize" in report["non_promotion_notice"]
