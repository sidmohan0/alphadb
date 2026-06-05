"""Fast fair-value model for KXBTC15M threshold/volatility experiments."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from alphadb.model_evaluation.metrics import optional_float

FAIR_VALUE_MODEL_VERSION = "kxbtc15m.threshold_volatility_fair_value.v1"
FAIR_VALUE_MODEL_REPORT_SCHEMA = "kxbtc_fair_value_model_rows.v1"


@dataclass(frozen=True)
class ThresholdVolatilityFairValueConfig:
    price_column: str = "external_close"
    threshold_column: str = "payout_threshold"
    probability_column: str = "p_yes"
    min_time_to_close_seconds: float = 1.0
    max_time_to_close_seconds: float = 15.0 * 60.0
    volatility_floor_pct: float = 0.0005
    momentum_weight: float = 0.25

    def as_dict(self) -> dict[str, Any]:
        return {
            "price_column": self.price_column,
            "threshold_column": self.threshold_column,
            "probability_column": self.probability_column,
            "min_time_to_close_seconds": self.min_time_to_close_seconds,
            "max_time_to_close_seconds": self.max_time_to_close_seconds,
            "volatility_floor_pct": self.volatility_floor_pct,
            "momentum_weight": self.momentum_weight,
        }


def build_threshold_volatility_fair_value_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    config: ThresholdVolatilityFairValueConfig | None = None,
) -> list[dict[str, Any]]:
    scorer = ThresholdVolatilityFairValueModel(config or ThresholdVolatilityFairValueConfig())
    return [scorer.score_row(row) for row in rows]


def build_threshold_volatility_fair_value_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    config: ThresholdVolatilityFairValueConfig | None = None,
) -> dict[str, Any]:
    config = config or ThresholdVolatilityFairValueConfig()
    scored = build_threshold_volatility_fair_value_rows(rows, config=config)
    completed = [row for row in scored if row.get("fair_value_status") == "complete"]
    skipped = [row for row in scored if row.get("fair_value_status") == "skipped"]
    probabilities = [float(row[config.probability_column]) for row in completed]
    return {
        "schema_version": FAIR_VALUE_MODEL_REPORT_SCHEMA,
        "model_version": FAIR_VALUE_MODEL_VERSION,
        "config": config.as_dict(),
        "input_rows": len(rows),
        "counts": {
            "completed": len(completed),
            "skipped": len(skipped),
        },
        "probability_summary": {
            "min": round(min(probabilities), 6) if probabilities else None,
            "max": round(max(probabilities), 6) if probabilities else None,
            "mean": round(sum(probabilities) / len(probabilities), 6)
            if probabilities
            else None,
        },
        "skips": summarize_skips(scored),
        "rows": scored,
    }


class ThresholdVolatilityFairValueModel:
    def __init__(self, config: ThresholdVolatilityFairValueConfig | None = None):
        self.config = config or ThresholdVolatilityFairValueConfig()

    def score_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        output = dict(row)
        price = first_numeric(
            row,
            (
                self.config.price_column,
                "external_close",
                "coinbase_btc_close",
                "btc_price",
                "underlying_price",
                "last_external_close",
            ),
        )
        threshold = first_numeric(
            row,
            (
                self.config.threshold_column,
                "payout_threshold",
                "strike",
                "strike_price",
                "floor_strike",
                "cap_strike",
                "target_price",
            ),
        )
        if threshold is None:
            threshold = parse_threshold_from_text(row)
        if price is None:
            return mark_skipped(output, "missing_external_price")
        if threshold is None:
            return mark_skipped(output, "missing_payout_threshold")
        if price <= 0 or threshold <= 0:
            return mark_skipped(output, "invalid_price_or_threshold")

        time_to_close = time_to_close_seconds(row)
        if time_to_close is None:
            return mark_skipped(output, "missing_time_to_close")
        clamped_time = min(
            self.config.max_time_to_close_seconds,
            max(self.config.min_time_to_close_seconds, time_to_close),
        )
        volatility = max(self.config.volatility_floor_pct, realized_volatility_pct(row))
        momentum = recent_momentum(row)
        momentum_shift = price * momentum * self.config.momentum_weight
        expected_price = price + momentum_shift
        horizon_scale = math.sqrt(clamped_time / 60.0)
        sigma_dollars = max(price * volatility * horizon_scale, 0.01)
        z_score = (expected_price - threshold) / sigma_dollars
        p_yes = normal_cdf(z_score)

        output.update(
            {
                self.config.probability_column: round(clamp_probability(p_yes), 6),
                "fair_value_status": "complete",
                "fair_value_model_version": FAIR_VALUE_MODEL_VERSION,
                "fair_value_skip_reason": None,
                "external_close": price,
                "payout_threshold": threshold,
                "threshold_distance_dollars": round(price - threshold, 6),
                "threshold_distance_pct": round((price - threshold) / threshold, 9),
                "time_to_close_seconds": round(time_to_close, 6),
                "fair_value_realized_volatility_pct": round(volatility, 9),
                "fair_value_recent_momentum": round(momentum, 9),
                "fair_value_z_score": round(z_score, 6),
            }
        )
        return output


def first_numeric(row: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        value = optional_float(row.get(key))
        if value is not None:
            return value
    return None


def parse_threshold_from_text(row: Mapping[str, Any]) -> float | None:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("subtitle", "title", "market_title", "market_subtitle")
    )
    if not text.strip():
        return None
    matches = re.findall(r"\$?\b(\d{2,3}(?:,\d{3})+(?:\.\d+)?)\b", text)
    if not matches:
        matches = re.findall(r"\$?\b(\d{4,7}(?:\.\d+)?)\b", text)
    if not matches:
        return None
    return float(matches[-1].replace(",", ""))


def time_to_close_seconds(row: Mapping[str, Any]) -> float | None:
    direct = first_numeric(
        row,
        (
            "time_to_close_seconds",
            "seconds_to_close",
            "time_remaining_seconds",
            "seconds_remaining",
        ),
    )
    if direct is not None:
        return max(0.0, direct)
    decision = parse_datetime(row.get("decision_timestamp") or row.get("timestamp"))
    close = parse_datetime(
        row.get("close_time")
        or row.get("market_close_time")
        or row.get("expiration_time")
        or row.get("expected_expiration_time")
    )
    if decision is None or close is None:
        return None
    return max(0.0, (close - decision).total_seconds())


def realized_volatility_pct(row: Mapping[str, Any]) -> float:
    value = first_numeric(
        row,
        (
            "coinbase_btc_realized_volatility_5m",
            "external_realized_vol_5",
            "coinbase_btc_realized_volatility_15m",
            "external_realized_vol_15",
            "fair_value_realized_volatility_pct",
        ),
    )
    if value is None:
        return 0.0
    return abs(value)


def recent_momentum(row: Mapping[str, Any]) -> float:
    value = first_numeric(
        row,
        (
            "coinbase_btc_log_momentum_1m",
            "external_log_return_1",
            "coinbase_btc_momentum_1m",
            "external_return_1",
            "external_close_to_open_return",
        ),
    )
    return 0.0 if value is None else value


def normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def clamp_probability(value: float) -> float:
    return min(0.999999, max(0.000001, value))


def mark_skipped(row: dict[str, Any], reason: str) -> dict[str, Any]:
    row.update(
        {
            "fair_value_status": "skipped",
            "fair_value_skip_reason": reason,
            "fair_value_model_version": FAIR_VALUE_MODEL_VERSION,
            "p_yes": None,
        }
    )
    return row


def summarize_skips(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    reasons = sorted(
        {
            str(row.get("fair_value_skip_reason"))
            for row in rows
            if row.get("fair_value_status") == "skipped"
        }
    )
    return [
        {
            "reason": reason,
            "count": sum(
                1
                for row in rows
                if row.get("fair_value_status") == "skipped"
                and str(row.get("fair_value_skip_reason")) == reason
            ),
        }
        for reason in reasons
    ]


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
