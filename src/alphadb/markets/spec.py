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


class MarketSpec(StrictModel):
    spec_version: str = Field(min_length=1)
    series: str = Field(min_length=1)
    underlying: str = Field(min_length=1)
    horizon_minutes: PositiveInt
    settlement_source: str = Field(min_length=1)
    settlement_reference: str = Field(min_length=1)
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
        return self


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
