from __future__ import annotations

import pytest

from alphadb.dashboard.strategy import (
    SPEC_SCHEMA_VERSION,
    compile_strategy_brief,
    validate_strategy_spec,
)


def test_strategy_brief_compiles_model_probability_spec_with_constrained_fields() -> None:
    result = compile_strategy_brief(
        "Use the BTC 15m machine learning model at minute 12 when edge is above 2% with $7 max."
    )

    assert result.status == "supported"
    assert result.selected_template == "model_probability"
    assert result.spec is not None
    assert result.spec["schema_version"] == SPEC_SCHEMA_VERSION
    assert result.spec["market"]["series"] == "KXBTC15M"
    assert result.spec["market"]["decision_minute"] == 12
    assert result.spec["trade_policy"]["execution"] == "taker_ioc"
    assert result.spec["trade_policy"]["min_edge"] == 0.02
    assert result.spec["trade_policy"]["max_order_dollars"] == 7.0


def test_strategy_brief_needs_confirmation_when_market_or_edge_is_missing() -> None:
    result = compile_strategy_brief("Trade funding reversals when the signal is extreme.")

    assert result.status == "needs_confirmation"
    assert result.selected_template == "external_signal_threshold"
    assert result.spec is not None
    assert "market.series" in result.missing_fields
    assert "trade_policy.min_edge" in result.missing_fields
    assert result.questions


def test_unsupported_brief_routes_without_fake_runnable_spec() -> None:
    result = compile_strategy_brief(
        "Train a reinforcement learning portfolio arbitrage strategy with maker limit orders."
    )

    assert result.status == "unsupported"
    assert result.spec is None
    assert "model_training" in result.missing_capabilities
    assert "maker_execution" in result.missing_capabilities


def test_strategy_spec_validation_rejects_non_mvp_execution_modes() -> None:
    result = compile_strategy_brief("Use BTC 15m fair value when edge is above 1%.")
    assert result.spec is not None
    spec = dict(result.spec)
    spec["trade_policy"] = {**spec["trade_policy"], "execution": "maker"}

    with pytest.raises(ValueError, match="taker_ioc"):
        validate_strategy_spec(spec)
