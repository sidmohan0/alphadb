import json

import pytest
from pydantic import ValidationError

from alphadb.markets.cli import main, render_market_json, render_market_list
from alphadb.markets.registry import MarketRegistry, default_market_registry
from alphadb.markets.spec import MarketSpec, kxbtc15m_spec


def test_default_registry_contains_kxbtc15m() -> None:
    spec = default_market_registry().get("KXBTC15M")

    assert spec.series == "KXBTC15M"
    assert spec.underlying == "BTC"
    assert spec.horizon_minutes == 15
    assert spec.settlement_source == "CF Benchmarks RTI"
    assert spec.discovery_rules.handle_every_instance is True
    assert spec.feature_config.source == "coinbase_exchange"
    assert spec.feature_config.external_symbol == "BTC-USD"
    assert spec.feature_config.granularity_seconds == 60
    assert spec.feature_config.external_data_role == "feature_only"
    assert spec.label_function.outcome_source == "kalshi_settlement"
    assert spec.label_function.no_external_feature_truth is True
    assert spec.fee_assumptions.role == "taker"
    assert spec.fee_assumptions.taker_fee_multiplier == 0.07
    assert spec.fee_assumptions.maker_fee_multiplier == 0.0175
    assert spec.risk_config.bankroll_dollars == 1000.0
    assert spec.risk_config.live_stake_cap_dollars == 1.0
    assert spec.risk_config.max_daily_loss_dollars == 10.0
    assert spec.trading_cutoffs.decision_minute_offset == 12
    assert spec.trading_cutoffs.interval_seconds == 60
    assert spec.trading_cutoffs.settlement_buffer_seconds == 60
    assert spec.trading_cutoffs.time_in_force == "immediate_or_cancel"
    assert spec.trading_cutoffs.post_only is False


def test_market_spec_requires_core_fields() -> None:
    payload = kxbtc15m_spec().model_dump()
    payload.pop("series")

    with pytest.raises(ValidationError):
        MarketSpec(**payload)


def test_market_spec_rejects_unknown_fields() -> None:
    payload = kxbtc15m_spec().model_dump()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        MarketSpec(**payload)


def test_market_spec_rejects_inconsistent_discovery_series() -> None:
    payload = kxbtc15m_spec().model_dump()
    payload["discovery_rules"]["series_ticker"] = "KXETH15M"

    with pytest.raises(ValidationError, match="series_ticker"):
        MarketSpec(**payload)


def test_market_spec_requires_decision_before_horizon() -> None:
    payload = kxbtc15m_spec().model_dump()
    payload["trading_cutoffs"]["decision_minute_offset"] = 15

    with pytest.raises(ValidationError, match="decision_minute_offset"):
        MarketSpec(**payload)


def test_registry_rejects_duplicate_specs_and_unknown_series() -> None:
    registry = MarketRegistry()
    spec = kxbtc15m_spec()
    registry.register(spec)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(spec)

    with pytest.raises(KeyError, match="unknown market spec"):
        registry.get("KXETH15M")


def test_market_cli_renderers_expose_registered_spec() -> None:
    spec = kxbtc15m_spec()

    rendered_list = render_market_list([spec])
    assert "KXBTC15M BTC 15 BTC-USD immediate_or_cancel" in rendered_list

    rendered_json = json.loads(render_market_json(spec))
    assert rendered_json["series"] == "KXBTC15M"
    assert rendered_json["feature_config"]["external_symbol"] == "BTC-USD"


def test_market_cli_lists_specs(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list"]) == 0

    output = capsys.readouterr().out
    assert "KXBTC15M BTC 15 BTC-USD immediate_or_cancel" in output
