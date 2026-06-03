import json

import pytest
from pydantic import ValidationError

from alphadb.markets.cli import main, render_market_json, render_market_list
from alphadb.markets.registry import MarketRegistry, default_market_registry
from alphadb.markets.spec import (
    MarketSpec,
    PayoutComparatorRule,
    SettlementSpec,
    kxbtc15m_settlement_spec,
    kxbtc15m_spec,
)


def test_default_registry_contains_kxbtc15m() -> None:
    spec = default_market_registry().get("KXBTC15M")

    assert spec.series == "KXBTC15M"
    assert spec.underlying == "BTC"
    assert spec.horizon_minutes == 15
    assert spec.settlement_source == "CF Benchmarks RTI"
    assert spec.settlement_spec is not None
    assert spec.settlement_spec.market_series == "KXBTC15M"
    assert spec.settlement_spec.official_input_source.name == "CF Benchmarks RTI"
    assert spec.settlement_spec.official_input_source.index_ticker == "BRTI"
    assert spec.settlement_spec.official_input_source.cadence_seconds == 1
    assert spec.settlement_spec.payout_threshold_rule.name == "listed_payout_threshold"
    assert spec.settlement_spec.payout_threshold_rule.verification_status == "confirmed"
    comparator_rules = {
        rule.comparator: rule for rule in spec.settlement_spec.payout_comparator_rules
    }
    assert comparator_rules["above"].exact_threshold_pays_yes is False
    assert comparator_rules["below"].exact_threshold_pays_yes is False
    assert comparator_rules["exactly"].exact_threshold_pays_yes is True
    assert comparator_rules["at_least"].exact_threshold_pays_yes is True
    assert comparator_rules["between"].lower_threshold_inclusive is True
    assert comparator_rules["between"].upper_threshold_inclusive is True
    assert spec.settlement_spec.final_settlement_window.duration_seconds == 60
    assert spec.settlement_spec.final_settlement_window.cadence_seconds == 1
    assert spec.settlement_spec.final_settlement_window.expected_print_count == 60
    assert spec.settlement_spec.final_settlement_window.ends_at == "market_close"
    assert spec.settlement_spec.input_quality_policy.missing_prints == "invalidate_row"
    assert spec.settlement_spec.input_quality_policy.duplicate_timestamps == "invalidate_row"
    assert (
        spec.settlement_spec.timestamp_semantics.authoritative_timestamp
        == "official_effective_time"
    )
    assert spec.settlement_spec.timestamp_semantics.timezone == "UTC"
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


def test_market_spec_rejects_inconsistent_settlement_spec_series() -> None:
    payload = kxbtc15m_spec().model_dump()
    payload["settlement_spec"]["market_series"] = "KXETH15M"

    with pytest.raises(ValidationError, match="settlement_spec market_series"):
        MarketSpec(**payload)


def test_market_spec_rejects_inconsistent_settlement_source() -> None:
    payload = kxbtc15m_spec().model_dump()
    payload["settlement_spec"]["official_input_source"]["name"] = "Coinbase"

    with pytest.raises(ValidationError, match="official source"):
        MarketSpec(**payload)


def test_kxbtc15m_settlement_spec_encodes_structured_rules() -> None:
    settlement_spec = kxbtc15m_settlement_spec()

    assert settlement_spec.spec_version == "kxbtc15m.settlement.v1"
    assert settlement_spec.settlement_family == "listed_threshold_final_window_average"
    assert settlement_spec.official_input_source.source_role == "official_settlement_input"
    assert settlement_spec.payout_threshold_rule.name == "listed_payout_threshold"
    assert settlement_spec.final_settlement_window.expected_print_count == 60
    assert settlement_spec.input_quality_policy.incomplete_window == "invalidate_row"
    assert (
        settlement_spec.input_quality_policy.source_timestamp_after_decision
        == "invalidate_row"
    )
    assert settlement_spec.timestamp_semantics.source_timestamp_field == "effective_time_utc"


def test_kxbtc15m_comparator_rules_encode_exact_threshold_outcomes() -> None:
    settlement_spec = kxbtc15m_settlement_spec()
    comparator_rules = {
        rule.comparator: rule for rule in settlement_spec.payout_comparator_rules
    }

    assert set(comparator_rules) == {"above", "below", "exactly", "at_least", "between"}
    assert comparator_rules["above"].lower_threshold_inclusive is False
    assert comparator_rules["above"].exact_threshold_pays_yes is False
    assert comparator_rules["below"].upper_threshold_inclusive is False
    assert comparator_rules["below"].exact_threshold_pays_yes is False
    assert comparator_rules["exactly"].exact_threshold_pays_yes is True
    assert comparator_rules["at_least"].lower_threshold_inclusive is True
    assert comparator_rules["at_least"].exact_threshold_pays_yes is True
    assert comparator_rules["between"].threshold_count == 2
    assert comparator_rules["between"].lower_threshold_inclusive is True
    assert comparator_rules["between"].upper_threshold_inclusive is True


def test_settlement_spec_rejects_inconsistent_print_count() -> None:
    payload = kxbtc15m_settlement_spec().model_dump()
    payload["final_settlement_window"]["expected_print_count"] = 59

    with pytest.raises(ValidationError, match="expected_print_count"):
        SettlementSpec(**payload)


def test_settlement_spec_rejects_mismatched_cadence() -> None:
    payload = kxbtc15m_settlement_spec().model_dump()
    payload["official_input_source"]["cadence_seconds"] = 2

    with pytest.raises(ValidationError, match="cadence"):
        SettlementSpec(**payload)


def test_settlement_spec_requires_rule_fields() -> None:
    payload = kxbtc15m_settlement_spec().model_dump()
    payload.pop("payout_threshold_rule")

    with pytest.raises(ValidationError):
        SettlementSpec(**payload)


def test_settlement_spec_rejects_missing_comparator_rules() -> None:
    payload = kxbtc15m_settlement_spec().model_dump()
    payload["payout_comparator_rules"] = [
        rule for rule in payload["payout_comparator_rules"] if rule["comparator"] != "between"
    ]

    with pytest.raises(ValidationError, match="payout comparator rules"):
        SettlementSpec(**payload)


def test_settlement_spec_rejects_duplicate_comparator_rules() -> None:
    payload = kxbtc15m_settlement_spec().model_dump()
    payload["payout_comparator_rules"] = [
        *payload["payout_comparator_rules"],
        payload["payout_comparator_rules"][0],
    ]

    with pytest.raises(ValidationError, match="duplicate"):
        SettlementSpec(**payload)


def test_payout_comparator_rule_rejects_unconfirmed_semantics() -> None:
    with pytest.raises(ValidationError, match="above comparator semantics"):
        PayoutComparatorRule(
            comparator="above",
            threshold_count=1,
            lower_threshold_inclusive=True,
            upper_threshold_inclusive=None,
            exact_threshold_pays_yes=True,
            description="Incorrectly treats equality as a YES payout.",
        )


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
    assert rendered_json["settlement_spec"]["market_series"] == "KXBTC15M"
    assert rendered_json["settlement_spec"]["payout_threshold_rule"]["name"] == (
        "listed_payout_threshold"
    )
    assert rendered_json["settlement_spec"]["payout_comparator_rules"][0]["comparator"] == "above"


def test_market_cli_lists_specs(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list"]) == 0

    output = capsys.readouterr().out
    assert "KXBTC15M BTC 15 BTC-USD immediate_or_cancel" in output
