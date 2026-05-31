from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from alphadb.collectors.kalshi_rest import FixtureKalshiRestClient, RestKxbtc15mCollector
from alphadb.config import settings_from_env
from alphadb.events.log import RawEventLog
from alphadb.features.ledger import (
    FeatureRowBuilder,
    MissingFeatureEventsError,
    ModelFeatureCompatibilityError,
    NoLookaheadViolationError,
)
from alphadb.markets.spec import kxbtc15m_spec
from alphadb.model_registry.registry import ModelRegistration, ModelRegistryRepository
from alphadb.state.repository import OperationalStateRepository


def dependencies_or_skip() -> tuple[OperationalStateRepository, ModelRegistryRepository]:
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


def register_feature_model(registry: ModelRegistryRepository) -> str:
    model = registry.register(
        ModelRegistration(
            series="KXBTC15M",
            model_name="feature-ledger-test",
            model_version=f"v-{uuid4().hex}",
            artifact_uri="artifacts/models/feature-ledger-test/model.joblib",
            artifact_sha256="e" * 64,
            feature_version="features.kxbtc15m.v1",
            calibration_version="calibration.none.v1",
            dataset_id="dataset_kxbtc15m_feature_ledger_v1",
        )
    )
    return model.model_id


def collected_fixture_run(
    repository: OperationalStateRepository,
) -> tuple[str, str]:
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
    return summary.platform_run_id, summary.market_tickers[0]


def test_feature_row_is_deterministic_and_records_no_lookahead_metadata() -> None:
    repository, model_registry = dependencies_or_skip()
    run_id, market_ticker = collected_fixture_run(repository)
    model_id = register_feature_model(model_registry)
    builder = FeatureRowBuilder(repository.database_url)
    decision_timestamp = datetime(2026, 5, 31, 21, 13, tzinfo=UTC)

    first = builder.build(
        run_id=run_id,
        market_ticker=market_ticker,
        model_id=model_id,
        decision_timestamp=decision_timestamp,
        expected_feature_version="features.kxbtc15m.v1",
        expected_dataset_id="dataset_kxbtc15m_feature_ledger_v1",
    )
    second = builder.build(
        run_id=run_id,
        market_ticker=market_ticker,
        model_id=model_id,
        decision_timestamp=decision_timestamp,
    )

    assert first.inserted is True
    assert second.inserted is False
    assert second.feature_row_id == first.feature_row_id
    assert second.row_hash == first.row_hash
    assert first.max_source_event_timestamp <= first.decision_timestamp
    assert first.source_lag_ms == 60_000
    assert first.feature_version == "features.kxbtc15m.v1"
    assert first.calibration_version == "calibration.none.v1"
    assert first.dataset_id == "dataset_kxbtc15m_feature_ledger_v1"
    assert first.feature_values["best_yes_bid_dollars"] == 0.48
    assert first.feature_values["best_no_bid_dollars"] == 0.47
    assert len(first.source_event_ids) == 2


def test_feature_row_fails_fast_when_required_events_are_missing() -> None:
    repository, model_registry = dependencies_or_skip()
    tracer = repository.create_tracer_run(kxbtc15m_spec())
    model_id = register_feature_model(model_registry)

    with pytest.raises(MissingFeatureEventsError):
        FeatureRowBuilder(repository.database_url).build(
            run_id=tracer.run_id,
            market_ticker=tracer.market_ticker,
            model_id=model_id,
            decision_timestamp=datetime.now(UTC),
        )


def test_feature_row_rejects_source_events_after_decision_time() -> None:
    repository, model_registry = dependencies_or_skip()
    run_id, market_ticker = collected_fixture_run(repository)
    model_id = register_feature_model(model_registry)

    with pytest.raises(NoLookaheadViolationError):
        FeatureRowBuilder(repository.database_url).build(
            run_id=run_id,
            market_ticker=market_ticker,
            model_id=model_id,
            decision_timestamp=datetime(2026, 5, 31, 21, 11, 59, tzinfo=UTC),
        )


def test_feature_row_records_latest_replay_readable_events_and_checks_model_compatibility() -> None:
    repository, model_registry = dependencies_or_skip()
    run_id, market_ticker = collected_fixture_run(repository)
    model_id = register_feature_model(model_registry)
    event_log = RawEventLog(repository.database_url)
    event_log.append(
        run_id=run_id,
        market_ticker=market_ticker,
        source="kalshi_rest",
        source_event_id=f"{run_id}:{market_ticker}:older-market",
        received_at=datetime(2026, 5, 31, 21, 10, tzinfo=UTC),
        source_timestamp=datetime(2026, 5, 31, 21, 10, tzinfo=UTC),
        schema_version="kalshi.market_snapshot.v1",
        payload={"market": {"ticker": market_ticker, "yes_bid_dollars": "0.0100"}},
    )

    with pytest.raises(ModelFeatureCompatibilityError):
        FeatureRowBuilder(repository.database_url).build(
            run_id=run_id,
            market_ticker=market_ticker,
            model_id=model_id,
            decision_timestamp=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
            expected_feature_version="features.other.v1",
        )

    row = FeatureRowBuilder(repository.database_url).build(
        run_id=run_id,
        market_ticker=market_ticker,
        model_id=model_id,
        decision_timestamp=datetime(2026, 5, 31, 21, 13, tzinfo=UTC) + timedelta(seconds=1),
    )

    assert row.feature_values["yes_bid_dollars"] == 0.48
    assert row.metadata["required_schemas"] == [
        "kalshi.market_snapshot.v1",
        "kalshi.orderbook_snapshot.v1",
    ]
