from datetime import UTC, datetime

import psycopg
import pytest

from alphadb.collectors.coinbase import (
    COINBASE_FEATURE_SCHEMA,
    COINBASE_SOURCE,
    CoinbaseFeatureAdapter,
    CoinbaseFeatureError,
    FixtureCoinbaseClient,
    MissingCoinbaseDataError,
    StaleCoinbaseDataError,
    build_external_price_features,
)
from alphadb.config import settings_from_env
from alphadb.events.log import RawEventLog
from alphadb.markets.spec import kxbtc15m_spec
from alphadb.state.repository import OperationalStateRepository


def coinbase_repository_or_skip() -> OperationalStateRepository:
    repository = OperationalStateRepository(settings_from_env().database_url)
    try:
        with repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    repository.apply_migrations()
    return repository


def test_coinbase_market_structure_features_are_built_from_raw_candles() -> None:
    features = build_external_price_features(
        [
            {
                "timestamp": datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 2,
            },
            {
                "timestamp": datetime(2026, 5, 1, 0, 1, tzinfo=UTC),
                "open": 100,
                "high": 103,
                "low": 99,
                "close": 102,
                "volume": 3,
            },
            {
                "timestamp": datetime(2026, 5, 1, 0, 2, tzinfo=UTC),
                "open": 102,
                "high": 104,
                "low": 101,
                "close": 103,
                "volume": 4,
            },
        ]
    )

    assert features["coinbase_btc_momentum_1m"] > 0
    assert features["coinbase_btc_realized_range_pct"] > 0
    assert features["coinbase_btc_candle_shock_5m"] >= 0
    assert features["coinbase_btc_volume"] == 4


def test_coinbase_adapter_logs_feature_event_with_provenance_and_no_lookahead() -> None:
    repository = coinbase_repository_or_skip()
    tracer = repository.create_tracer_run(
        kxbtc15m_spec(),
        now=datetime(2026, 5, 31, 21, 0, tzinfo=UTC),
    )

    result = CoinbaseFeatureAdapter(
        database_url=repository.database_url,
        client=FixtureCoinbaseClient(),
    ).collect_feature_event(
        run_id=tracer.run_id,
        market_ticker=tracer.market_ticker,
        decision_timestamp=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
    )
    events = list(
        RawEventLog(repository.database_url).replay_events(
            run_id=tracer.run_id,
            market_ticker=tracer.market_ticker,
        )
    )

    assert result.max_source_event_timestamp <= result.decision_timestamp
    assert result.source_lag_ms == 60_000
    assert result.feature_values["external_close"] == 101.2
    assert events[-1]["source"] == COINBASE_SOURCE
    assert events[-1]["schema_version"] == COINBASE_FEATURE_SCHEMA
    assert events[-1]["payload"]["data_role"] == "feature_only"


def test_coinbase_adapter_rejects_missing_stale_and_malformed_data() -> None:
    repository = coinbase_repository_or_skip()
    tracer = repository.create_tracer_run(kxbtc15m_spec())
    adapter = CoinbaseFeatureAdapter(
        database_url=repository.database_url,
        client=FixtureCoinbaseClient(candles=[]),
    )

    with pytest.raises(MissingCoinbaseDataError):
        adapter.collect_feature_event(
            run_id=tracer.run_id,
            market_ticker=tracer.market_ticker,
            decision_timestamp=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
        )

    stale = CoinbaseFeatureAdapter(
        database_url=repository.database_url,
        client=FixtureCoinbaseClient(candles=[[1_780_260_000, 1, 2, 1, 2, 3]]),
        max_staleness_seconds=60,
    )
    with pytest.raises(StaleCoinbaseDataError):
        stale.collect_feature_event(
            run_id=tracer.run_id,
            market_ticker=tracer.market_ticker,
            decision_timestamp=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
        )

    malformed = CoinbaseFeatureAdapter(
        database_url=repository.database_url,
        client=FixtureCoinbaseClient(candles=[[1, 2, 3]]),
    )
    with pytest.raises(CoinbaseFeatureError):
        malformed.collect_feature_event(
            run_id=tracer.run_id,
            market_ticker=tracer.market_ticker,
            decision_timestamp=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
        )
