import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from alphadb.artifacts import file_sha256, load_pinned_artifact_config, load_pinned_model_policy, register_loaded_model
from alphadb.collectors.kalshi_rest import FixtureKalshiRestClient
from alphadb.config import settings_from_env
from alphadb.strategy.runner import LiveDataPaperRunner
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
