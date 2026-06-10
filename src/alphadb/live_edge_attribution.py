"""Live edge attribution payloads for fair-value operator diagnostics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "alphadb_live_edge_attribution.v1"
MARKET_CONTEXT_COINBASE_PRIMARY = "coinbase_primary"
MARKET_CONTEXT_BRTI_PRIMARY = "brti_primary"
MARKET_CONTEXT_FIXTURE = "fixture"
DEFAULT_TAKER_FEE_MULTIPLIER = 0.07


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

    fee_multiplier = _first_float(
        runtime_controls_map,
        ("taker_fee_multiplier",),
        default=_first_float(
            snapshot,
            ("taker_fee_multiplier",),
            default=_first_float(
                config_map,
                ("taker_fee_multiplier",),
                default=DEFAULT_TAKER_FEE_MULTIPLIER,
            ),
        ),
    )
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
    market_context_source = _market_context_source(
        freshness=freshness_map,
        source_row=source_map,
        config=config_map,
        runtime_controls=runtime_controls_map,
        snapshot=snapshot,
    )
    active_context = active_context_freshness(
        market_context_source=market_context_source,
        freshness=freshness_map,
        source_row=source_map,
        config=config_map,
    )
    side_evaluations = build_live_side_evaluations(
        decision=decision_map,
        source_row=source_map,
        selected_side=side,
        min_edge=min_edge,
        min_contract_price=min_contract_price,
        taker_fee_multiplier=(
            fee_multiplier
            if fee_multiplier is not None
            else DEFAULT_TAKER_FEE_MULTIPLIER
        ),
    )
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
        "side_evaluations": side_evaluations,
        "side_evaluation_summary": side_evaluation_summary(
            side_evaluations=side_evaluations,
            selected_side=side,
        ),
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
            active_context_source=_text(active_context.get("evidence_source")),
            active_context_status=_text(active_context.get("status")),
            active_context_age_seconds=_float(active_context.get("age_seconds")),
            active_context_stale_seconds=_float(active_context.get("stale_seconds")),
            missing_fields=missing_fields,
        ),
        "freshness": {
            "market_context_source": market_context_source,
            "quote_seen_at": freshness_map.get("quote_seen_at"),
            "quote_age_seconds": _round(quote_age),
            "coinbase_max_source_event_timestamp": freshness_map.get(
                "coinbase_max_source_event_timestamp"
            ),
            "coinbase_feature_age_seconds": _round(coinbase_age),
            "brti_source_timestamp": freshness_map.get("brti_source_timestamp"),
            "brti_context_age_seconds": _round(
                _float(freshness_map.get("brti_context_age_seconds"))
            ),
            "brti_context_status": freshness_map.get("brti_context_status"),
            "quote_stale_seconds": _round(quote_stale_seconds),
            "coinbase_feature_stale_seconds": _round(coinbase_stale_seconds),
            "active_context": active_context,
        },
        "timing": compact_timing(timing_map),
        "fresh_quote_counterfactual": fresh_quote_counterfactual_status(
            decision=decision_map,
            source_row=source_map,
            freshness=freshness_map,
        ),
        "missing_fields": missing_fields,
    }


def build_live_side_evaluations(
    *,
    decision: Mapping[str, Any],
    source_row: Mapping[str, Any],
    selected_side: str | None,
    min_edge: float | None,
    min_contract_price: float | None,
    taker_fee_multiplier: float,
) -> list[dict[str, Any]]:
    probability_yes = _probability_yes(decision=decision, source_row=source_row)
    evaluations = [
        build_live_side_evaluation(
            side="yes",
            probability_yes=probability_yes,
            decision=decision,
            source_row=source_row,
            selected_side=selected_side,
            min_edge=min_edge,
            min_contract_price=min_contract_price,
            taker_fee_multiplier=taker_fee_multiplier,
        ),
        build_live_side_evaluation(
            side="no",
            probability_yes=probability_yes,
            decision=decision,
            source_row=source_row,
            selected_side=selected_side,
            min_edge=min_edge,
            min_contract_price=min_contract_price,
            taker_fee_multiplier=taker_fee_multiplier,
        ),
    ]
    return side_evaluations_with_selection_context(
        side_evaluations=evaluations,
        selected_side=selected_side,
    )


def build_live_side_evaluation(
    *,
    side: str,
    probability_yes: float | None,
    decision: Mapping[str, Any],
    source_row: Mapping[str, Any],
    selected_side: str | None,
    min_edge: float | None,
    min_contract_price: float | None,
    taker_fee_multiplier: float,
) -> dict[str, Any]:
    selected = selected_side == side
    probability = _side_probability(side, probability_yes)
    price = _side_price(side=side, decision=decision, source_row=source_row, selected=selected)
    explicit_fee = _side_fee(side=side, decision=decision, source_row=source_row, selected=selected)
    fee = explicit_fee if explicit_fee is not None else _taker_fee(price, taker_fee_multiplier)
    raw_gap = (
        round(probability - price, 6)
        if probability is not None and price is not None
        else None
    )
    edge = (
        round(raw_gap - fee, 6)
        if raw_gap is not None and fee is not None
        else None
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
    valid, invalid_reason = _side_validity(probability=probability, price=price)
    status, reason = side_evaluation_status(
        valid=valid,
        invalid_reason=invalid_reason,
        price=price,
        min_contract_price=min_contract_price,
        edge=edge,
        min_edge=min_edge,
    )
    return {
        "side": side,
        "selected": selected,
        "valid": valid,
        "status": status,
        "reason": reason,
        "comparison_reason": None,
        "probability": _round(probability),
        "fair_value": _round(probability),
        "price": _round(price),
        "fee_per_contract": _round(fee),
        "raw_gap": _round(raw_gap),
        "edge": _round(edge),
        "min_edge": _round(min_edge),
        "edge_shortfall": _round(edge_shortfall),
        "edge_margin": _round(edge_margin),
        "edge_cleared": edge is not None and min_edge is not None and edge >= min_edge,
        "min_contract_price": _round(min_contract_price),
    }


def side_evaluations_with_selection_context(
    *,
    side_evaluations: Sequence[dict[str, Any]],
    selected_side: str | None,
) -> list[dict[str, Any]]:
    selected = next(
        (
            evaluation
            for evaluation in side_evaluations
            if _text(evaluation.get("side")) == selected_side
        ),
        None,
    )
    selected_edge = _float(selected.get("edge")) if selected else None
    annotated: list[dict[str, Any]] = []
    for evaluation in side_evaluations:
        reason = side_comparison_reason(
            evaluation=evaluation,
            selected_side=selected_side,
            selected_edge=selected_edge,
        )
        annotated.append({**evaluation, "comparison_reason": reason})
    return annotated


def side_comparison_reason(
    *,
    evaluation: Mapping[str, Any],
    selected_side: str | None,
    selected_edge: float | None,
) -> str | None:
    side = _text(evaluation.get("side"))
    if selected_side is not None and side == selected_side:
        return "selected"
    status = _text(evaluation.get("status"))
    reason = _text(evaluation.get("reason"))
    if status == "unavailable":
        return f"not_selected_{reason or 'unavailable'}"
    if reason == "price_below_min_contract":
        return "not_selected_price_below_min_contract"
    edge = _float(evaluation.get("edge"))
    if edge is not None and selected_edge is not None:
        if edge < selected_edge:
            return "not_selected_worse_edge"
        if edge == selected_edge:
            return "not_selected_tie_break"
        return "not_selected_despite_higher_edge"
    if reason:
        return f"not_selected_{reason}"
    return "not_selected"


def side_evaluation_summary(
    *,
    side_evaluations: Sequence[Mapping[str, Any]],
    selected_side: str | None,
) -> dict[str, Any]:
    valid = [
        evaluation
        for evaluation in side_evaluations
        if evaluation.get("valid") is True and _float(evaluation.get("edge")) is not None
    ]
    best = max(
        valid,
        key=lambda evaluation: (
            _float(evaluation.get("edge")) or float("-inf"),
            _text(evaluation.get("side")) or "",
        ),
        default=None,
    )
    selected = next(
        (
            evaluation
            for evaluation in side_evaluations
            if _text(evaluation.get("side")) == selected_side
        ),
        None,
    )
    return {
        "selected_side": selected_side,
        "best_side": _text(best.get("side")) if best else None,
        "selected_reason": _text(selected.get("reason")) if selected else None,
        "selected_status": _text(selected.get("status")) if selected else None,
    }


def side_evaluation_status(
    *,
    valid: bool,
    invalid_reason: str | None,
    price: float | None,
    min_contract_price: float | None,
    edge: float | None,
    min_edge: float | None,
) -> tuple[str, str | None]:
    if not valid:
        return "unavailable", invalid_reason
    if (
        price is not None
        and min_contract_price is not None
        and price < min_contract_price
    ):
        return "blocked", "price_below_min_contract"
    if edge is not None and min_edge is not None and edge < min_edge:
        return "below_min_edge", "edge_below_min"
    if edge is not None and min_edge is not None and edge >= min_edge:
        return "cleared", "edge_met"
    return "available", None


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
    active_context_source: str | None = None,
    active_context_status: str | None = None,
    active_context_age_seconds: float | None = None,
    active_context_stale_seconds: float | None = None,
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
    if active_context_source == "brti_latest_context":
        if _active_context_is_stale(
            status=active_context_status,
            age_seconds=active_context_age_seconds,
            stale_seconds=active_context_stale_seconds,
        ):
            return "brti_freshness_suspect"
    if active_context_source == "coinbase_features":
        if _active_context_is_stale(
            status=active_context_status,
            age_seconds=active_context_age_seconds,
            stale_seconds=active_context_stale_seconds,
        ):
            return "coinbase_freshness_suspect"
    if (
        active_context_source in (None, "coinbase_features")
        and coinbase_feature_age_seconds is not None
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


def active_context_freshness(
    *,
    market_context_source: str,
    freshness: Mapping[str, Any],
    source_row: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the freshness evidence for the active market context source only."""

    if market_context_source == MARKET_CONTEXT_BRTI_PRIMARY:
        age = _first_float(
            freshness,
            ("brti_context_age_seconds",),
            default=_float(source_row.get("brti_context_age_seconds")),
        )
        stale_seconds = _first_float(
            freshness,
            ("brti_freshness_limit_seconds",),
            default=_first_float(
                source_row,
                ("brti_freshness_limit_seconds",),
                default=_float(config.get("brti_freshness_limit_seconds")),
            ),
        )
        raw_status = _text(
            freshness.get("brti_context_status")
            or source_row.get("brti_context_status")
            or source_row.get("market_context_status")
        )
        status = _context_status(
            raw_status=raw_status,
            age_seconds=age,
            stale_seconds=stale_seconds,
        )
        return {
            "market_context_source": market_context_source,
            "evidence_source": "brti_latest_context",
            "status": status,
            "age_seconds": _round(age),
            "stale_seconds": _round(stale_seconds),
            "source_timestamp": freshness.get("brti_source_timestamp")
            or source_row.get("brti_source_timestamp"),
            "context_status": raw_status,
        }
    if market_context_source == MARKET_CONTEXT_FIXTURE:
        return {
            "market_context_source": market_context_source,
            "evidence_source": "fixture",
            "status": "not_applicable",
            "age_seconds": None,
            "stale_seconds": None,
            "source_timestamp": None,
            "context_status": "not_applicable",
        }

    age = _first_float(
        freshness,
        ("coinbase_feature_age_seconds",),
        default=_float(source_row.get("coinbase_feature_age_seconds")),
    )
    stale_seconds = _float(config.get("coinbase_feature_stale_seconds"))
    status = _context_status(
        raw_status=_text(source_row.get("market_context_status")),
        age_seconds=age,
        stale_seconds=stale_seconds,
    )
    return {
        "market_context_source": market_context_source,
        "evidence_source": "coinbase_features",
        "status": status,
        "age_seconds": _round(age),
        "stale_seconds": _round(stale_seconds),
        "source_timestamp": freshness.get("coinbase_max_source_event_timestamp")
        or source_row.get("coinbase_max_source_event_timestamp"),
        "context_status": _text(source_row.get("market_context_status")),
    }


def fresh_quote_counterfactual_status(
    *,
    decision: Mapping[str, Any],
    source_row: Mapping[str, Any],
    freshness: Mapping[str, Any],
) -> dict[str, Any]:
    explicit = _mapping(
        freshness.get("fresh_quote_counterfactual")
        or source_row.get("fresh_quote_counterfactual")
        or decision.get("fresh_quote_counterfactual")
    )
    if explicit:
        status = _text(explicit.get("status")) or "available"
        return {
            "status": status,
            "basis": _text(explicit.get("basis")),
            "fresh_quote_seen_at": explicit.get("fresh_quote_seen_at"),
            "edge_at_submit": _round(_float(explicit.get("edge_at_submit"))),
            "counterfactual_pnl_if_available": _round(
                _float(explicit.get("counterfactual_pnl_if_available"))
            ),
        }
    return {
        "status": "unavailable",
        "basis": "independent_fresh_quote_evidence_missing",
        "fresh_quote_seen_at": None,
        "edge_at_submit": None,
        "counterfactual_pnl_if_available": None,
    }


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


def _market_context_source(
    *,
    freshness: Mapping[str, Any],
    source_row: Mapping[str, Any],
    config: Mapping[str, Any],
    runtime_controls: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> str:
    return (
        _text(freshness.get("market_context_source"))
        or _text(source_row.get("market_context_source"))
        or _text(runtime_controls.get("market_context_source"))
        or _text(snapshot.get("market_context_source"))
        or _text(config.get("market_context_source"))
        or MARKET_CONTEXT_COINBASE_PRIMARY
    )


def _context_status(
    *,
    raw_status: str | None,
    age_seconds: float | None,
    stale_seconds: float | None,
) -> str:
    if raw_status in {"missing", "unavailable", "unusable"}:
        return raw_status
    if age_seconds is None:
        return "missing"
    if stale_seconds is not None and age_seconds > stale_seconds:
        return "stale"
    return "fresh"


def _active_context_is_stale(
    *,
    status: str | None,
    age_seconds: float | None,
    stale_seconds: float | None,
) -> bool:
    if status == "stale":
        return True
    if age_seconds is not None and stale_seconds is not None:
        return age_seconds > stale_seconds
    return False


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


def _probability_yes(
    *,
    decision: Mapping[str, Any],
    source_row: Mapping[str, Any],
) -> float | None:
    probability_yes = _first_float(
        source_row,
        ("p_yes", "probability_yes"),
        default=_float(decision.get("probability_yes")),
    )
    if probability_yes is not None:
        return probability_yes
    selected_probability = _first_float(decision, ("fair_value", "probability"))
    selected_side = _text(decision.get("side"))
    if selected_probability is None or selected_side not in {"yes", "no"}:
        return None
    if selected_side == "yes":
        return selected_probability
    return 1.0 - selected_probability


def _side_probability(side: str, probability_yes: float | None) -> float | None:
    if probability_yes is None:
        return None
    return probability_yes if side == "yes" else 1.0 - probability_yes


def _side_price(
    *,
    side: str,
    decision: Mapping[str, Any],
    source_row: Mapping[str, Any],
    selected: bool,
) -> float | None:
    side_keys = (
        ("yes_ask", "yes_ask_dollars", "executable_yes_price")
        if side == "yes"
        else ("no_ask", "no_ask_dollars", "executable_no_price")
    )
    price = _first_float(source_row, side_keys)
    if price is not None:
        return price
    if selected:
        return _first_float(decision, ("price", *side_keys))
    return None


def _side_fee(
    *,
    side: str,
    decision: Mapping[str, Any],
    source_row: Mapping[str, Any],
    selected: bool,
) -> float | None:
    side_keys = ("yes_fee", "yes_fee_per_contract") if side == "yes" else (
        "no_fee",
        "no_fee_per_contract",
    )
    fee = _first_float(source_row, side_keys)
    if fee is not None:
        return fee
    if selected:
        return _first_float(decision, ("fee_per_contract", "fee", *side_keys))
    return None


def _side_validity(
    *,
    probability: float | None,
    price: float | None,
) -> tuple[bool, str | None]:
    if probability is None:
        return False, "missing_probability"
    if price is None:
        return False, "missing_executable_price"
    if probability < 0.0 or probability > 1.0:
        return False, "invalid_probability"
    if price <= 0.0 or price >= 1.0:
        return False, "invalid_executable_price"
    return True, None


def _taker_fee(price: float | None, taker_fee_multiplier: float) -> float | None:
    if price is None or price <= 0.0 or price >= 1.0:
        return None
    return round(taker_fee_multiplier * price * (1.0 - price), 6)


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
