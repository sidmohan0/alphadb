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
