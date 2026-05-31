from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest

from alphadb.collectors.kalshi_rest import FixtureKalshiRestClient, RestKxbtc15mCollector
from alphadb.config import settings_from_env
from alphadb.model_registry.registry import ModelRegistration, ModelRegistryRepository
from alphadb.replay.report import ReplayReporter
from alphadb.state.repository import OperationalStateRepository


def replay_dependencies_or_skip() -> tuple[OperationalStateRepository, ModelRegistryRepository]:
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


def replay_fixture(repository: OperationalStateRepository, registry: ModelRegistryRepository):
    suffix = uuid4().hex[:12]
    market_ticker = f"KXBTC15M-26MAY312100-{suffix}"
    model = registry.register(
        ModelRegistration(
            series="KXBTC15M",
            model_name="replay-report-test",
            model_version=f"v-{uuid4().hex}",
            artifact_uri="artifacts/models/replay-report-test/model.joblib",
            artifact_sha256="2" * 64,
            feature_version="features.kxbtc15m.v1",
            calibration_version="calibration.none.v1",
            dataset_id="dataset_replay_report_v1",
        )
    )
    summary = RestKxbtc15mCollector(
        database_url=repository.database_url,
        client=FixtureKalshiRestClient(
            markets=[
                {
                    "ticker": market_ticker,
                    "series_ticker": "KXBTC15M",
                    "event_ticker": f"KXBTC15M-{suffix}",
                    "status": "open",
                    "open_time": "2026-05-31T21:00:00Z",
                    "close_time": "2026-05-31T21:15:00Z",
                    "updated_time": "2026-05-31T21:12:00Z",
                    "title": "Bitcoin above prior 15 minute mark?",
                    "yes_bid_dollars": "0.4800",
                    "yes_ask_dollars": "0.5200",
                    "no_bid_dollars": "0.4700",
                    "no_ask_dollars": "0.5300",
                }
            ],
            orderbooks={
                market_ticker: {
                    "orderbook_fp": {
                        "yes_dollars": [["0.4800", "14.00"]],
                        "no_dollars": [["0.4700", "11.00"]],
                    }
                }
            },
        ),
        source_mode="fixture",
    ).collect(
        series="KXBTC15M",
        max_markets=1,
        now=datetime(2026, 5, 31, 21, 12, tzinfo=UTC),
    )
    return model.model_id, summary.platform_run_id, summary.market_tickers[0]


def test_replay_report_is_deterministic_and_traces_sources_to_outputs() -> None:
    repository, registry = replay_dependencies_or_skip()
    model_id, run_id, market_ticker = replay_fixture(repository, registry)
    reporter = ReplayReporter(repository.database_url)
    kwargs = {
        "run_id": run_id,
        "market_ticker": market_ticker,
        "model_id": model_id,
        "decision_timestamp": datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
        "probability_yes": 0.65,
        "realized_pnl_dollars": 0.0,
        "liquidity_price_dollars": 0.52,
        "liquidity_quantity": 1,
        "mark_price_dollars": 0.55,
    }

    first = reporter.run(**kwargs)
    second = reporter.run(**kwargs)

    assert second.as_dict() == first.as_dict()
    assert first.raw_event_ids == tuple(sorted(first.raw_event_ids))
    assert len(first.raw_event_ids) == 2
    assert set(first.source_event_ids).issubset(set(first.raw_event_ids))
    assert first.model_artifact_uri == "artifacts/models/replay-report-test/model.joblib"
    assert first.model_artifact_sha256 == "2" * 64
    assert first.selected_side == "yes"
    assert first.risk_status == "approved"
    assert first.paper_status == "filled"
    assert first.filled_quantity == 1
    assert first.unrealized_pnl_dollars == pytest.approx(0.03)
    assert len(first.report_hash) == 64
