"""Feature groups and engineered features for KXBTC15M model evaluation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from alphadb.model_evaluation.metrics import optional_float

LEAKY_FEATURE_COLUMNS = {
    "yes",
    "kalshi_result",
    "result",
    "expiration_value",
    "settlement_value_dollars",
    "realized_pnl",
    "settlement_result",
}

REQUIRED_TIMING_COLUMNS = {
    "decision_minute_offset",
    "time_since_open_seconds",
    "time_to_close_seconds",
}

COINBASE_BTC_MARKET_STRUCTURE_PREFIX = "coinbase_btc_"
RAW_X_SIGNAL_PREFIXES = (
    "x_counts_",
    "x_attention_",
    "x_total_count_",
    "x_signal_",
)


DEFAULT_FEATURE_GROUP_PATTERNS: dict[str, tuple[str, ...]] = {
    "timing": (
        "decision_minute_offset",
        "time_since_open_seconds",
        "time_to_close_seconds",
        "minute_sin",
        "minute_cos",
        "hour_sin",
        "hour_cos",
    ),
    "kalshi_quote_state": (
        "price_close_dollars",
        "yes_bid_close_dollars",
        "yes_ask_close_dollars",
        "no_bid_close_dollars",
        "no_ask_close_dollars",
        "yes_bid",
        "yes_ask",
        "no_bid",
        "no_ask",
        "yes_spread",
        "no_spread",
        "yes_midpoint",
        "no_midpoint",
        "quote_imbalance",
        "yes_executable_gap",
        "no_executable_gap",
    ),
    "kalshi_trade_state": (
        "last_trade_yes_price_dollars",
        "last_trade_no_price_dollars",
        "last_trade_price_dollars",
        "last_trade_count_fp",
        "last_trade_age_seconds",
        "recent_trade_intensity",
    ),
    "kalshi_liquidity_state": ("volume_fp", "open_interest_fp"),
    "coinbase_external_state": (
        "external_granularity_seconds",
        "external_open",
        "external_high",
        "external_low",
        "external_close",
        "external_volume",
        "external_return_1",
        "external_log_return_1",
        "external_close_to_open_return",
        "external_range_pct",
        "external_realized_vol_5",
        "external_realized_vol_15",
        "external_momentum_short",
        "external_volatility_ratio",
    ),
    "coinbase_btc_market_structure": (
        "coinbase_btc_*",
    ),
    "moneyness_state": (
        "payout_threshold",
        "strike_dollars",
        "moneyness_dollars",
        "moneyness_pct",
    ),
    "x_external_signal_state": (
        "x_counts_*",
        "x_attention_*",
        "x_total_count_*",
        "x_signal_missing_category_count",
    ),
}


def default_model_feature_columns(
    feature_columns: Sequence[str],
    *,
    include_raw_x_counts: bool = False,
) -> list[str]:
    """Return public-safe default research features.

    Raw X-count columns remain available for explicit post-mortem reads, but they are frozen out
    of default model-comparison paths after the failed ALP-69 raw-count experiment.
    """

    output: list[str] = []
    for column in feature_columns:
        if column in LEAKY_FEATURE_COLUMNS:
            continue
        if not include_raw_x_counts and is_raw_x_signal_feature(column):
            continue
        output.append(column)
    return output


def is_raw_x_signal_feature(column: str) -> bool:
    return column.startswith(RAW_X_SIGNAL_PREFIXES)


def is_coinbase_btc_market_structure_feature(column: str) -> bool:
    return column.startswith(COINBASE_BTC_MARKET_STRUCTURE_PREFIX)


def resolve_feature_groups(
    feature_columns: Sequence[str],
    *,
    group_patterns: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, list[str]]:
    group_patterns = group_patterns or DEFAULT_FEATURE_GROUP_PATTERNS
    feature_set = set(feature_columns)
    leaky = sorted(feature_set.intersection(LEAKY_FEATURE_COLUMNS))
    if leaky:
        raise ValueError(f"leaky feature columns are not allowed: {leaky}")
    groups: dict[str, list[str]] = {}
    for group_name, patterns in group_patterns.items():
        columns = [
            column
            for column in feature_columns
            if any(pattern_matches_feature(pattern, column) for pattern in patterns)
        ]
        groups[group_name] = columns
    ungrouped = sorted(feature_set.difference({column for columns in groups.values() for column in columns}))
    if ungrouped:
        groups["ungrouped"] = ungrouped
    return groups


def ablation_feature_sets(
    feature_columns: Sequence[str],
    *,
    include_required_timing: bool = True,
) -> list[dict[str, Any]]:
    groups = resolve_feature_groups(feature_columns)
    feature_set = set(feature_columns)
    required_timing = REQUIRED_TIMING_COLUMNS.intersection(feature_set) if include_required_timing else set()
    configs = [{"name": "full", "feature_columns": list(feature_columns), "mode": "full"}]
    for group_name, columns in groups.items():
        if not columns:
            continue
        removed = [column for column in feature_columns if column not in set(columns)]
        one_group = sorted(set(columns).union(required_timing), key=list(feature_columns).index)
        configs.append(
            {
                "name": f"without_{group_name}",
                "feature_columns": removed,
                "mode": "remove_group",
                "group": group_name,
            }
        )
        configs.append(
            {
                "name": f"only_{group_name}",
                "feature_columns": one_group,
                "mode": "only_group",
                "group": group_name,
            }
        )
    return configs


def engineer_kxbtc_features(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    engineered: list[dict[str, Any]] = []
    for row in rows:
        output = dict(row)
        add_quote_features(output)
        add_trade_features(output)
        add_external_features(output)
        add_time_features(output)
        add_moneyness_features(output)
        add_coinbase_btc_market_structure_features(output)
        validate_source_lineage(output)
        engineered.append(output)
    return engineered


def pattern_matches_feature(pattern: str, column: str) -> bool:
    if pattern.endswith("*"):
        return column.startswith(pattern[:-1])
    return column == pattern


def add_quote_features(row: dict[str, Any]) -> None:
    yes_bid = first_numeric(row, "yes_bid", "yes_bid_close_dollars")
    yes_ask = first_numeric(row, "yes_ask", "yes_ask_close_dollars")
    no_bid = first_numeric(row, "no_bid", "no_bid_close_dollars")
    no_ask = first_numeric(row, "no_ask", "no_ask_close_dollars")
    if yes_bid is not None and yes_ask is not None:
        row["yes_spread"] = yes_ask - yes_bid
        row["yes_midpoint"] = (yes_bid + yes_ask) / 2.0
        row["yes_executable_gap"] = yes_ask - row["yes_midpoint"]
    if no_bid is not None and no_ask is not None:
        row["no_spread"] = no_ask - no_bid
        row["no_midpoint"] = (no_bid + no_ask) / 2.0
        row["no_executable_gap"] = no_ask - row["no_midpoint"]
    if yes_bid is not None and no_bid is not None:
        denominator = abs(yes_bid) + abs(no_bid)
        if denominator:
            row["quote_imbalance"] = (yes_bid - no_bid) / denominator


def add_trade_features(row: dict[str, Any]) -> None:
    decision = parse_datetime(row.get("decision_timestamp") or row.get("decision_timestamp_utc"))
    trade_time = parse_datetime(row.get("last_trade_timestamp"))
    if decision and trade_time:
        row["last_trade_age_seconds"] = (decision - trade_time).total_seconds()
    count = optional_float(row.get("last_trade_count_fp"))
    elapsed = optional_float(row.get("time_since_open_seconds"))
    if count is not None and elapsed is not None:
        row["recent_trade_intensity"] = count / max(elapsed, 60.0)


def add_external_features(row: dict[str, Any]) -> None:
    returns = [
        value
        for value in (
            optional_float(row.get("external_return_1")),
            optional_float(row.get("external_log_return_1")),
            optional_float(row.get("external_close_to_open_return")),
        )
        if value is not None
    ]
    if returns:
        row["external_momentum_short"] = sum(returns)
    vol_5 = optional_float(row.get("external_realized_vol_5"))
    vol_15 = optional_float(row.get("external_realized_vol_15"))
    if vol_5 is not None and vol_15 is not None:
        row["external_volatility_ratio"] = vol_15 / max(vol_5, 1e-12)


def add_coinbase_btc_market_structure_features(row: dict[str, Any]) -> None:
    close = optional_float(row.get("external_close"))
    open_ = optional_float(row.get("external_open"))
    high = optional_float(row.get("external_high"))
    low = optional_float(row.get("external_low"))
    volume = optional_float(row.get("external_volume"))
    return_1 = optional_float(row.get("external_return_1"))
    log_return_1 = optional_float(row.get("external_log_return_1"))
    close_to_open = optional_float(row.get("external_close_to_open_return"))
    range_pct = optional_float(row.get("external_range_pct"))
    vol_5 = optional_float(row.get("external_realized_vol_5"))
    vol_15 = optional_float(row.get("external_realized_vol_15"))
    threshold = first_numeric(row, "payout_threshold", "strike_dollars")

    if return_1 is not None:
        row["coinbase_btc_momentum_1m"] = return_1
    if log_return_1 is not None:
        row["coinbase_btc_log_momentum_1m"] = log_return_1
        row["coinbase_btc_abs_log_momentum_1m"] = abs(log_return_1)
    if close_to_open is not None:
        row["coinbase_btc_close_to_open_return"] = close_to_open
    if log_return_1 is not None and close_to_open is not None:
        continuation = log_return_1 * close_to_open
        row["coinbase_btc_continuation_pressure"] = continuation
        row["coinbase_btc_reversal_pressure"] = -continuation
    if close is not None and open_ not in (None, 0):
        row["coinbase_btc_candle_body_pct"] = (close - float(open_)) / float(open_)
    if high is not None and low is not None and close not in (None, 0):
        row["coinbase_btc_realized_range_pct"] = (high - low) / close
    elif range_pct is not None:
        row["coinbase_btc_realized_range_pct"] = range_pct
    if vol_5 is not None:
        row["coinbase_btc_realized_volatility_5m"] = vol_5
    if vol_15 is not None:
        row["coinbase_btc_realized_volatility_15m"] = vol_15
    if vol_5 is not None and vol_15 is not None:
        row["coinbase_btc_volatility_ratio_15m_5m"] = vol_15 / max(vol_5, 1e-12)
    if log_return_1 is not None and vol_5 is not None:
        row["coinbase_btc_candle_shock_5m"] = abs(log_return_1) / max(vol_5, 1e-12)
    effective_range_pct = optional_float(row.get("coinbase_btc_realized_range_pct"))
    if effective_range_pct is not None and vol_5 is not None:
        row["coinbase_btc_range_shock_5m"] = effective_range_pct / max(vol_5, 1e-12)
    if volume is not None:
        row["coinbase_btc_volume"] = volume
        row["coinbase_btc_log_volume"] = math.log1p(max(volume, 0.0))
    if close is not None and threshold is not None:
        distance = close - threshold
        row["coinbase_btc_threshold_distance_dollars"] = distance
        row["coinbase_btc_threshold_distance_pct"] = distance / threshold if threshold else None
        row["coinbase_btc_abs_threshold_distance_pct"] = (
            abs(distance) / threshold if threshold else None
        )


def add_time_features(row: dict[str, Any]) -> None:
    decision = parse_datetime(row.get("decision_timestamp") or row.get("decision_timestamp_utc"))
    if decision is None:
        return
    minute_of_day = decision.hour * 60 + decision.minute
    row["minute_sin"] = math.sin(2 * math.pi * minute_of_day / 1440.0)
    row["minute_cos"] = math.cos(2 * math.pi * minute_of_day / 1440.0)
    row["hour_sin"] = math.sin(2 * math.pi * decision.hour / 24.0)
    row["hour_cos"] = math.cos(2 * math.pi * decision.hour / 24.0)


def add_moneyness_features(row: dict[str, Any]) -> None:
    external_close = optional_float(row.get("external_close"))
    threshold = first_numeric(row, "payout_threshold", "strike_dollars")
    if external_close is None or threshold is None:
        return
    row["moneyness_dollars"] = external_close - threshold
    row["moneyness_pct"] = (external_close - threshold) / threshold if threshold else None


def validate_source_lineage(row: Mapping[str, Any]) -> None:
    decision = parse_datetime(row.get("decision_timestamp") or row.get("decision_timestamp_utc"))
    if decision is None:
        return
    source_columns = (
        "max_source_event_timestamp_utc",
        "candle_source_event_timestamp_utc",
        "trade_source_event_timestamp_utc",
        "external_source_event_timestamp_utc",
        "last_trade_timestamp",
    )
    for column in source_columns:
        source = parse_datetime(row.get(column))
        if source and source > decision:
            raise ValueError(
                "no-lookahead violation: "
                f"{column}={source.isoformat()} after decision={decision.isoformat()}"
            )


def first_numeric(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = optional_float(row.get(key))
        if value is not None:
            return value
    return None


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
