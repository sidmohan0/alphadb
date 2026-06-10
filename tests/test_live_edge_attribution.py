from __future__ import annotations

from alphadb.live_edge_attribution import (
    build_live_edge_attribution,
    summarize_live_edge_attribution_buckets,
)


def test_live_edge_attribution_decomposes_edge_below_min() -> None:
    attribution = build_live_edge_attribution(
        decision={
            "decision": "skip",
            "reason": "edge_below_min",
            "ticker": "KXBTC15M-EDGE",
            "side": "yes",
            "probability": 0.6,
            "price": 0.55,
            "fee": 0.02,
            "edge": 0.03,
        },
        runtime_controls={"min_edge": 0.05, "min_contract_price": 0.25},
        config={"quote_stale_seconds": 15, "coinbase_feature_stale_seconds": 90},
        freshness={"quote_age_seconds": 2.0, "coinbase_feature_age_seconds": 8.0},
        timing={"total_elapsed_seconds": 0.75, "phase_seconds": {"collection": 0.5}},
    )

    assert attribution["status"] == "available"
    assert attribution["market_ticker"] == "KXBTC15M-EDGE"
    assert attribution["raw_gap"] == 0.05
    assert attribution["fee_per_contract"] == 0.02
    assert attribution["edge"] == 0.03
    assert attribution["edge_shortfall"] == 0.02
    assert attribution["attribution_class"] == "threshold_drag"
    assert side_evaluation(attribution, "yes")["selected"] is True
    assert side_evaluation(attribution, "yes")["reason"] == "edge_below_min"
    assert attribution["freshness"]["quote_age_seconds"] == 2.0
    assert attribution["freshness"]["active_context"]["status"] == "fresh"
    assert attribution["fresh_quote_counterfactual"]["status"] == "unavailable"
    assert attribution["timing"]["phase_seconds"]["collection"] == 0.5


def test_live_edge_attribution_classifies_fee_and_freshness_drag() -> None:
    fee_drag = build_live_edge_attribution(
        decision={
            "decision": "skip",
            "reason": "edge_below_min",
            "side": "no",
            "probability": 0.52,
            "price": 0.5,
            "fee": 0.03,
        },
        runtime_controls={"min_edge": 0.01},
    )
    stale_quote = build_live_edge_attribution(
        decision={
            "decision": "skip",
            "reason": "edge_below_min",
            "side": "yes",
            "probability": 0.6,
            "price": 0.55,
            "fee": 0.01,
        },
        runtime_controls={"min_edge": 0.05},
        config={"quote_stale_seconds": 15},
        freshness={"quote_age_seconds": 22.0},
    )
    missing = build_live_edge_attribution(
        decision={"decision": "skip", "reason": "missing_orderbook_quote"},
    )

    assert fee_drag["attribution_class"] == "fee_drag"
    assert stale_quote["attribution_class"] == "quote_freshness_suspect"
    assert missing["status"] == "partial"
    assert missing["attribution_class"] == "missing_quote_context"


def test_brti_primary_uses_brti_context_not_coinbase_diagnostic_age() -> None:
    attribution = build_live_edge_attribution(
        decision={
            "decision": "skip",
            "reason": "edge_below_min",
            "side": "yes",
            "probability": 0.6,
            "price": 0.55,
            "fee": 0.01,
            "edge": 0.04,
        },
        config={
            "market_context_source": "brti_primary",
            "quote_stale_seconds": 15,
            "coinbase_feature_stale_seconds": 90,
        },
        runtime_controls={"min_edge": 0.05, "market_context_source": "brti_primary"},
        freshness={
            "market_context_source": "brti_primary",
            "quote_age_seconds": 2.0,
            "coinbase_feature_age_seconds": 300.0,
            "brti_context_age_seconds": 1.0,
            "brti_freshness_limit_seconds": 5.0,
            "brti_context_status": "usable",
        },
    )

    assert attribution["attribution_class"] == "threshold_drag"
    assert attribution["freshness"]["active_context"] == {
        "market_context_source": "brti_primary",
        "evidence_source": "brti_latest_context",
        "status": "fresh",
        "age_seconds": 1.0,
        "stale_seconds": 5.0,
        "source_timestamp": None,
        "context_status": "usable",
    }


def test_context_freshness_tracks_coinbase_and_fixture_modes() -> None:
    coinbase = build_live_edge_attribution(
        decision={
            "decision": "skip",
            "reason": "edge_below_min",
            "side": "yes",
            "probability": 0.6,
            "price": 0.55,
            "fee": 0.01,
            "edge": 0.04,
        },
        config={
            "market_context_source": "coinbase_primary",
            "coinbase_feature_stale_seconds": 90,
        },
        runtime_controls={"min_edge": 0.05},
        freshness={
            "market_context_source": "coinbase_primary",
            "coinbase_feature_age_seconds": 120.0,
        },
    )
    fixture = build_live_edge_attribution(
        decision={
            "decision": "skip",
            "reason": "edge_below_min",
            "side": "yes",
            "probability": 0.6,
            "price": 0.55,
            "fee": 0.01,
            "edge": 0.04,
        },
        config={"market_context_source": "fixture"},
        runtime_controls={"min_edge": 0.05, "market_context_source": "fixture"},
        freshness={"market_context_source": "fixture"},
    )

    assert coinbase["attribution_class"] == "coinbase_freshness_suspect"
    assert coinbase["freshness"]["active_context"]["status"] == "stale"
    assert fixture["attribution_class"] == "threshold_drag"
    assert fixture["freshness"]["active_context"]["status"] == "not_applicable"


def test_live_edge_attribution_bucket_summary_counts_classes() -> None:
    assert summarize_live_edge_attribution_buckets(
        [
            {"attribution_class": "threshold_drag"},
            {"attribution_class": "fee_drag"},
            {"attribution_class": "threshold_drag"},
            {},
        ]
    ) == [
        {"attribution_class": "threshold_drag", "count": 2},
        {"attribution_class": "fee_drag", "count": 1},
        {"attribution_class": "unknown", "count": 1},
    ]


def test_live_edge_attribution_exposes_yes_and_no_evaluations_for_negative_yes_gap() -> None:
    attribution = build_live_edge_attribution(
        decision={
            "decision": "skip",
            "reason": "edge_below_min",
            "ticker": "KXBTC15M-NEGATIVE-YES",
            "side": "yes",
            "fair_value": 0.6147,
            "price": 0.999,
            "fee_per_contract": 0.00007,
            "edge": -0.38437,
        },
        source_row={
            "ticker": "KXBTC15M-NEGATIVE-YES",
            "p_yes": 0.6147,
            "yes_ask": 0.999,
            "no_ask": 0.99,
        },
        runtime_controls={"min_edge": 0.0, "min_contract_price": 0.25},
    )

    yes = side_evaluation(attribution, "yes")
    no = side_evaluation(attribution, "no")

    assert attribution["side_evaluation_summary"] == {
        "selected_side": "yes",
        "best_side": "yes",
        "selected_reason": "edge_below_min",
        "selected_status": "below_min_edge",
    }
    assert yes["selected"] is True
    assert yes["raw_gap"] == -0.3843
    assert yes["edge"] == -0.38437
    assert yes["edge_cleared"] is False
    assert no["selected"] is False
    assert no["probability"] == 0.3853
    assert no["raw_gap"] == -0.6047
    assert no["reason"] == "edge_below_min"
    assert no["comparison_reason"] == "not_selected_worse_edge"


def test_live_edge_attribution_exposes_no_selected_side_evaluation() -> None:
    attribution = build_live_edge_attribution(
        decision={
            "decision": "trade",
            "reason": "edge_met",
            "ticker": "KXBTC15M-NO",
            "side": "no",
            "fair_value": 0.7,
            "price": 0.5,
            "fee_per_contract": 0.0175,
            "edge": 0.1825,
        },
        source_row={
            "ticker": "KXBTC15M-NO",
            "p_yes": 0.3,
            "yes_ask": 0.8,
            "no_ask": 0.5,
        },
        runtime_controls={"min_edge": 0.05, "min_contract_price": 0.25},
    )

    yes = side_evaluation(attribution, "yes")
    no = side_evaluation(attribution, "no")

    assert attribution["side"] == "no"
    assert attribution["side_evaluation_summary"]["best_side"] == "no"
    assert yes["selected"] is False
    assert yes["status"] == "below_min_edge"
    assert yes["edge"] == -0.5112
    assert no["selected"] is True
    assert no["status"] == "cleared"
    assert no["edge_cleared"] is True
    assert no["edge"] == 0.1825


def test_live_edge_attribution_marks_missing_or_invalid_opposite_side() -> None:
    missing_no = build_live_edge_attribution(
        decision={
            "decision": "skip",
            "reason": "edge_below_min",
            "ticker": "KXBTC15M-MISSING-NO",
            "side": "yes",
            "fair_value": 0.6,
            "price": 0.55,
            "fee": 0.017325,
            "edge": 0.032675,
        },
        source_row={
            "ticker": "KXBTC15M-MISSING-NO",
            "p_yes": 0.6,
            "yes_ask": 0.55,
        },
        runtime_controls={"min_edge": 0.05, "min_contract_price": 0.25},
    )
    invalid_no = build_live_edge_attribution(
        decision={
            "decision": "skip",
            "reason": "edge_below_min",
            "ticker": "KXBTC15M-INVALID-NO",
            "side": "yes",
            "fair_value": 0.6,
            "price": 0.55,
            "fee": 0.017325,
            "edge": 0.032675,
        },
        source_row={
            "ticker": "KXBTC15M-INVALID-NO",
            "p_yes": 0.6,
            "yes_ask": 0.55,
            "no_ask": 1.0,
        },
        runtime_controls={"min_edge": 0.05, "min_contract_price": 0.25},
    )

    assert side_evaluation(missing_no, "no")["status"] == "unavailable"
    assert side_evaluation(missing_no, "no")["reason"] == "missing_executable_price"
    assert (
        side_evaluation(missing_no, "no")["comparison_reason"]
        == "not_selected_missing_executable_price"
    )
    assert side_evaluation(invalid_no, "no")["status"] == "unavailable"
    assert side_evaluation(invalid_no, "no")["reason"] == "invalid_executable_price"
    assert (
        side_evaluation(invalid_no, "no")["comparison_reason"]
        == "not_selected_invalid_executable_price"
    )


def test_live_edge_attribution_marks_both_sides_below_minimum() -> None:
    attribution = build_live_edge_attribution(
        decision={
            "decision": "skip",
            "reason": "edge_below_min",
            "ticker": "KXBTC15M-BOTH-BELOW",
            "side": "yes",
            "fair_value": 0.51,
            "price": 0.5,
            "fee": 0.0175,
            "edge": -0.0075,
        },
        source_row={
            "ticker": "KXBTC15M-BOTH-BELOW",
            "p_yes": 0.51,
            "yes_ask": 0.5,
            "no_ask": 0.5,
        },
        runtime_controls={"min_edge": 0.05, "min_contract_price": 0.25},
    )

    assert side_evaluation(attribution, "yes")["status"] == "below_min_edge"
    assert side_evaluation(attribution, "no")["status"] == "below_min_edge"
    assert side_evaluation(attribution, "yes")["edge_cleared"] is False
    assert side_evaluation(attribution, "no")["edge_cleared"] is False


def side_evaluation(attribution: dict[str, object], side: str) -> dict[str, object]:
    return next(
        item
        for item in attribution["side_evaluations"]  # type: ignore[index]
        if item["side"] == side
    )
