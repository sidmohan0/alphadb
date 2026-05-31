from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest

from alphadb.collectors.kalshi_rest import FixtureKalshiRestClient, RestKxbtc15mCollector
from alphadb.config import settings_from_env
from alphadb.decision_engine.engine import (
    DecisionEngine,
    DecisionInput,
    DecisionPolicy,
    DecisionRepository,
    ExecutableQuotes,
    ModelOutput,
    build_decision_input,
    taker_fee_dollars,
)
from alphadb.features.ledger import FeatureRow, FeatureRowBuilder
from alphadb.markets.spec import kxbtc15m_spec
from alphadb.model_registry.registry import ModelRegistration, ModelRegistryRepository
from alphadb.state.repository import OperationalStateRepository


def decision_dependencies_or_skip() -> tuple[
    OperationalStateRepository,
    ModelRegistryRepository,
]:
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


def feature_row_fixture(repository: OperationalStateRepository, registry: ModelRegistryRepository) -> FeatureRow:
    model = registry.register(
        ModelRegistration(
            series="KXBTC15M",
            model_name="decision-engine-test",
            model_version=f"v-{uuid4().hex}",
            artifact_uri="artifacts/models/decision-engine-test/model.joblib",
            artifact_sha256="f" * 64,
            feature_version="features.kxbtc15m.v1",
            calibration_version="calibration.none.v1",
            dataset_id="dataset_decision_engine_v1",
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
    return FeatureRowBuilder(repository.database_url).build(
        run_id=summary.platform_run_id,
        market_ticker=summary.market_tickers[0],
        model_id=model.model_id,
        decision_timestamp=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
    )


def test_decision_engine_trades_best_positive_ev_and_persists_output() -> None:
    repository, registry = decision_dependencies_or_skip()
    feature_row = feature_row_fixture(repository, registry)
    spec = kxbtc15m_spec()

    result = DecisionEngine().evaluate(
        build_decision_input(
            spec=spec,
            feature_row=feature_row,
            probability_yes=0.65,
            yes_ask_dollars=0.52,
            no_ask_dollars=0.53,
        )
    )
    persisted = DecisionRepository(repository.database_url).persist(result)
    rows = DecisionRepository(repository.database_url).list(run_id=feature_row.run_id)

    assert persisted.inserted is True
    assert persisted.outcome == "order_candidate"
    assert persisted.selected_side == "yes"
    assert persisted.skip_reason is None
    assert persisted.intended_quantity == 1
    assert persisted.selected_ev_dollars == pytest.approx(
        0.65 - 0.52 - taker_fee_dollars(0.52, spec)
    )
    assert rows[0]["metadata"]["feature_row_id"] == feature_row.feature_row_id
    assert rows[0]["metadata"]["intended_quantity"] == 1


def test_decision_engine_skips_when_expected_value_is_below_policy_threshold() -> None:
    repository, registry = decision_dependencies_or_skip()
    feature_row = feature_row_fixture(repository, registry)
    spec = kxbtc15m_spec()
    policy = DecisionPolicy.from_spec(spec)

    result = DecisionEngine().evaluate(
        decision_input=DecisionInput(
            spec=spec,
            feature_row=feature_row,
            model_output=ModelOutput(
                probability_yes=0.51,
                model_id=feature_row.model_id,
                feature_row_id=feature_row.feature_row_id,
            ),
            executable_quotes=ExecutableQuotes(yes_ask_dollars=0.52, no_ask_dollars=0.51),
            policy=policy,
        )
    )

    assert result.outcome == "skip"
    assert result.selected_side is None
    assert result.skip_reason == "ev_below_threshold"
    assert result.intended_quantity == 0


def test_decision_engine_selects_no_side_when_no_has_better_ev() -> None:
    repository, registry = decision_dependencies_or_skip()
    feature_row = feature_row_fixture(repository, registry)

    result = DecisionEngine().evaluate(
        build_decision_input(
            spec=kxbtc15m_spec(),
            feature_row=feature_row,
            probability_yes=0.35,
            yes_ask_dollars=0.66,
            no_ask_dollars=0.50,
        )
    )

    assert result.outcome == "order_candidate"
    assert result.selected_side == "no"
    assert result.selected_ev_dollars is not None
    assert result.selected_ev_dollars > 0


def test_decision_engine_handles_quote_edge_cases_and_fee_assumptions() -> None:
    repository, registry = decision_dependencies_or_skip()
    feature_row = feature_row_fixture(repository, registry)
    spec = kxbtc15m_spec()

    missing_quotes = DecisionEngine().evaluate(
        DecisionInput(
            spec=spec,
            feature_row=feature_row,
            model_output=ModelOutput(
                probability_yes=0.65,
                model_id=feature_row.model_id,
                feature_row_id=feature_row.feature_row_id,
            ),
            executable_quotes=ExecutableQuotes(yes_ask_dollars=None, no_ask_dollars=None),
            policy=DecisionPolicy.from_spec(spec),
        )
    )
    invalid_quote = DecisionEngine().evaluate(
        build_decision_input(
            spec=spec,
            feature_row=feature_row,
            probability_yes=0.99,
            yes_ask_dollars=1.0,
            no_ask_dollars=1.0,
        )
    )
    fee = taker_fee_dollars(0.52, spec)

    assert missing_quotes.skip_reason == "missing_executable_quote"
    assert invalid_quote.skip_reason == "missing_executable_quote"
    assert fee == pytest.approx(0.07 * 0.52 * 0.48)
