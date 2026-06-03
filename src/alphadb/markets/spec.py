"""Validated target-platform market specification contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DiscoveryRules(StrictModel):
    series_ticker: str = Field(min_length=1)
    recurrence_minutes: PositiveInt
    market_ticker_prefix: str = Field(min_length=1)
    handle_every_instance: bool


class FeatureConfig(StrictModel):
    source: str = Field(min_length=1)
    external_symbol: str = Field(min_length=1)
    granularity_seconds: PositiveInt
    external_data_role: Literal["feature_only"]


class LabelFunction(StrictModel):
    name: str = Field(min_length=1)
    outcome_source: str = Field(min_length=1)
    no_external_feature_truth: bool


class FeeAssumptions(StrictModel):
    role: Literal["taker", "maker"]
    taker_fee_multiplier: PositiveFloat
    maker_fee_multiplier: PositiveFloat


class RiskConfig(StrictModel):
    bankroll_dollars: PositiveFloat
    live_stake_cap_dollars: PositiveFloat
    max_daily_loss_dollars: PositiveFloat


class TradingCutoffs(StrictModel):
    decision_minute_offset: PositiveInt
    interval_seconds: PositiveInt
    settlement_buffer_seconds: PositiveInt
    min_ev: float
    post_only: bool
    time_in_force: Literal["immediate_or_cancel", "good_till_canceled"]
    self_trade_prevention_type: str = Field(min_length=1)


RuleVerificationStatus = Literal["confirmed", "requires_human_confirmation"]
PayoutComparator = Literal["above", "below", "exactly", "at_least", "between"]


class OfficialSettlementInputSource(StrictModel):
    source_role: Literal["official_settlement_input"]
    name: str = Field(min_length=1)
    index_ticker: str = Field(min_length=1)
    cadence_seconds: PositiveInt


class SettlementRuleReference(StrictModel):
    name: str = Field(min_length=1)
    verification_status: RuleVerificationStatus
    description: str = Field(min_length=1)


class PayoutComparatorRule(StrictModel):
    comparator: PayoutComparator
    threshold_count: PositiveInt
    lower_threshold_inclusive: bool | None
    upper_threshold_inclusive: bool | None
    exact_threshold_pays_yes: bool | None
    description: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_comparator_shape(self) -> PayoutComparatorRule:
        expected = {
            "above": (1, False, None, False),
            "below": (1, None, False, False),
            "exactly": (1, None, None, True),
            "at_least": (1, True, None, True),
            "between": (2, True, True, None),
        }[self.comparator]
        actual = (
            self.threshold_count,
            self.lower_threshold_inclusive,
            self.upper_threshold_inclusive,
            self.exact_threshold_pays_yes,
        )
        if actual != expected:
            raise ValueError(f"{self.comparator} comparator semantics do not match CRYPTO15M terms")
        return self


class FinalSettlementWindowRule(StrictModel):
    name: Literal["final_window_average"]
    duration_seconds: PositiveInt
    cadence_seconds: PositiveInt
    expected_print_count: PositiveInt
    ends_at: Literal["market_close"]

    @model_validator(mode="after")
    def validate_expected_print_count(self) -> FinalSettlementWindowRule:
        if self.duration_seconds % self.cadence_seconds != 0:
            raise ValueError("final window duration must be divisible by print cadence")
        expected = self.duration_seconds // self.cadence_seconds
        if self.expected_print_count != expected:
            raise ValueError("expected_print_count must match duration_seconds / cadence_seconds")
        return self


class SettlementInputQualityPolicy(StrictModel):
    missing_prints: Literal["invalidate_row"]
    duplicate_timestamps: Literal["invalidate_row"]
    incomplete_window: Literal["invalidate_row"]
    source_timestamp_after_decision: Literal["invalidate_row"]


class SettlementTimestampSemantics(StrictModel):
    authoritative_timestamp: Literal["official_effective_time"]
    timezone: Literal["UTC"]
    source_timestamp_field: str = Field(min_length=1)


class SettlementSpec(StrictModel):
    spec_version: str = Field(min_length=1)
    market_series: str = Field(min_length=1)
    settlement_family: Literal["listed_threshold_final_window_average"]
    official_input_source: OfficialSettlementInputSource
    payout_threshold_rule: SettlementRuleReference
    payout_comparator_rules: tuple[PayoutComparatorRule, ...]
    final_settlement_window: FinalSettlementWindowRule
    input_quality_policy: SettlementInputQualityPolicy
    timestamp_semantics: SettlementTimestampSemantics

    @model_validator(mode="after")
    def validate_consistency(self) -> SettlementSpec:
        if self.official_input_source.cadence_seconds != self.final_settlement_window.cadence_seconds:
            raise ValueError("official input cadence must match final settlement window cadence")
        expected_comparators = {"above", "below", "exactly", "at_least", "between"}
        comparators = {rule.comparator for rule in self.payout_comparator_rules}
        if comparators != expected_comparators:
            missing = sorted(expected_comparators - comparators)
            extra = sorted(comparators - expected_comparators)
            raise ValueError(f"payout comparator rules incomplete: missing={missing}, extra={extra}")
        if len(self.payout_comparator_rules) != len(comparators):
            raise ValueError("payout comparator rules must not contain duplicate comparators")
        return self


class MarketSpec(StrictModel):
    spec_version: str = Field(min_length=1)
    series: str = Field(min_length=1)
    underlying: str = Field(min_length=1)
    horizon_minutes: PositiveInt
    settlement_source: str = Field(min_length=1)
    settlement_reference: str = Field(min_length=1)
    settlement_spec: SettlementSpec | None = None
    discovery_rules: DiscoveryRules
    feature_config: FeatureConfig
    label_function: LabelFunction
    fee_assumptions: FeeAssumptions
    risk_config: RiskConfig
    trading_cutoffs: TradingCutoffs

    @model_validator(mode="after")
    def validate_consistency(self) -> MarketSpec:
        if self.discovery_rules.series_ticker != self.series:
            raise ValueError("discovery series_ticker must match series")
        if self.trading_cutoffs.decision_minute_offset >= self.horizon_minutes:
            raise ValueError("decision_minute_offset must be before market horizon")
        if self.settlement_spec is not None:
            if self.settlement_spec.market_series != self.series:
                raise ValueError("settlement_spec market_series must match series")
            if self.settlement_spec.official_input_source.name != self.settlement_source:
                raise ValueError("settlement_spec official source must match settlement_source")
        return self


def kxbtc15m_settlement_spec() -> SettlementSpec:
    return SettlementSpec(
        spec_version="kxbtc15m.settlement.v1",
        market_series="KXBTC15M",
        settlement_family="listed_threshold_final_window_average",
        official_input_source=OfficialSettlementInputSource(
            source_role="official_settlement_input",
            name="CF Benchmarks RTI",
            index_ticker="BRTI",
            cadence_seconds=1,
        ),
        payout_threshold_rule=SettlementRuleReference(
            name="listed_payout_threshold",
            verification_status="confirmed",
            description=(
                "Concrete KXBTC15M market metadata supplies listed price levels "
                "used as payout thresholds; CRYPTO15M terms do not define an "
                "opening-window-derived reference."
            ),
        ),
        payout_comparator_rules=kxbtc15m_payout_comparator_rules(),
        final_settlement_window=FinalSettlementWindowRule(
            name="final_window_average",
            duration_seconds=60,
            cadence_seconds=1,
            expected_print_count=60,
            ends_at="market_close",
        ),
        input_quality_policy=SettlementInputQualityPolicy(
            missing_prints="invalidate_row",
            duplicate_timestamps="invalidate_row",
            incomplete_window="invalidate_row",
            source_timestamp_after_decision="invalidate_row",
        ),
        timestamp_semantics=SettlementTimestampSemantics(
            authoritative_timestamp="official_effective_time",
            timezone="UTC",
            source_timestamp_field="effective_time_utc",
        ),
    )


def kxbtc15m_payout_comparator_rules() -> tuple[PayoutComparatorRule, ...]:
    return (
        PayoutComparatorRule(
            comparator="above",
            threshold_count=1,
            lower_threshold_inclusive=False,
            upper_threshold_inclusive=None,
            exact_threshold_pays_yes=False,
            description="Expiration value must be strictly greater than the listed threshold.",
        ),
        PayoutComparatorRule(
            comparator="below",
            threshold_count=1,
            lower_threshold_inclusive=None,
            upper_threshold_inclusive=False,
            exact_threshold_pays_yes=False,
            description="Expiration value must be strictly less than the listed threshold.",
        ),
        PayoutComparatorRule(
            comparator="exactly",
            threshold_count=1,
            lower_threshold_inclusive=None,
            upper_threshold_inclusive=None,
            exact_threshold_pays_yes=True,
            description=(
                "Expiration value must equal the listed threshold at the specified precision."
            ),
        ),
        PayoutComparatorRule(
            comparator="at_least",
            threshold_count=1,
            lower_threshold_inclusive=True,
            upper_threshold_inclusive=None,
            exact_threshold_pays_yes=True,
            description=(
                "Expiration value must be greater than or equal to the listed threshold."
            ),
        ),
        PayoutComparatorRule(
            comparator="between",
            threshold_count=2,
            lower_threshold_inclusive=True,
            upper_threshold_inclusive=True,
            exact_threshold_pays_yes=None,
            description=(
                "Expiration value must be greater than or equal to the lower threshold "
                "and less than or equal to the upper threshold."
            ),
        ),
    )


def kxbtc15m_spec() -> MarketSpec:
    return MarketSpec(
        spec_version="v1",
        series="KXBTC15M",
        underlying="BTC",
        horizon_minutes=15,
        settlement_source="CF Benchmarks RTI",
        settlement_reference=(
            "Kalshi crypto contracts settle from CF Benchmarks RTI; "
            "external BTC feeds are features only."
        ),
        settlement_spec=kxbtc15m_settlement_spec(),
        discovery_rules=DiscoveryRules(
            series_ticker="KXBTC15M",
            recurrence_minutes=15,
            market_ticker_prefix="KXBTC15M",
            handle_every_instance=True,
        ),
        feature_config=FeatureConfig(
            source="coinbase_exchange",
            external_symbol="BTC-USD",
            granularity_seconds=60,
            external_data_role="feature_only",
        ),
        label_function=LabelFunction(
            name="kalshi_market_result",
            outcome_source="kalshi_settlement",
            no_external_feature_truth=True,
        ),
        fee_assumptions=FeeAssumptions(
            role="taker",
            taker_fee_multiplier=0.07,
            maker_fee_multiplier=0.0175,
        ),
        risk_config=RiskConfig(
            bankroll_dollars=1000.0,
            live_stake_cap_dollars=1.0,
            max_daily_loss_dollars=10.0,
        ),
        trading_cutoffs=TradingCutoffs(
            decision_minute_offset=12,
            interval_seconds=60,
            settlement_buffer_seconds=60,
            min_ev=0.0,
            post_only=False,
            time_in_force="immediate_or_cancel",
            self_trade_prevention_type="taker_at_cross",
        ),
    )
