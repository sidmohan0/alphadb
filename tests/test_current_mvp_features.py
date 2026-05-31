import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from alphadb.artifacts import file_sha256, load_pinned_artifact_config, load_pinned_model_policy, register_loaded_model
from alphadb.collectors.coinbase import CoinbaseFeatureAdapter, FixtureCoinbaseClient
from alphadb.config import settings_from_env
from alphadb.events.log import RawEventLog
from alphadb.features.current_mvp import CurrentMvpFeatureRowBuilder, MissingCurrentMvpFeatureError
from alphadb.features.ledger import MissingFeatureEventsError, NoLookaheadViolationError
from alphadb.markets.spec import kxbtc15m_spec
from alphadb.state.repository import OperationalStateRepository


FEATURE_COLUMNS = [
    "decision_minute_offset",
    "time_since_open_seconds",
    "time_to_close_seconds",
    "price_close_dollars",
    "yes_bid_close_dollars",
    "yes_ask_close_dollars",
    "volume_fp",
    "open_interest_fp",
    "last_trade_yes_price_dollars",
    "last_trade_no_price_dollars",
    "last_trade_price_dollars",
    "last_trade_count_fp",
    "yes_bid",
    "yes_ask",
    "no_bid",
    "no_ask",
    "external_granularity_seconds",
    "external_open",
    "external_high",
    "external_low",
    "external_close",
    "external_volume",
    "external_return_1",
    "external_log_return_1",
    "external_close_to_open_return",
    "external_range_pct",
    "external_realized_vol_5",
    "external_realized_vol_15",
]


def db_or_skip() -> OperationalStateRepository:
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


def policy_fixture(tmp_path: Path, columns: list[str] | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    columns = columns or FEATURE_COLUMNS
    model = tmp_path / "model.json"
    schema = tmp_path / "feature_schema.json"
    report = tmp_path / "report.json"
    config = tmp_path / "artifacts.json"
    model.write_text(
        json.dumps({"type": "constant_probability", "probability_yes": 0.66, "feature_columns": columns}),
        encoding="utf-8",
    )
    schema.write_text(json.dumps({"feature_columns": columns}), encoding="utf-8")
    report.write_text(
        json.dumps({"selection": {"selection": {"candidate": "constant_probability", "decision_minute_offset": 12}}}),
        encoding="utf-8",
    )
    config.write_text(
        json.dumps(
            {
                "candidate": "constant_probability",
                "decision_minute_offset": 12,
                "mode": "conditional",
                "sizing": "fixed_dollars",
                "model_version": f"v-{uuid4().hex}",
                "artifacts": {
                    "model_path": model.name,
                    "model_sha256": file_sha256(model),
                    "feature_schema_path": schema.name,
                    "feature_schema_sha256": file_sha256(schema),
                    "model_selection_report_path": report.name,
                    "model_selection_report_sha256": file_sha256(report),
                },
            }
        ),
        encoding="utf-8",
    )
    return load_pinned_model_policy(
        load_pinned_artifact_config(artifact_root=tmp_path, config_path=config)
    )


def append_required_events(repository: OperationalStateRepository, run_id: str, market_ticker: str) -> None:
    log = RawEventLog(repository.database_url)
    decision = datetime(2026, 5, 31, 21, 13, tzinfo=UTC)
    common = {
        "run_id": run_id,
        "market_ticker": market_ticker,
        "source": "kalshi_rest",
        "received_at": decision,
    }
    market = {
        "ticker": market_ticker,
        "open_time": "2026-05-31T21:00:00Z",
        "close_time": "2026-05-31T21:15:00Z",
        "yes_bid_dollars": "0.48",
        "yes_ask_dollars": "0.52",
        "no_bid_dollars": "0.47",
        "no_ask_dollars": "0.53",
    }
    log.append(
        **common,
        source_event_id=f"{run_id}:market",
        source_timestamp=decision - timedelta(minutes=1),
        schema_version="kalshi.market_snapshot.v1",
        payload={"market": market},
    )
    log.append(
        **common,
        source_event_id=f"{run_id}:orderbook",
        source_timestamp=decision - timedelta(minutes=1),
        schema_version="kalshi.orderbook_snapshot.v1",
        payload={"orderbook": {"orderbook_fp": {"yes_dollars": [["0.48", "1"]], "no_dollars": [["0.47", "1"]]}}},
    )
    log.append(
        **common,
        source_event_id=f"{run_id}:candle",
        source_timestamp=decision - timedelta(seconds=30),
        schema_version="kalshi.candlestick_snapshot.v1",
        payload={
            "candlestick": {
                "price_close_dollars": 0.50,
                "yes_bid_close_dollars": 0.48,
                "yes_ask_close_dollars": 0.52,
                "volume_fp": 10,
                "open_interest_fp": 20,
            }
        },
    )
    log.append(
        **common,
        source_event_id=f"{run_id}:trade",
        source_timestamp=decision - timedelta(seconds=20),
        schema_version="kalshi.trade_snapshot.v1",
        payload={
            "trade": {
                "yes_price_dollars": 0.51,
                "no_price_dollars": 0.49,
                "price_dollars": 0.51,
                "count_fp": 2,
            }
        },
    )
    CoinbaseFeatureAdapter(
        database_url=repository.database_url,
        client=FixtureCoinbaseClient(),
    ).collect_feature_event(
        run_id=run_id,
        market_ticker=market_ticker,
        decision_timestamp=decision,
    )


def test_current_mvp_feature_builder_produces_model_ready_no_lookahead_row(tmp_path: Path) -> None:
    repository = db_or_skip()
    tracer = repository.create_tracer_run(kxbtc15m_spec(), now=datetime(2026, 5, 31, 21, 0, tzinfo=UTC))
    append_required_events(repository, tracer.run_id, tracer.market_ticker)
    policy = policy_fixture(tmp_path)
    model = register_loaded_model(database_url=repository.database_url, policy=policy)

    result = CurrentMvpFeatureRowBuilder(repository.database_url).build(
        run_id=tracer.run_id,
        market_ticker=tracer.market_ticker,
        model_id=model.model_id,
        policy=policy,
        decision_timestamp=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
    )

    assert result.feature_row.max_source_event_timestamp <= result.feature_row.decision_timestamp
    assert result.feature_row.feature_values["decision_minute_offset"] == 13
    assert result.feature_row.feature_values["yes_ask_dollars"] == 0.52
    assert len(result.model_ready_values) == len(FEATURE_COLUMNS)
    assert policy.predict_yes_probability(result.feature_row.feature_values) == 0.66


def test_current_mvp_feature_builder_fails_for_missing_schema_columns_and_source_events(
    tmp_path: Path,
) -> None:
    repository = db_or_skip()
    tracer = repository.create_tracer_run(kxbtc15m_spec())
    policy = policy_fixture(tmp_path, columns=["unknown_feature"])
    model = register_loaded_model(database_url=repository.database_url, policy=policy)

    with pytest.raises(MissingFeatureEventsError):
        CurrentMvpFeatureRowBuilder(repository.database_url).build(
            run_id=tracer.run_id,
            market_ticker=tracer.market_ticker,
            model_id=model.model_id,
            policy=policy,
            decision_timestamp=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
        )

    append_required_events(repository, tracer.run_id, tracer.market_ticker)
    with pytest.raises(MissingCurrentMvpFeatureError):
        CurrentMvpFeatureRowBuilder(repository.database_url).build(
            run_id=tracer.run_id,
            market_ticker=tracer.market_ticker,
            model_id=model.model_id,
            policy=policy,
            decision_timestamp=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
        )


def test_current_mvp_feature_builder_rejects_latest_required_event_after_decision(
    tmp_path: Path,
) -> None:
    repository = db_or_skip()
    tracer = repository.create_tracer_run(kxbtc15m_spec(), now=datetime(2026, 5, 31, 21, 0, tzinfo=UTC))
    append_required_events(repository, tracer.run_id, tracer.market_ticker)
    RawEventLog(repository.database_url).append(
        run_id=tracer.run_id,
        market_ticker=tracer.market_ticker,
        source="kalshi_rest",
        source_event_id=f"{tracer.run_id}:future-trade",
        received_at=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
        source_timestamp=datetime(2026, 5, 31, 21, 14, tzinfo=UTC),
        schema_version="kalshi.trade_snapshot.v1",
        payload={"trade": {"price_dollars": 0.99}},
    )
    policy = policy_fixture(tmp_path)
    model = register_loaded_model(database_url=repository.database_url, policy=policy)

    with pytest.raises(NoLookaheadViolationError):
        CurrentMvpFeatureRowBuilder(repository.database_url).build(
            run_id=tracer.run_id,
            market_ticker=tracer.market_ticker,
            model_id=model.model_id,
            policy=policy,
            decision_timestamp=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
        )
