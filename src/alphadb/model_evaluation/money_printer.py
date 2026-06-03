"""Fast KXBTC15M money-printer validation reports."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from typing import Any

from alphadb.model_evaluation.edge import (
    COINBASE_BTC_GROUP,
    aggregate_edge_windows,
    build_edge_window_report,
    build_feature_pruning_report,
    mapping_from,
)
from alphadb.model_evaluation.features import (
    default_model_feature_columns,
    engineer_kxbtc_features,
    parse_datetime,
    resolve_feature_groups,
)
from alphadb.model_evaluation.metrics import (
    max_drawdown,
    optional_float,
    taker_fee,
)
from alphadb.model_evaluation.models import (
    append_engineered_group_columns,
    fit_and_report_candidate,
    rename_prediction_candidate,
    rows_for_markets,
    rows_with_numeric_features,
)
from alphadb.model_evaluation.walk_forward import build_walk_forward_windows

MONEY_PRINTER_NOTICE = (
    "This money-printer validation report informs research only and does not authorize "
    "model promotion, live trading, Current MVP changes, or target-platform cutover."
)


def build_nested_oos_edge_verdict_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_columns: Sequence[str],
    top_n: int = 8,
    selection_market_count: int,
    holdout_market_count: int,
    step_market_count: int | None = None,
    candidate_names: Sequence[str] = ("fast_logistic",),
) -> dict[str, Any]:
    engineered = engineer_kxbtc_features(rows)
    default_columns = default_model_feature_columns(feature_columns)
    all_columns = append_engineered_group_columns(default_columns, engineered, COINBASE_BTC_GROUP)
    groups = resolve_feature_groups(all_columns)
    coinbase_columns = set(groups.get(COINBASE_BTC_GROUP, []))
    baseline_columns = [column for column in all_columns if column not in coinbase_columns]
    modeled = rows_with_numeric_features(engineered, all_columns)
    windows = build_walk_forward_windows(
        modeled,
        selection_market_count=selection_market_count,
        holdout_market_count=holdout_market_count,
        step_market_count=step_market_count or holdout_market_count,
    )
    window_reports = [
        build_nested_oos_window_report(
            modeled,
            window,
            baseline_columns=baseline_columns,
            all_feature_columns=all_columns,
            top_n=top_n,
            candidate_names=candidate_names,
        )
        for window in windows
    ]
    aggregate = aggregate_edge_windows(window_reports)
    diagnostics = nested_window_diagnostics(window_reports, aggregate)
    verdict = nested_money_printer_verdict(diagnostics)
    return {
        "schema_version": "kxbtc_nested_oos_edge_verdict_report_v1",
        "raw_row_count": len(rows),
        "modeled_row_count_after_required_feature_dropna": len(modeled),
        "selection_market_count": selection_market_count,
        "holdout_market_count": holdout_market_count,
        "step_market_count": step_market_count or holdout_market_count,
        "candidate_model_families": list(candidate_names),
        "top_n": top_n,
        "baseline_feature_count": len(baseline_columns),
        "candidate_feature_group": COINBASE_BTC_GROUP,
        "default_excluded_feature_groups": ["x_external_signal_state"],
        "selection_scope": "feature/model/policy choices are selected inside each window before holdout scoring",
        "holdout_tuning_status": "none_detected_by_contract",
        "window_count": len(windows),
        "complete_window_count": aggregate.get("complete_window_count"),
        "aggregate": aggregate,
        "diagnostics": diagnostics,
        "money_printer_verdict": verdict,
        "windows": window_reports,
        "non_promotion_notice": MONEY_PRINTER_NOTICE,
    }


def build_nested_oos_window_report(
    rows: Sequence[Mapping[str, Any]],
    window: Any,
    *,
    baseline_columns: Sequence[str],
    all_feature_columns: Sequence[str],
    top_n: int,
    candidate_names: Sequence[str],
) -> dict[str, Any]:
    selection_rows = rows_for_markets(rows, window.selection_markets)
    pruning = build_feature_pruning_report(
        selection_rows,
        feature_columns=all_feature_columns,
        top_n=top_n,
    )
    slim_columns = [
        column
        for column in pruning["slim_feature_columns"]
        if column not in set(baseline_columns)
    ]
    candidate_columns = list(baseline_columns) + slim_columns
    candidate_rows = rows_with_numeric_features(rows, candidate_columns)
    report = build_edge_window_report(
        candidate_rows,
        window,
        baseline_columns=baseline_columns,
        candidate_columns=candidate_columns,
        candidate_names=candidate_names,
    )
    report["selected_slim_feature_columns"] = slim_columns
    report["feature_pruning_summary"] = {
        "schema_version": pruning["schema_version"],
        "selection_row_count": len(selection_rows),
        "retained_feature_count": pruning["retained_feature_count"],
        "slim_feature_columns": slim_columns,
        "top_rankings": pruning["rankings"][:top_n],
    }
    report["selection_scope"] = "window_selection_only"
    report["holdout_tuning_status"] = "none"
    return report


def nested_window_diagnostics(
    window_reports: Sequence[Mapping[str, Any]],
    aggregate: Mapping[str, Any],
) -> dict[str, Any]:
    complete = [report for report in window_reports if report.get("status") == "complete"]
    deltas = [window_policy_delta(report) for report in complete]
    positive = [value for value in deltas if value > 0]
    negative = [value for value in deltas if value < 0]
    positive_sum = sum(positive)
    largest_positive = max(positive, default=0.0)
    concentration = largest_positive / positive_sum if positive_sum > 0 else None
    stress_delta = mapping_from(aggregate.get("aggregate_stress_delta"))
    punitive = mapping_from(
        stress_delta.get("fees_x_2_worse_spread_1_cents")
        or stress_delta.get("worse_spread_1_cents")
    )
    complete_count = len(complete)
    required_positive = math.ceil(0.6 * complete_count) if complete_count else 0
    return {
        "window_pnl_deltas": deltas,
        "positive_window_count": len(positive),
        "negative_window_count": len(negative),
        "flat_window_count": sum(1 for value in deltas if value == 0),
        "required_positive_window_count": required_positive,
        "median_window_delta": median(deltas),
        "aggregate_policy_delta": aggregate.get("aggregate_policy_delta"),
        "largest_positive_window_delta": largest_positive,
        "single_window_positive_contribution_share": concentration,
        "single_window_concentration_status": (
            "concentrated" if concentration is not None and concentration > 0.5 else "not_concentrated"
        ),
        "punitive_friction_delta": punitive,
        "punitive_friction_positive": (optional_float(punitive.get("net_pnl")) or 0.0) > 0,
        "model_family_instability": aggregate.get("model_family_instability"),
        "holdout_tuning_status": "none_detected_by_contract",
    }


def nested_money_printer_verdict(diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    positive = int(optional_float(diagnostics.get("positive_window_count")) or 0)
    required = int(optional_float(diagnostics.get("required_positive_window_count")) or 0)
    median_delta = optional_float(diagnostics.get("median_window_delta")) or 0.0
    aggregate_delta = optional_float(
        mapping_from(diagnostics.get("aggregate_policy_delta")).get("net_pnl")
    ) or 0.0
    concentration = optional_float(diagnostics.get("single_window_positive_contribution_share"))
    punitive_ok = bool(diagnostics.get("punitive_friction_positive"))
    if (
        positive >= required
        and median_delta > 0
        and aggregate_delta > 0
        and punitive_ok
        and (concentration is None or concentration <= 0.5)
    ):
        return {
            "value": "continue",
            "reason": "clean_nested_oos_bars_passed",
        }
    if aggregate_delta <= 0 or median_delta <= 0 or positive < max(1, required - 1):
        return {
            "value": "kill",
            "reason": "clean_nested_oos_edge_not_stable_enough",
        }
    return {
        "value": "revise",
        "reason": "mixed_clean_nested_oos_evidence",
    }


def window_policy_delta(report: Mapping[str, Any]) -> float:
    candidate = mapping_from(mapping_from(report.get("candidate")).get("holdout_policy_metrics"))
    baseline = mapping_from(mapping_from(report.get("baseline")).get("holdout_policy_metrics"))
    return (optional_float(candidate.get("net_pnl")) or 0.0) - (
        optional_float(baseline.get("net_pnl")) or 0.0
    )


def build_stale_quote_alpha_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    windows_seconds: Sequence[int] = (5, 15, 30, 60),
    min_btc_move_cents: float = 0.5,
    quote_reaction_ratio: float = 0.5,
) -> dict[str, Any]:
    engineered = engineer_kxbtc_features(rows)
    scored = stale_quote_rows(
        engineered,
        windows_seconds=windows_seconds,
        min_btc_move_cents=min_btc_move_cents,
        quote_reaction_ratio=quote_reaction_ratio,
    )
    candidates = [row for row in scored if row["is_stale_quote_candidate"]]
    return {
        "schema_version": "kxbtc_stale_quote_alpha_report_v1",
        "raw_row_count": len(rows),
        "scored_row_count": len(scored),
        "candidate_row_count": len(candidates),
        "windows_seconds": list(windows_seconds),
        "min_btc_move_cents": min_btc_move_cents,
        "quote_reaction_ratio": quote_reaction_ratio,
        "candidate_rows": candidates,
        "regime_breakdowns": {
            "threshold_proximity": breakdown(candidates, "threshold_proximity_bucket"),
            "time_to_expiry": breakdown(candidates, "time_to_expiry_bucket"),
            "spread": breakdown(candidates, "spread_bucket"),
            "side": breakdown(candidates, "side"),
        },
        "no_lookahead_note": "Rows are compared only with earlier rows from the same market instance.",
        "non_promotion_notice": MONEY_PRINTER_NOTICE,
    }


def stale_quote_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    windows_seconds: Sequence[int],
    min_btc_move_cents: float,
    quote_reaction_ratio: float,
) -> list[dict[str, Any]]:
    by_ticker: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_ticker.setdefault(str(row.get("ticker", "")), []).append(row)
    output: list[dict[str, Any]] = []
    for ticker_rows in by_ticker.values():
        ordered = sorted(ticker_rows, key=row_time_key)
        for index, row in enumerate(ordered):
            if index == 0:
                continue
            scored = score_stale_quote_row(
                row,
                ordered[:index],
                windows_seconds=windows_seconds,
                min_btc_move_cents=min_btc_move_cents,
                quote_reaction_ratio=quote_reaction_ratio,
            )
            if scored is not None:
                output.append(scored)
    return output


def score_stale_quote_row(
    row: Mapping[str, Any],
    prior_rows: Sequence[Mapping[str, Any]],
    *,
    windows_seconds: Sequence[int],
    min_btc_move_cents: float,
    quote_reaction_ratio: float,
) -> dict[str, Any] | None:
    current_ts = parse_datetime(row.get("decision_timestamp") or row.get("decision_timestamp_utc"))
    returns_by_window: dict[str, float] = {}
    quote_moves_by_window: dict[str, float] = {}
    selected_prev: Mapping[str, Any] | None = None
    for window_seconds in sorted(windows_seconds):
        previous = latest_prior_row(row, prior_rows, window_seconds)
        if previous is None:
            continue
        btc_return = btc_return_between(previous, row)
        quote_move = quote_move_cents(previous, row)
        if btc_return is None or quote_move is None:
            continue
        returns_by_window[str(window_seconds)] = btc_return
        quote_moves_by_window[str(window_seconds)] = quote_move
        selected_prev = previous
    if not returns_by_window or selected_prev is None:
        return None
    selected_window, selected_return = max(
        returns_by_window.items(),
        key=lambda item: abs(item[1]),
    )
    side = "yes" if selected_return >= 0 else "no"
    quote_move = quote_moves_by_window[selected_window]
    threshold_distance_pct = abs(optional_float(row.get("moneyness_pct")) or 0.0)
    closeness_multiplier = 1.0 + (1.0 / (1.0 + threshold_distance_pct * 100.0))
    btc_implied_move_cents = abs(selected_return) * 100.0 * closeness_multiplier
    stale_score = max(0.0, btc_implied_move_cents - quote_move)
    spread = side_spread(row, side)
    previous_ts = parse_datetime(
        selected_prev.get("decision_timestamp") or selected_prev.get("decision_timestamp_utc")
    )
    lag_seconds = (
        (current_ts - previous_ts).total_seconds()
        if current_ts is not None and previous_ts is not None
        else None
    )
    is_candidate = (
        btc_implied_move_cents >= min_btc_move_cents
        and quote_move <= btc_implied_move_cents * quote_reaction_ratio
    )
    return {
        "row_key": row_key(row),
        "ticker": row.get("ticker"),
        "decision_timestamp": row.get("decision_timestamp") or row.get("decision_timestamp_utc"),
        "decision_minute_offset": row.get("decision_minute_offset"),
        "side": side,
        "selected_window_seconds": int(selected_window),
        "btc_returns_by_window": returns_by_window,
        "kalshi_quote_move_cents_by_window": quote_moves_by_window,
        "btc_implied_probability_move_cents": btc_implied_move_cents,
        "kalshi_quote_move_cents": quote_move,
        "stale_quote_score": stale_score,
        "quote_update_recency_seconds": optional_float(row.get("last_trade_age_seconds")),
        "previous_decision_lag_seconds": lag_seconds,
        "threshold_distance_pct": threshold_distance_pct,
        "threshold_proximity_bucket": threshold_bucket(threshold_distance_pct),
        "time_to_expiry_seconds": optional_float(row.get("time_to_close_seconds")),
        "time_to_expiry_bucket": time_to_expiry_bucket(row),
        "spread": spread,
        "spread_bucket": spread_bucket(spread),
        "liquidity_proxy": liquidity_proxy(row),
        "is_stale_quote_candidate": is_candidate,
    }


def build_top_ev_sniper_policy_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_columns: Sequence[str],
    nested_oos_report: Mapping[str, Any],
    stale_quote_report: Mapping[str, Any] | None = None,
    fee_multiplier: float = 0.14,
    friction_spread_cents: float = 1.0,
    fixed_dollars_per_trade: float = 5.0,
    min_ev: float = 0.0,
    min_confidence: float = 0.0,
    min_stale_quote_score: float = 0.0,
    side: str = "any",
) -> dict[str, Any]:
    engineered = engineer_kxbtc_features(rows)
    stale_scores = stale_score_index(stale_quote_report)
    opportunities = sniper_opportunities(
        engineered,
        feature_columns=feature_columns,
        nested_oos_report=nested_oos_report,
        stale_scores=stale_scores,
        fee_multiplier=fee_multiplier,
        friction_spread_cents=friction_spread_cents,
        fixed_dollars_per_trade=fixed_dollars_per_trade,
    )
    filtered = [
        opportunity
        for opportunity in opportunities
        if opportunity["predicted_ev_per_contract"] >= min_ev
        and opportunity["confidence"] >= min_confidence
        and opportunity["stale_quote_score"] >= min_stale_quote_score
        and (side == "any" or opportunity["side"] == side)
    ]
    positive = [
        opportunity for opportunity in filtered if opportunity["predicted_ev_per_contract"] > 0
    ]
    buckets = ev_buckets(positive)
    monotonic = monotonic_bucket_check(buckets)
    decision = sniper_decision(buckets, monotonic)
    return {
        "schema_version": "kxbtc_top_ev_sniper_policy_report_v1",
        "raw_row_count": len(rows),
        "opportunity_count": len(opportunities),
        "filtered_opportunity_count": len(filtered),
        "positive_ev_opportunity_count": len(positive),
        "trade_reduction_vs_all_opportunities": (
            1.0 - (len(positive) / len(opportunities)) if opportunities else None
        ),
        "ranking": "predicted_ev_at_executable_ask_after_fees_and_friction",
        "policy_filters": {
            "min_ev": min_ev,
            "min_confidence": min_confidence,
            "min_stale_quote_score": min_stale_quote_score,
            "side": side,
            "fee_multiplier": fee_multiplier,
            "friction_spread_cents": friction_spread_cents,
            "fixed_dollars_per_trade": fixed_dollars_per_trade,
            "selection_scope": "fixed_before_holdout_bucket_scoring",
        },
        "buckets": buckets,
        "monotonicity": monotonic,
        "decision": decision,
        "bootstrap": {
            name: bucket.get("bootstrap")
            for name, bucket in buckets.items()
            if isinstance(bucket, Mapping)
        },
        "non_promotion_notice": MONEY_PRINTER_NOTICE,
    }


def sniper_opportunities(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_columns: Sequence[str],
    nested_oos_report: Mapping[str, Any],
    stale_scores: Mapping[str, float],
    fee_multiplier: float,
    friction_spread_cents: float,
    fixed_dollars_per_trade: float,
) -> list[dict[str, Any]]:
    default_columns = default_model_feature_columns(feature_columns)
    output: list[dict[str, Any]] = []
    for window_report in nested_oos_report.get("windows", ()):
        if not isinstance(window_report, Mapping) or window_report.get("status") != "complete":
            continue
        slim_columns = [str(column) for column in window_report.get("selected_slim_feature_columns", ())]
        candidate_columns = list(default_columns) + [
            column for column in slim_columns if column not in set(default_columns)
        ]
        window = mapping_from(window_report.get("window"))
        selection_markets = [str(value) for value in window.get("selection_markets", ())]
        holdout_markets = [str(value) for value in window.get("holdout_markets", ())]
        selection_rows = rows_with_numeric_features(
            rows_for_markets(rows, selection_markets),
            candidate_columns,
        )
        holdout_rows = rows_with_numeric_features(
            rows_for_markets(rows, holdout_markets),
            candidate_columns,
        )
        selected_family = str(mapping_from(window_report.get("candidate")).get("selected_candidate"))
        report, trained = fit_and_report_candidate(
            selected_family,
            train_rows=selection_rows,
            evaluation_rows=holdout_rows,
            feature_columns=candidate_columns,
        )
        if trained is None:
            continue
        predicted = rename_prediction_candidate(trained.predict_rows(holdout_rows), selected_family)
        for row in predicted:
            opportunity = trade_opportunity(
                row,
                fee_multiplier=fee_multiplier,
                friction_spread_cents=friction_spread_cents,
                fixed_dollars_per_trade=fixed_dollars_per_trade,
                stale_quote_score=stale_scores.get(row_key(row), 0.0),
            )
            if opportunity is not None:
                opportunity["window_start"] = window.get("holdout_markets", [""])[0]
                opportunity["selected_candidate"] = selected_family
                output.append(opportunity)
    return output


def trade_opportunity(
    row: Mapping[str, Any],
    *,
    fee_multiplier: float,
    friction_spread_cents: float,
    fixed_dollars_per_trade: float,
    stale_quote_score: float,
) -> dict[str, Any] | None:
    p_yes = optional_float(row.get("p_yes"))
    yes = optional_float(row.get("yes"))
    yes_ask = optional_float(row.get("yes_ask"))
    no_ask = optional_float(row.get("no_ask"))
    if p_yes is None or yes not in (0.0, 1.0) or yes_ask is None or no_ask is None:
        return None
    spread = friction_spread_cents / 100.0
    side_payloads = []
    for side, probability, ask in (
        ("yes", p_yes, yes_ask),
        ("no", 1.0 - p_yes, no_ask),
    ):
        adjusted_ask = min(0.99, ask + spread)
        fee = taker_fee(adjusted_ask, fee_multiplier)
        ev = probability - adjusted_ask - fee
        side_payloads.append((ev, side, probability, adjusted_ask, fee))
    predicted_ev, side, probability, ask, fee = max(side_payloads, key=lambda item: item[0])
    contracts = max(0, int(fixed_dollars_per_trade // max(ask, 0.01)))
    if contracts <= 0:
        return None
    payout = int(yes) if side == "yes" else 1 - int(yes)
    one_contract_pnl = payout - ask - fee
    fixed_dollar_pnl = one_contract_pnl * contracts
    return {
        "row_key": row_key(row),
        "ticker": row.get("ticker"),
        "decision_timestamp": row.get("decision_timestamp") or row.get("decision_timestamp_utc"),
        "decision_minute_offset": row.get("decision_minute_offset"),
        "side": side,
        "probability": probability,
        "confidence": max(p_yes, 1.0 - p_yes),
        "ask": ask,
        "fee": fee,
        "contracts": contracts,
        "predicted_ev_per_contract": predicted_ev,
        "one_contract_realized_pnl": one_contract_pnl,
        "fixed_dollar_pnl": fixed_dollar_pnl,
        "win": fixed_dollar_pnl > 0,
        "stale_quote_score": stale_quote_score,
        "threshold_distance_pct": abs(optional_float(row.get("moneyness_pct")) or 0.0),
        "spread": side_spread(row, side),
        "liquidity_proxy": liquidity_proxy(row),
        "time_to_expiry_seconds": optional_float(row.get("time_to_close_seconds")),
    }


def ev_buckets(opportunities: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    ordered = sorted(
        opportunities,
        key=lambda row: optional_float(row.get("predicted_ev_per_contract")) or 0.0,
        reverse=True,
    )
    bucket_specs = (
        ("top_1_pct", 0.01),
        ("top_5_pct", 0.05),
        ("top_10_pct", 0.10),
        ("all_positive_ev", 1.0),
    )
    return {
        name: bucket_metrics(ordered[: max(1, math.ceil(len(ordered) * fraction))])
        if ordered
        else empty_bucket_metrics()
        for name, fraction in bucket_specs
    }


def bucket_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pnls = [optional_float(row.get("fixed_dollar_pnl")) or 0.0 for row in rows]
    one_contract = [optional_float(row.get("one_contract_realized_pnl")) or 0.0 for row in rows]
    predicted = [optional_float(row.get("predicted_ev_per_contract")) or 0.0 for row in rows]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    equity = 1000.0
    curve = [equity]
    for pnl in pnls:
        equity += pnl
        curve.append(equity)
    return {
        "trade_count": len(rows),
        "pnl": sum(pnls),
        "realized_ev_per_trade": mean(one_contract),
        "win_rate": len(wins) / len(rows) if rows else 0.0,
        "profit_factor": (sum(wins) / abs(sum(losses))) if losses else None,
        "max_drawdown": max_drawdown(curve),
        "average_edge_per_trade": mean(predicted),
        "bootstrap": {
            "pnl_sum_ci": bootstrap_ci(pnls, mode="sum"),
            "realized_ev_per_trade_ci": bootstrap_ci(one_contract, mode="mean"),
        },
    }


def empty_bucket_metrics() -> dict[str, Any]:
    return {
        "trade_count": 0,
        "pnl": 0.0,
        "realized_ev_per_trade": None,
        "win_rate": 0.0,
        "profit_factor": None,
        "max_drawdown": 0.0,
        "average_edge_per_trade": None,
        "bootstrap": {
            "pnl_sum_ci": None,
            "realized_ev_per_trade_ci": None,
        },
    }


def monotonic_bucket_check(buckets: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    order = ["top_1_pct", "top_5_pct", "top_10_pct", "all_positive_ev"]
    values = [optional_float(mapping_from(buckets.get(name)).get("realized_ev_per_trade")) for name in order]
    real_values = [value for value in values if value is not None]
    monotonic = all(left >= right for left, right in zip(real_values, real_values[1:], strict=False))
    return {
        "status": "monotonic" if monotonic else "not_monotonic",
        "bucket_order": order,
        "realized_ev_per_trade": dict(zip(order, values, strict=True)),
    }


def sniper_decision(
    buckets: Mapping[str, Mapping[str, Any]],
    monotonicity: Mapping[str, Any],
) -> dict[str, Any]:
    top_10 = mapping_from(buckets.get("top_10_pct"))
    pnl = optional_float(top_10.get("pnl")) or 0.0
    profit_factor = optional_float(top_10.get("profit_factor")) or 0.0
    if pnl > 0 and profit_factor >= 1.5 and monotonicity.get("status") == "monotonic":
        return {"value": "continue", "reason": "top_ev_bucket_money_printer_bars_passed"}
    if pnl <= 0:
        return {"value": "kill", "reason": "top_ev_bucket_lost_money"}
    return {"value": "revise", "reason": "top_ev_bucket_positive_but_not_money_printer_grade"}


def build_fillability_probe_report(
    opportunities: Sequence[Mapping[str, Any]],
    *,
    ask_tolerance_cents: float = 1.0,
) -> dict[str, Any]:
    normalized = [
        normalize_fillability_opportunity(row, ask_tolerance_cents=ask_tolerance_cents)
        for row in opportunities
    ]
    simulated = [row for row in normalized if row["simulated_opportunity"]]
    observed = [row for row in normalized if row["live_observed"]]
    fillable = [row for row in normalized if row["fillable"]]
    filled = [row for row in normalized if row["filled"]]
    pnls = [optional_float(row.get("realized_pnl")) or 0.0 for row in filled]
    return {
        "schema_version": "kxbtc_fillability_probe_report_v1",
        "opportunity_count": len(normalized),
        "required_fields": [
            "decision_timestamp",
            "btc_reference_price",
            "kalshi_best_ask",
            "available_size",
            "spread",
            "predicted_probability",
            "predicted_ev",
            "stale_quote_score",
            "order_intent",
            "order_sent",
            "fill_status",
            "partial_fill",
            "latency_ms",
            "post_trade_quote_movement",
            "settlement_result",
            "realized_pnl",
        ],
        "counts": {
            "simulated_opportunities": len(simulated),
            "live_observed_opportunities": len(observed),
            "fillable_opportunities": len(fillable),
            "filled_opportunities": len(filled),
            "partial_fill_count": sum(1 for row in normalized if row["partial_fill"]),
        },
        "gaps": {
            "simulated_to_observed_gap": len(simulated) - len(observed),
            "observed_to_fillable_gap": len(observed) - len(fillable),
            "fillable_to_filled_gap": len(fillable) - len(filled),
        },
        "pnl": {
            "realized_pnl": sum(pnls),
            "realized_pnl_per_filled_trade": mean(pnls),
        },
        "opportunities": normalized,
        "mode": "live_data_paper_or_observation_only",
        "non_promotion_notice": MONEY_PRINTER_NOTICE,
    }


def normalize_fillability_opportunity(
    row: Mapping[str, Any],
    *,
    ask_tolerance_cents: float,
) -> dict[str, Any]:
    predicted_ev = first_present_float(row, "predicted_ev", "predicted_ev_per_contract")
    simulated_ask = first_present_float(row, "simulated_ask", "side_price", "ask")
    best_ask = first_present_float(row, "kalshi_best_ask", "observed_best_ask", "ask")
    available_size = first_present_float(row, "available_size", "ask_size", "best_ask_size")
    intended_contracts = int(first_present_float(row, "intended_contracts", "contracts") or 1)
    filled_quantity = int(first_present_float(row, "filled_quantity", "fill_quantity") or 0)
    fill_status = str(row.get("fill_status", "")).lower()
    explicit_fillable = row.get("fillable")
    fillable = (
        bool(explicit_fillable)
        if explicit_fillable is not None
        else (
            best_ask is not None
            and available_size is not None
            and available_size >= intended_contracts
            and (
                simulated_ask is None
                or best_ask <= simulated_ask + (ask_tolerance_cents / 100.0)
            )
        )
    )
    filled = filled_quantity > 0 or fill_status in {"filled", "partial", "partial_fill", "partial_filled"}
    realized_pnl = first_present_float(row, "realized_pnl")
    return {
        "decision_timestamp": row.get("decision_timestamp"),
        "btc_reference_price": first_present_float(row, "btc_reference_price", "external_close"),
        "kalshi_best_ask": best_ask,
        "available_size": available_size,
        "spread": first_present_float(row, "spread"),
        "predicted_probability": first_present_float(row, "predicted_probability", "probability"),
        "predicted_ev": predicted_ev,
        "stale_quote_score": first_present_float(row, "stale_quote_score") or 0.0,
        "order_intent": row.get("order_intent"),
        "order_sent": bool(row.get("order_sent", False)),
        "fill_status": fill_status or "not_sent",
        "partial_fill": 0 < filled_quantity < intended_contracts or "partial" in fill_status,
        "latency_ms": first_present_float(row, "latency_ms"),
        "post_trade_quote_movement": first_present_float(row, "post_trade_quote_movement"),
        "settlement_result": row.get("settlement_result"),
        "realized_pnl": realized_pnl,
        "simulated_opportunity": bool(row.get("simulated_opportunity", (predicted_ev or 0.0) > 0)),
        "live_observed": best_ask is not None,
        "fillable": fillable,
        "filled": filled,
        "intended_contracts": intended_contracts,
        "filled_quantity": filled_quantity,
    }


def latest_prior_row(
    row: Mapping[str, Any],
    prior_rows: Sequence[Mapping[str, Any]],
    window_seconds: int,
) -> Mapping[str, Any] | None:
    current_ts = parse_datetime(row.get("decision_timestamp") or row.get("decision_timestamp_utc"))
    current_offset = optional_float(row.get("time_since_open_seconds"))
    for prior in reversed(prior_rows):
        prior_ts = parse_datetime(prior.get("decision_timestamp") or prior.get("decision_timestamp_utc"))
        if current_ts is not None and prior_ts is not None:
            delta = (current_ts - prior_ts).total_seconds()
        else:
            prior_offset = optional_float(prior.get("time_since_open_seconds"))
            delta = (
                current_offset - prior_offset
                if current_offset is not None and prior_offset is not None
                else None
            )
        if delta is not None and 0 < delta <= window_seconds:
            return prior
    return None


def btc_return_between(previous: Mapping[str, Any], current: Mapping[str, Any]) -> float | None:
    previous_close = optional_float(previous.get("external_close"))
    current_close = optional_float(current.get("external_close"))
    if previous_close not in (None, 0.0) and current_close is not None:
        return (current_close - previous_close) / previous_close
    return optional_float(current.get("external_return_1"))


def quote_move_cents(previous: Mapping[str, Any], current: Mapping[str, Any]) -> float | None:
    moves = []
    for column in ("yes_ask", "no_ask", "yes_midpoint", "no_midpoint"):
        previous_value = optional_float(previous.get(column))
        current_value = optional_float(current.get(column))
        if previous_value is not None and current_value is not None:
            moves.append(abs(current_value - previous_value) * 100.0)
    return max(moves) if moves else None


def side_spread(row: Mapping[str, Any], side: str) -> float | None:
    if side == "yes":
        return optional_float(row.get("yes_spread"))
    return optional_float(row.get("no_spread"))


def liquidity_proxy(row: Mapping[str, Any]) -> float | None:
    count = optional_float(row.get("last_trade_count_fp"))
    elapsed = optional_float(row.get("time_since_open_seconds"))
    if count is not None and elapsed is not None:
        return count / max(elapsed, 60.0)
    return optional_float(row.get("external_volume"))


def threshold_bucket(distance_pct: float | None) -> str:
    value = abs(distance_pct or 0.0)
    if value <= 0.001:
        return "near_threshold"
    if value <= 0.005:
        return "mid_threshold"
    return "far_threshold"


def time_to_expiry_bucket(row: Mapping[str, Any]) -> str:
    value = optional_float(row.get("time_to_close_seconds"))
    if value is None:
        return "unknown"
    if value <= 60:
        return "final_60s"
    if value <= 300:
        return "final_5m"
    return "early"


def spread_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value <= 0.02:
        return "tight"
    if value <= 0.05:
        return "normal"
    return "wide"


def breakdown(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    buckets: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(str(row.get(key, "unknown")), []).append(row)
    return {
        name: {
            "count": len(bucket_rows),
            "mean_stale_quote_score": mean(
                [optional_float(row.get("stale_quote_score")) or 0.0 for row in bucket_rows]
            ),
        }
        for name, bucket_rows in sorted(buckets.items())
    }


def stale_score_index(report: Mapping[str, Any] | None) -> dict[str, float]:
    if not isinstance(report, Mapping):
        return {}
    return {
        str(row.get("row_key")): optional_float(row.get("stale_quote_score")) or 0.0
        for row in report.get("candidate_rows", ())
        if isinstance(row, Mapping)
    }


def row_key(row: Mapping[str, Any]) -> str:
    return "|".join(
        (
            str(row.get("ticker", "")),
            str(row.get("decision_timestamp") or row.get("decision_timestamp_utc") or ""),
            str(row.get("decision_minute_offset", "")),
        )
    )


def row_time_key(row: Mapping[str, Any]) -> tuple[str, float]:
    timestamp = parse_datetime(row.get("decision_timestamp") or row.get("decision_timestamp_utc"))
    if timestamp is not None:
        return (timestamp.isoformat(), optional_float(row.get("time_since_open_seconds")) or 0.0)
    return ("", optional_float(row.get("time_since_open_seconds")) or 0.0)


def first_present_float(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = optional_float(row.get(key))
        if value is not None:
            return value
    return None


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def bootstrap_ci(
    values: Sequence[float],
    *,
    mode: str,
    iterations: int = 200,
) -> dict[str, float] | None:
    if not values:
        return None
    rng = random.Random(42)
    samples: list[float] = []
    for _ in range(iterations):
        draw = [values[rng.randrange(len(values))] for _ in values]
        samples.append(sum(draw) if mode == "sum" else (sum(draw) / len(draw)))
    samples.sort()
    low = samples[int(0.05 * (len(samples) - 1))]
    high = samples[int(0.95 * (len(samples) - 1))]
    return {"p05": low, "p95": high}
