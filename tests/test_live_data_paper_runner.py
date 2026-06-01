import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from alphadb.artifacts import file_sha256, load_pinned_artifact_config, load_pinned_model_policy, register_loaded_model
from alphadb.collectors.coinbase import FixtureCoinbaseClient
from alphadb.collectors.kalshi_rest import FixtureKalshiRestClient
from alphadb.config import settings_from_env
from alphadb.strategy.runner import LiveDataGatedLiveRunner, LiveDataPaperRunner
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


def runner_repository_or_skip() -> OperationalStateRepository:
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


def policy(tmp_path: Path, probability_yes: float, columns: list[str] | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    columns = columns or FEATURE_COLUMNS
    model = tmp_path / "model.json"
    schema = tmp_path / "feature_schema.json"
    report = tmp_path / "report.json"
    config = tmp_path / "artifacts.json"
    model.write_text(
        json.dumps(
            {
                "type": "constant_probability",
                "probability_yes": probability_yes,
                "feature_columns": columns,
            }
        ),
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
    return load_pinned_model_policy(load_pinned_artifact_config(artifact_root=tmp_path, config_path=config))


def make_runner(repository: OperationalStateRepository, tmp_path: Path, probability_yes: float, columns=None):
    loaded = policy(tmp_path, probability_yes, columns=columns)
    model = register_loaded_model(database_url=repository.database_url, policy=loaded)
    return LiveDataPaperRunner(
        database_url=repository.database_url,
        policy=loaded,
        model_id=model.model_id,
        kalshi_client=FixtureKalshiRestClient(),
    )


class FakeLiveOrderClient:
    def __init__(self, response: Mapping[str, Any] | None = None):
        self.response = response or {"order": {"status": "executed"}}
        self.requests: list[Mapping[str, Any]] = []

    def create_order(
        self,
        *,
        request_payload: Mapping[str, Any],
        settings,
    ) -> Mapping[str, Any]:
        self.requests.append(dict(request_payload))
        return self.response


def gated_live_settings(max_daily_loss_dollars: str = "1000"):
    current = settings_from_env()
    return settings_from_env(
        {
            "DATABASE_URL": current.database_url,
            "ALPHADB_RUNTIME_MODE": "gated-live",
            "ALPHADB_ENABLE_LIVE_ORDERS": "1",
            "ALPHADB_HUMAN_CUTOVER_APPROVED": "1",
            "KALSHI_API_KEY_ID": "key-id",
            "KALSHI_PRIVATE_KEY_PATH": "/tmp/private-key.pem",
            "ALPHADB_LIVE_STAKE_CAP_DOLLARS": "1.0",
            "ALPHADB_MAX_DAILY_LOSS_DOLLARS": max_daily_loss_dollars,
            "ALPHADB_MIN_EV_DOLLARS": "0.0",
        }
    )


def active_fixture_clients(now: datetime) -> tuple[FixtureKalshiRestClient, FixtureCoinbaseClient]:
    open_time = now - timedelta(minutes=12)
    close_time = now + timedelta(minutes=3)
    ticker = f"KXBTC15M-{uuid4().hex[:12]}"
    market = {
        "ticker": ticker,
        "series_ticker": "KXBTC15M",
        "event_ticker": f"KXBTC15M-{uuid4().hex[:8]}",
        "status": "open",
        "open_time": open_time.isoformat().replace("+00:00", "Z"),
        "close_time": close_time.isoformat().replace("+00:00", "Z"),
        "updated_time": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "title": "Bitcoin above prior 15 minute mark?",
        "yes_bid_dollars": "0.4800",
        "yes_ask_dollars": "0.5200",
        "no_bid_dollars": "0.4700",
        "no_ask_dollars": "0.5300",
    }
    orderbook = {
        "orderbook_fp": {
            "yes_dollars": [["0.4800", "14.00"]],
            "no_dollars": [["0.4700", "11.00"]],
        }
    }
    ts = int((now - timedelta(minutes=2)).timestamp())
    candles = [
        [ts - 120, 100.0, 101.0, 100.5, 100.8, 1.5],
        [ts - 60, 100.1, 101.2, 100.8, 101.0, 1.7],
        [ts, 100.4, 101.3, 101.0, 101.2, 1.4],
    ]
    return (
        FixtureKalshiRestClient(markets=[market], orderbooks={ticker: orderbook}),
        FixtureCoinbaseClient(candles=candles),
    )


def test_live_data_paper_runner_fills_positive_ev_trade_and_blocks_live_orders(
    tmp_path: Path,
) -> None:
    repository = runner_repository_or_skip()
    runner = make_runner(repository, tmp_path, 0.66)

    result = runner.run_one_cycle(now=datetime(2026, 5, 31, 21, 13, tzinfo=UTC))

    assert result.outcome is not None
    assert result.outcome.status == "handled"
    assert result.outcome.metadata["selected_side"] == "yes"
    assert result.outcome.metadata["risk_status"] == "approved"
    assert result.outcome.metadata["paper_status"] == "filled"
    assert result.outcome.metadata["live_orders_sent"] == 0
    assert result.counts["paper_filled"] >= 1


def test_live_data_paper_runner_records_ev_skip_risk_skip_missing_features_and_duplicates(
    tmp_path: Path,
) -> None:
    repository = runner_repository_or_skip()
    ev_runner = make_runner(repository, tmp_path / "ev", 0.51)
    risk_runner = make_runner(repository, tmp_path / "risk", 0.66)
    missing_runner = make_runner(repository, tmp_path / "missing", 0.66, columns=["unknown_feature"])

    ev_skip = ev_runner.run_one_cycle(now=datetime(2026, 5, 31, 21, 13, tzinfo=UTC))
    risk_skip = risk_runner.run_one_cycle(
        now=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
        daily_realized_pnl_dollars=-10.0,
    )
    missing = missing_runner.run_one_cycle(now=datetime(2026, 5, 31, 21, 13, tzinfo=UTC))
    duplicate = ev_runner.run_one_cycle(
        run_id=ev_skip.run_id,
        now=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
    )

    assert ev_skip.outcome is not None
    assert ev_skip.outcome.status == "skipped"
    assert ev_skip.outcome.reason == "ev_below_threshold"
    assert risk_skip.outcome is not None
    assert risk_skip.outcome.reason == "daily_loss_limit"
    assert missing.outcome is not None
    assert missing.outcome.status == "skipped"
    assert missing.outcome.reason == "missing_live_features"
    assert duplicate.counts["duplicate_prevented"] == 1


def test_gated_live_runner_submits_risk_approved_ioc_order_without_paper_fill(
    tmp_path: Path,
) -> None:
    repository = runner_repository_or_skip()
    loaded = policy(tmp_path, 0.66)
    model = register_loaded_model(database_url=repository.database_url, policy=loaded)
    fake_live = FakeLiveOrderClient()
    runner = LiveDataGatedLiveRunner(
        database_url=repository.database_url,
        policy=loaded,
        model_id=model.model_id,
        settings=gated_live_settings(),
        kalshi_client=FixtureKalshiRestClient(),
        live_order_client=fake_live,
    )

    result = runner.run_one_cycle(now=datetime(2026, 5, 31, 21, 13, tzinfo=UTC))

    assert result.outcome is not None
    assert result.outcome.status == "handled"
    assert result.outcome.metadata["runtime_mode"] == "gated-live"
    assert result.outcome.metadata["live_orders_sent"] == 1
    assert result.outcome.metadata["live_order_status"] == "submitted"
    assert result.outcome.paper_order_id is None
    assert fake_live.requests
    assert fake_live.requests[0]["time_in_force"] == "immediate_or_cancel"
    assert fake_live.requests[0]["post_only"] is False


def test_gated_live_loop_stops_on_live_order_rejection(tmp_path: Path) -> None:
    repository = runner_repository_or_skip()
    loaded = policy(tmp_path, 0.66)
    model = register_loaded_model(database_url=repository.database_url, policy=loaded)
    fake_live = FakeLiveOrderClient({"order": {"status": "rejected"}})
    now = datetime.now(UTC).replace(microsecond=0)
    kalshi_client, coinbase_client = active_fixture_clients(now)
    runner = LiveDataGatedLiveRunner(
        database_url=repository.database_url,
        policy=loaded,
        model_id=model.model_id,
        settings=gated_live_settings(),
        kalshi_client=kalshi_client,
        coinbase_client=coinbase_client,
        live_order_client=fake_live,
    )

    result = runner.run_loop(poll_seconds=0, max_markets=1, max_cycles=1)

    assert result.status == "stopped_on_error"
    assert result.latest_result is not None
    assert result.latest_result.outcome is not None
    assert result.latest_result.outcome.status == "error"
    assert result.latest_result.outcome.reason == "live_order_error"
