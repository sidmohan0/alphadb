"""Live edge attribution payloads for fair-value operator diagnostics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "alphadb_live_edge_attribution.v1"


def build_live_edge_attribution(
    *,
    decision: Mapping[str, Any] | None,
    source_row: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
    runtime_config: Mapping[str, Any] | None = None,
    runtime_controls: Mapping[str, Any] | None = None,
    freshness: Mapping[str, Any] | None = None,
    timing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a best-effort explanation of the selected side's live edge."""

    decision_map = _mapping(decision)
    source_map = _mapping(source_row)
    config_map = _mapping(config)
    runtime_config_map = _mapping(runtime_config)
    runtime_controls_map = _mapping(runtime_controls)
    snapshot = _mapping(runtime_config_map.get("snapshot"))
    freshness_map = _mapping(freshness)
    timing_map = _mapping(timing)

    side = _text(decision_map.get("side"))
    probability = _first_float(decision_map, ("fair_value", "probability"))
    price = _first_float(decision_map, ("price", "yes_ask", "no_ask"))
    fee = _first_float(decision_map, ("fee_per_contract", "fee"))
    edge = _float(decision_map.get("edge"))
    raw_gap = (
        round(probability - price, 6)
        if probability is not None and price is not None
        else None
    )
    if fee is None and edge is not None and raw_gap is not None:
        fee = round(raw_gap - edge, 6)
    if edge is None and raw_gap is not None and fee is not None:
        edge = round(raw_gap - fee, 6)

    min_edge = _first_float(
        runtime_controls_map,
        ("min_edge",),
        default=_first_float(
            snapshot,
            ("min_edge",),
            default=_float(config_map.get("min_edge")),
        ),
    )
    min_contract_price = _first_float(
        runtime_controls_map,
        ("min_contract_price",),
        default=_first_float(
            snapshot,
            ("min_contract_price",),
            default=_float(config_map.get("min_contract_price")),
        ),
    )
    edge_shortfall = (
        round(max(0.0, min_edge - edge), 6)
        if min_edge is not None and edge is not None
        else None
    )
    edge_margin = (
        round(edge - min_edge, 6)
        if min_edge is not None and edge is not None
        else None
    )
    quote_age = _float(freshness_map.get("quote_age_seconds"))
    coinbase_age = _float(freshness_map.get("coinbase_feature_age_seconds"))
    quote_stale_seconds = _float(config_map.get("quote_stale_seconds"))
    coinbase_stale_seconds = _float(config_map.get("coinbase_feature_stale_seconds"))
    missing_fields = _missing_fields(
        {
            "side": side,
            "probability": probability,
            "price": price,
            "fee_per_contract": fee,
            "edge": edge,
            "min_edge": min_edge,
        }
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "available" if not missing_fields else "partial",
        "decision": _text(decision_map.get("decision")),
        "reason": _text(decision_map.get("reason")),
        "market_ticker": _text(
            decision_map.get("ticker")
            or decision_map.get("market_ticker")
            or source_map.get("ticker")
            or source_map.get("market_ticker")
        ),
        "side": side,
        "fair_value": _round(probability),
        "price": _round(price),
        "fee_per_contract": _round(fee),
        "raw_gap": _round(raw_gap),
        "edge": _round(edge),
        "min_edge": _round(min_edge),
        "edge_shortfall": _round(edge_shortfall),
        "edge_margin": _round(edge_margin),
        "min_contract_price": _round(min_contract_price),
        "edge_cleared": edge is not None and min_edge is not None and edge >= min_edge,
        "attribution_class": classify_live_edge_attribution(
            decision_reason=_text(decision_map.get("reason")),
            raw_gap=raw_gap,
            edge=edge,
            min_edge=min_edge,
            price=price,
            min_contract_price=min_contract_price,
            quote_age_seconds=quote_age,
            quote_stale_seconds=quote_stale_seconds,
            coinbase_feature_age_seconds=coinbase_age,
            coinbase_feature_stale_seconds=coinbase_stale_seconds,
            missing_fields=missing_fields,
        ),
        "freshness": {
            "quote_seen_at": freshness_map.get("quote_seen_at"),
            "quote_age_seconds": _round(quote_age),
            "coinbase_max_source_event_timestamp": freshness_map.get(
                "coinbase_max_source_event_timestamp"
            ),
            "coinbase_feature_age_seconds": _round(coinbase_age),
            "quote_stale_seconds": _round(quote_stale_seconds),
            "coinbase_feature_stale_seconds": _round(coinbase_stale_seconds),
        },
        "timing": compact_timing(timing_map),
        "missing_fields": missing_fields,
    }


def classify_live_edge_attribution(
    *,
    decision_reason: str | None,
    raw_gap: float | None,
    edge: float | None,
    min_edge: float | None,
    price: float | None,
    min_contract_price: float | None,
    quote_age_seconds: float | None,
    quote_stale_seconds: float | None,
    coinbase_feature_age_seconds: float | None,
    coinbase_feature_stale_seconds: float | None,
    missing_fields: Sequence[str] = (),
) -> str:
    if decision_reason == "price_below_min_contract" or (
        price is not None
        and min_contract_price is not None
        and price < min_contract_price
    ):
        return "price_below_min_contract"
    if quote_age_seconds is not None and quote_stale_seconds is not None:
        if quote_age_seconds > quote_stale_seconds:
            return "quote_freshness_suspect"
    if (
        coinbase_feature_age_seconds is not None
        and coinbase_feature_stale_seconds is not None
        and coinbase_feature_age_seconds > coinbase_feature_stale_seconds
    ):
        return "coinbase_freshness_suspect"
    if "probability" in missing_fields or "price" in missing_fields:
        return "missing_quote_context"
    if raw_gap is not None and raw_gap <= 0:
        return "negative_raw_gap"
    if edge is not None and min_edge is not None and edge < min_edge:
        if raw_gap is not None and raw_gap > 0 and edge <= 0:
            return "fee_drag"
        return "threshold_drag"
    if edge is not None and min_edge is not None and edge >= min_edge:
        return "edge_cleared"
    return "unknown"


def summarize_live_edge_attribution_buckets(
    attributions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for attribution in attributions:
        attribution_class = _text(attribution.get("attribution_class")) or "unknown"
        counter[attribution_class] += 1
    return [
        {"attribution_class": name, "count": count}
        for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def compact_timing(timing: Mapping[str, Any]) -> dict[str, Any]:
    phase_seconds = _mapping(timing.get("phase_seconds"))
    compact_phases = {
        key: _round(_float(value))
        for key, value in phase_seconds.items()
        if _float(value) is not None
    }
    return {
        "total_elapsed_seconds": _round(_float(timing.get("total_elapsed_seconds"))),
        "quote_to_submit_seconds": _round(_float(timing.get("quote_to_submit_seconds"))),
        "phase_seconds": dict(sorted(compact_phases.items())),
    }


def _missing_fields(values: Mapping[str, Any]) -> list[str]:
    return [key for key, value in values.items() if value is None]


def _first_float(
    row: Mapping[str, Any],
    keys: Sequence[str],
    *,
    default: float | None = None,
) -> float | None:
    for key in keys:
        value = _float(row.get(key))
        if value is not None:
            return value
    return default


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
