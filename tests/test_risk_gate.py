from datetime import UTC, date, datetime
from uuid import uuid4

import psycopg
import pytest

from alphadb.collectors.kalshi_rest import FixtureKalshiRestClient, RestKxbtc15mCollector
from alphadb.config import settings_from_env
from alphadb.decision_engine.engine import DecisionEngine, DecisionRepository, build_decision_input
from alphadb.features.ledger import FeatureRowBuilder
from alphadb.markets.spec import kxbtc15m_spec
from alphadb.model_registry.registry import ModelRegistration, ModelRegistryRepository
from alphadb.risk.gate import (
    RiskDecisionRepository,
    RiskGate,
    RiskPolicy,
    RiskState,
)
from alphadb.state.repository import OperationalStateRepository


def risk_dependencies_or_skip() -> tuple[OperationalStateRepository, ModelRegistryRepository]:
    repository = OperationalStateRepository(settings_from_env().database_url)
    try:
        with repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    repository.apply_migrations()
    return repository, ModelRegistryRepository(repository.database_url)


def persisted_decision(
    repository: OperationalStateRepository,
    registry: ModelRegistryRepository,
    *,
    probability_yes: float = 0.65,
    yes_ask_dollars: float = 0.52,
    no_ask_dollars: float = 0.53,
):
    model = registry.register(
        ModelRegistration(
            series="KXBTC15M",
            model_name="risk-gate-test",
            model_version=f"v-{uuid4().hex}",
            artifact_uri="artifacts/models/risk-gate-test/model.joblib",
            artifact_sha256="1" * 64,
            feature_version="features.kxbtc15m.v1",
            calibration_version="calibration.none.v1",
            dataset_id="dataset_risk_gate_v1",
        )
    )
    collector = RestKxbtc15mCollector(
        database_url=repository.database_url,
        client=FixtureKalshiRestClient(),
        source_mode="fixture",
    )
    summary = collector.collect(
        series="KXBTC15M",
        max_markets=1,
        now=datetime(2026, 5, 31, 21, 12, tzinfo=UTC),
    )
    feature_row = FeatureRowBuilder(repository.database_url).build(
        run_id=summary.platform_run_id,
        market_ticker=summary.market_tickers[0],
        model_id=model.model_id,
        decision_timestamp=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
    )
    decision = DecisionEngine().evaluate(
        build_decision_input(
            spec=kxbtc15m_spec(),
            feature_row=feature_row,
            probability_yes=probability_yes,
            yes_ask_dollars=yes_ask_dollars,
            no_ask_dollars=no_ask_dollars,
        )
    )
    return DecisionRepository(repository.database_url).persist(decision)


def test_risk_gate_approves_trade_and_persists_order_intent() -> None:
    repository, registry = risk_dependencies_or_skip()
    decision = persisted_decision(repository, registry)
    spec = kxbtc15m_spec()
    result = RiskGate().evaluate(
        decision=decision,
        policy=RiskPolicy.from_spec(spec),
        state=RiskState(trading_day=date(2026, 5, 31), realized_pnl_dollars=0.0),
    )
    persisted = RiskDecisionRepository(repository.database_url).persist(result)
    rows = RiskDecisionRepository(repository.database_url).list(decision_id=decision.decision_id)

    assert persisted.inserted is True
    assert persisted.status == "approved"
    assert persisted.reason is None
    assert persisted.order_intent is not None
    assert persisted.order_intent.side == "yes"
    assert persisted.order_intent.quantity == 1
    assert persisted.order_intent.max_cost_dollars == pytest.approx(0.52)
    assert rows[0]["status"] == "approved"
    assert rows[0]["order_intent_id"] == persisted.order_intent.order_intent_id


def test_risk_gate_denies_decision_skip_and_too_small_trade_budget() -> None:
    repository, registry = risk_dependencies_or_skip()
    skipped_decision = persisted_decision(
        repository,
        registry,
        probability_yes=0.51,
        yes_ask_dollars=0.52,
        no_ask_dollars=0.51,
    )
    trade_decision = persisted_decision(repository, registry)
    spec = kxbtc15m_spec()
    tiny_budget_policy = RiskPolicy(
        max_daily_loss_dollars=spec.risk_config.max_daily_loss_dollars,
        per_trade_max_cost_dollars=0.25,
        fail_closed=True,
        time_in_force=spec.trading_cutoffs.time_in_force,
    )

    skipped = RiskGate().evaluate(
        decision=skipped_decision,
        policy=RiskPolicy.from_spec(spec),
        state=RiskState(trading_day=date(2026, 5, 31), realized_pnl_dollars=0.0),
    )
    too_small = RiskGate().evaluate(
        decision=trade_decision,
        policy=tiny_budget_policy,
        state=RiskState(trading_day=date(2026, 5, 31), realized_pnl_dollars=0.0),
    )

    assert skipped.status == "denied"
    assert skipped.reason == "decision_skip"
    assert skipped.order_intent is None
    assert too_small.status == "denied"
    assert too_small.reason == "per_trade_limit"
    assert too_small.order_intent is None


def test_risk_gate_enforces_daily_loss_limit_and_missing_state_fail_closed() -> None:
    repository, registry = risk_dependencies_or_skip()
    decision = persisted_decision(repository, registry)
    spec = kxbtc15m_spec()

    loss_limit = RiskGate().evaluate(
        decision=decision,
        policy=RiskPolicy.from_spec(spec),
        state=RiskState(
            trading_day=date(2026, 5, 31),
            realized_pnl_dollars=-spec.risk_config.max_daily_loss_dollars,
        ),
    )
    missing_state = RiskGate().evaluate(
        decision=decision,
        policy=RiskPolicy.from_spec(spec),
        state=None,
    )

    assert loss_limit.status == "denied"
    assert loss_limit.reason == "daily_loss_limit"
    assert missing_state.status == "denied"
    assert missing_state.reason == "missing_risk_state"


def test_risk_gate_duplicate_instance_protection_returns_existing_authoritative_outcome() -> None:
    repository, registry = risk_dependencies_or_skip()
    decision = persisted_decision(repository, registry)
    spec = kxbtc15m_spec()
    repository_ = RiskDecisionRepository(repository.database_url)
    result = RiskGate().evaluate(
        decision=decision,
        policy=RiskPolicy.from_spec(spec),
        state=RiskState(trading_day=date(2026, 5, 31), realized_pnl_dollars=0.0),
    )

    first = repository_.persist(result)
    second = repository_.persist(result)

    assert first.inserted is True
    assert second.inserted is False
    assert second.risk_decision_id == first.risk_decision_id
    assert second.order_intent is not None
    assert first.order_intent is not None
    assert second.order_intent.order_intent_id == first.order_intent.order_intent_id
