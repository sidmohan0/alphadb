from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from alphadb.collectors.coinbase import FixtureCoinbaseClient
from alphadb.collectors.kalshi_rest import FixtureKalshiRestClient
from alphadb.model_evaluation.fair_value_live import (
    FAIR_VALUE_DECISION_ROWS_SCHEMA,
    FairValueDecisionRowCollector,
    FairValueDecisionRowCollectorConfig,
)
from alphadb.model_evaluation import cli as model_eval_cli
from alphadb.model_evaluation import fair_value_live_job
from alphadb.model_evaluation.fair_value_live_job import (
    FAIR_VALUE_LIVE_JOB_SCHEMA,
    FairValueLiveTradingJob,
    FairValueLiveTradingJobConfig,
)
from alphadb.model_evaluation.fair_value_model import (
    FAIR_VALUE_MODEL_REPORT_SCHEMA,
    ThresholdVolatilityFairValueConfig,
    build_threshold_volatility_fair_value_report,
    build_threshold_volatility_fair_value_rows,
)
from alphadb.model_evaluation.fair_value_replay import (
    FairValueReplayConfig,
    build_fair_value_replay_report,
    build_fair_value_walk_forward_report,
)
from alphadb.config import settings_from_env
from alphadb.live_runtime import (
    DEFAULT_FAIR_VALUE_LIVE_CONFIG,
    LiveRunStatusRepository,
    LiveRuntimeConfig,
    LiveRuntimeConfigRepository,
    build_fair_value_live_status,
)
from alphadb.state.repository import OperationalStateRepository


def test_threshold_volatility_model_scores_intuitive_probability_ordering() -> None:
    base = {
        "ticker": "KXBTC15M-FV-MODEL",
        "decision_timestamp": "2026-06-04T15:00:00Z",
        "close_time": "2026-06-04T15:03:00Z",
        "external_realized_vol_5": 0.002,
        "external_log_return_1": 0.0,
        "payout_threshold": 100.0,
    }

    below, above, volatile_above = build_threshold_volatility_fair_value_rows(
        [
            {**base, "external_close": 99.0},
            {**base, "external_close": 101.0},
            {**base, "external_close": 101.0, "external_realized_vol_5": 0.03},
        ]
    )

    assert below["fair_value_status"] == "complete"
    assert above["p_yes"] > below["p_yes"]
    assert above["p_yes"] > 0.5
    assert volatile_above["p_yes"] < above["p_yes"]


def test_threshold_volatility_model_report_records_missing_inputs_as_skips() -> None:
    report = build_threshold_volatility_fair_value_report(
        [
            {
                "ticker": "KXBTC15M-FV-MISSING",
                "external_close": 101.0,
                "time_to_close_seconds": 60,
            }
        ],
        config=ThresholdVolatilityFairValueConfig(),
    )

    assert report["schema_version"] == FAIR_VALUE_MODEL_REPORT_SCHEMA
    assert report["counts"] == {"completed": 0, "skipped": 1}
    assert report["skips"] == [{"reason": "missing_payout_threshold", "count": 1}]


def test_fair_value_replay_distinguishes_orders_fills_and_unsettled_exposure() -> None:
    rows = [
        {
            "ticker": "KXBTC15M-FV-FILLED",
            "decision_timestamp": "2026-06-04T15:00:00Z",
            "p_yes": 0.9,
            "yes_ask": 0.20,
            "no_ask": 0.80,
            "result": "yes",
        },
        {
            "ticker": "KXBTC15M-FV-UNFILLED",
            "decision_timestamp": "2026-06-04T15:01:00Z",
            "p_yes": 0.9,
            "yes_ask": 0.20,
            "no_ask": 0.80,
            "fill_status": "unfilled",
            "result": "yes",
        },
        {
            "ticker": "KXBTC15M-FV-UNSETTLED",
            "decision_timestamp": "2026-06-04T15:02:00Z",
            "p_yes": 0.9,
            "yes_ask": 0.20,
            "no_ask": 0.80,
            "filled_contracts": 2,
        },
    ]

    report = build_fair_value_replay_report(
        rows,
        config=FairValueReplayConfig(min_edge=0.05, max_order_dollars=5, max_loss_dollars=50),
    )

    assert report["counts"]["orders"] == 3
    assert report["counts"]["trades"] == 2
    assert report["counts"]["unfilled_orders"] == 1
    assert report["settlement"]["status"] == "partial"
    assert report["settlement"]["missing_or_delayed_rows"] == 1
    assert report["pnl"]["unsettled_exposure_dollars"] > 0
    assert report["orders"][1]["fill_status"] == "unfilled"


def test_fair_value_replay_covers_missing_quote_edge_and_order_cap() -> None:
    report = build_fair_value_replay_report(
        [
            {
                "ticker": "KXBTC15M-FV-MISSING-QUOTE",
                "decision_timestamp": "2026-06-04T15:00:00Z",
                "p_yes": 0.9,
                "yes_ask": 0.20,
            },
            {
                "ticker": "KXBTC15M-FV-BELOW-EDGE",
                "decision_timestamp": "2026-06-04T15:01:00Z",
                "p_yes": 0.51,
                "yes_ask": 0.50,
                "no_ask": 0.50,
                "result": "yes",
            },
            {
                "ticker": "KXBTC15M-FV-ORDER-CAP",
                "decision_timestamp": "2026-06-04T15:02:00Z",
                "p_yes": 0.95,
                "yes_ask": 0.20,
                "no_ask": 0.80,
                "result": "yes",
            },
        ],
        config=FairValueReplayConfig(min_edge=0.05, max_order_dollars=1.0, max_loss_dollars=50),
    )

    skip_reasons = {reason for reason, _count in report["skips"]}
    assert "missing_executable_price" in skip_reasons
    assert "edge_below_min" in skip_reasons
    assert report["counts"]["orders"] == 1
    assert report["orders"][0]["cost_dollars"] <= 1.0


def test_fair_value_walk_forward_reports_insufficient_data_as_zero_windows() -> None:
    report = build_fair_value_walk_forward_report(
        [
            {
                "ticker": "KXBTC15M-FV-ONLY-ONE",
                "decision_timestamp": "2026-06-04T15:00:00Z",
                "p_yes": 0.9,
                "yes_ask": 0.20,
                "no_ask": 0.80,
                "result": "yes",
            }
        ],
        selection_market_count=2,
        holdout_market_count=1,
        min_edge_values=(0.0, 0.05),
    )

    assert report["market_count"] == 1
    assert report["complete_window_count"] == 0
    assert report["aggregate"]["holdout_trade_count"] == 0
    assert report["windows"] == []


def test_live_fair_value_collector_outputs_decision_rows_without_orders() -> None:
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    ticker = "KXBTC15M-FV-LIVE"
    kalshi = FixtureKalshiRestClient(
        markets=[
            {
                "ticker": ticker,
                "series_ticker": "KXBTC15M",
                "event_ticker": "KXBTC15M-FV",
                "status": "open",
                "open_time": (now - timedelta(minutes=10)).isoformat(),
                "close_time": (now + timedelta(minutes=5)).isoformat(),
                "updated_time": (now - timedelta(seconds=1)).isoformat(),
                "title": "Bitcoin above $100?",
                "payout_threshold": "100.00",
                "yes_ask_dollars": "0.40",
                "no_ask_dollars": "0.60",
            }
        ],
        orderbooks={
            ticker: {
                "orderbook_fp": {
                    "yes_dollars": [["0.39", "10"]],
                    "no_dollars": [["0.59", "10"]],
                }
            }
        },
    )
    coinbase = FixtureCoinbaseClient(candles=fixture_candles(now))

    result = FairValueDecisionRowCollector(
        kalshi_client=kalshi,
        coinbase_client=coinbase,
        config=FairValueDecisionRowCollectorConfig(max_markets=1),
    ).collect(now=now)
    payload = result.as_dict()

    assert payload["schema_version"] == FAIR_VALUE_DECISION_ROWS_SCHEMA
    assert payload["counts"]["decisions"] == 1
    assert payload["counts"]["orders_placed"] == 0
    row = payload["rows"][0]
    assert row["row_type"] == "decision"
    assert row["p_yes"] > 0.5
    assert row["no_lookahead_source_check"] is True
    assert row["yes_ask"] == 0.40


def test_live_fair_value_collector_records_skip_reasons() -> None:
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    ticker = "KXBTC15M-FV-SKIP"
    kalshi = FixtureKalshiRestClient(
        markets=[
            {
                "ticker": ticker,
                "series_ticker": "KXBTC15M",
                "status": "open",
                "open_time": (now - timedelta(minutes=10)).isoformat(),
                "close_time": (now + timedelta(minutes=5)).isoformat(),
                "updated_time": (now - timedelta(seconds=1)).isoformat(),
                "title": "Bitcoin above unknown threshold?",
                "yes_ask_dollars": "0.40",
                "no_ask_dollars": "0.60",
            }
        ],
        orderbooks={ticker: {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}},
    )

    payload = (
        FairValueDecisionRowCollector(
            kalshi_client=kalshi,
            coinbase_client=FixtureCoinbaseClient(candles=fixture_candles(now)),
            config=FairValueDecisionRowCollectorConfig(max_markets=1),
        )
        .collect(now=now)
        .as_dict()
    )

    assert payload["counts"]["skips"] == 1
    assert payload["skip_reasons"] == [{"reason": "unsupported_market_shape", "count": 1}]
    assert payload["orders_placed"] == 0


def test_live_trading_job_submits_capped_order_and_reports_settled_pnl(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeOrderClient:
        requests: list[dict]

        def __init__(self) -> None:
            self.requests = []

        def create_order(self, *, request_payload, settings):
            self.requests.append(dict(request_payload))
            return {
                "order_id": "ord_live_1",
                "client_order_id": request_payload["client_order_id"],
                "fill_count": "2.00",
                "remaining_count": "0.00",
            }

        def get_order(self, *, order_id, settings):
            return {
                "order": {
                    "order_id": order_id,
                    "fill_count_fp": "2.00",
                    "taker_fill_cost_dollars": "0.8000",
                    "taker_fees_dollars": "0.0200",
                }
            }

    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    settings = settings_from_env(
        {
            "ALPHADB_RUNTIME_MODE": "gated-live",
            "ALPHADB_ENABLE_LIVE_ORDERS": "1",
            "ALPHADB_HUMAN_CUTOVER_APPROVED": "1",
            "KALSHI_API_KEY_ID": "key-id",
            "KALSHI_PRIVATE_KEY_PATH": "/tmp/fake-key.pem",
        }
    )
    monkeypatch.setattr(
        fair_value_live_job,
        "public_market_result",
        lambda *, settings, ticker: {"status": "finalized", "result": "yes"},
    )
    client = FakeOrderClient()

    manifest = FairValueLiveTradingJob(
        config=FairValueLiveTradingJobConfig(
            output_root=tmp_path,
            source="fixture",
            coinbase_source="fixture",
            max_markets=1,
            max_order_dollars=5.0,
            max_daily_loss_dollars=50.0,
            submit_live_orders=True,
        ),
        settings=settings,
        order_client=client,
    ).run(now=now)

    assert manifest["schema_version"] == FAIR_VALUE_LIVE_JOB_SCHEMA
    assert manifest["runtime_controls"]["report_only"] is False
    assert manifest["runtime_controls"]["live_orders_enabled"] is True
    assert manifest["runtime_controls"]["orders_placed"] == 1
    assert client.requests[0]["time_in_force"] == "immediate_or_cancel"
    assert float(client.requests[0]["count"]) >= 1
    reconciliation = json.loads(
        Path(manifest["artifacts"]["live_reconciliation_report"]["path"]).read_text()
    )
    assert reconciliation["settlement"]["status"] == "reconciled"
    assert reconciliation["pnl"]["net_pnl_dollars"] == 1.18


def test_live_trading_cli_uses_env_caps_when_flags_are_omitted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ALPHADB_LIVE_STAKE_CAP_DOLLARS", "2.25")
    monkeypatch.setenv("ALPHADB_MAX_TICKER_EXPOSURE_DOLLARS", "3.5")
    monkeypatch.setenv("ALPHADB_MAX_DAILY_LOSS_DOLLARS", "12.0")
    output = tmp_path / "manifest.json"

    exit_code = model_eval_cli.main(
        [
            "fair-value-live-trading-job",
            "--output-root",
            str(tmp_path / "artifacts"),
            "--source",
            "fixture",
            "--coinbase-source",
            "fixture",
            "--max-markets",
            "1",
            "--output",
            str(output),
        ]
    )

    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert manifest["config"]["max_order_dollars"] == 2.25
    assert manifest["config"]["max_ticker_exposure_dollars"] == 3.5
    assert manifest["config"]["max_daily_loss_dollars"] == 12.0


def test_live_trading_job_retries_same_market_after_no_fill(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    ticker = "KXBTC15M-FV-NOFILL"
    install_live_job_fixture(monkeypatch, now=now, ticker=ticker)
    monkeypatch.setattr(
        fair_value_live_job,
        "public_market_result",
        lambda *, settings, ticker: {"status": "active", "result": None},
    )
    client = SequencedOrderClient(
        [
            {"fill_count": 0, "cost": 0.0, "fees": 0.0},
            {"fill_count": 2, "cost": 0.8, "fees": 0.02},
        ]
    )
    settings = live_enabled_settings()
    config = FairValueLiveTradingJobConfig(
        output_root=tmp_path,
        source="kalshi-public",
        coinbase_source="coinbase-live",
        max_markets=1,
        max_order_dollars=5.0,
        max_ticker_exposure_dollars=5.0,
        max_daily_loss_dollars=50.0,
        submit_live_orders=True,
    )

    first = FairValueLiveTradingJob(
        config=config,
        settings=settings,
        order_client=client,
    ).run(now=now)
    second = FairValueLiveTradingJob(
        config=config,
        settings=settings,
        order_client=client,
    ).run(now=now + timedelta(minutes=1))

    assert len(client.requests) == 2
    first_reconciliation = json.loads(
        Path(first["artifacts"]["live_reconciliation_report"]["path"]).read_text()
    )
    second_reconciliation = json.loads(
        Path(second["artifacts"]["live_reconciliation_report"]["path"]).read_text()
    )
    assert first_reconciliation["counts"]["no_fill"] == 1
    assert second_reconciliation["counts"]["filled"] == 1
    assert second_reconciliation["per_market_exposure"]["markets"][0]["exposure_dollars"] == 0.82


def test_live_trading_job_records_replay_skip_as_live_attempt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    ticker = "KXBTC15M-FV-EDGE-SKIP"
    install_live_job_fixture(monkeypatch, now=now, ticker=ticker)
    monkeypatch.setattr(
        fair_value_live_job,
        "public_market_result",
        lambda *, settings, ticker: {"status": "active", "result": None},
    )
    client = SequencedOrderClient([])

    manifest = FairValueLiveTradingJob(
        config=FairValueLiveTradingJobConfig(
            output_root=tmp_path,
            source="kalshi-public",
            coinbase_source="coinbase-live",
            max_markets=1,
            min_edge=1.0,
            max_order_dollars=5.0,
            max_ticker_exposure_dollars=5.0,
            max_daily_loss_dollars=50.0,
            submit_live_orders=True,
        ),
        settings=live_enabled_settings(),
        order_client=client,
    ).run(now=now)

    attempts = json.loads(Path(manifest["artifacts"]["live_order_attempts"]["path"]).read_text())
    assert client.requests == []
    assert manifest["counts"]["live_attempts"] == 1
    assert manifest["counts"]["live_skipped"] == 1
    assert attempts["attempts"][0]["market_ticker"] == ticker
    assert attempts["attempts"][0]["status"] == "skipped"
    assert attempts["attempts"][0]["reason"] == "edge_below_min"
    assert attempts["skip_reasons"] == [{"reason": "edge_below_min", "count": 1}]


def test_live_trading_job_blocks_duplicate_fill_after_ticker_cap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    ticker = "KXBTC15M-FV-TICKER-CAP"
    install_live_job_fixture(monkeypatch, now=now, ticker=ticker)
    monkeypatch.setattr(
        fair_value_live_job,
        "public_market_result",
        lambda *, settings, ticker: {"status": "active", "result": None},
    )
    client = SequencedOrderClient(
        [
            {"fill_count": 2, "cost": 4.8, "fees": 0.1},
            {"fill_count": 2, "cost": 0.8, "fees": 0.02},
        ]
    )
    settings = live_enabled_settings()
    config = FairValueLiveTradingJobConfig(
        output_root=tmp_path,
        source="kalshi-public",
        coinbase_source="coinbase-live",
        max_markets=1,
        max_order_dollars=5.0,
        max_ticker_exposure_dollars=5.0,
        max_daily_loss_dollars=50.0,
        submit_live_orders=True,
    )

    FairValueLiveTradingJob(config=config, settings=settings, order_client=client).run(now=now)
    second = FairValueLiveTradingJob(
        config=config,
        settings=settings,
        order_client=client,
    ).run(now=now + timedelta(minutes=1))

    assert len(client.requests) == 1
    attempts = json.loads(Path(second["artifacts"]["live_order_attempts"]["path"]).read_text())
    assert attempts["attempts"][0]["status"] == "skipped"
    assert attempts["attempts"][0]["reason"] == "market_exposure_cap_reached"
    assert attempts["skip_reasons"] == [{"reason": "market_exposure_cap_reached", "count": 1}]


def test_live_trading_job_skips_order_when_live_run_lock_is_held(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    ticker = "KXBTC15M-FV-LOCK-HELD"
    install_live_job_fixture(monkeypatch, now=now, ticker=ticker)
    monkeypatch.setattr(
        fair_value_live_job,
        "public_market_result",
        lambda *, settings, ticker: {"status": "active", "result": None},
    )
    monkeypatch.setattr(
        fair_value_live_job,
        "acquire_live_run_lock",
        lambda **kwargs: fair_value_live_job.LiveRunLock(
            backend="test",
            acquired=False,
            token="existing-lock",
            reason="live_run_lock_held",
            existing={"run_id": "fv_live_existing"},
        ),
    )
    client = SequencedOrderClient([{"fill_count": 2, "cost": 0.8, "fees": 0.02}])

    manifest = FairValueLiveTradingJob(
        config=FairValueLiveTradingJobConfig(
            output_root=tmp_path,
            source="kalshi-public",
            coinbase_source="coinbase-live",
            max_markets=1,
            max_order_dollars=5.0,
            max_ticker_exposure_dollars=5.0,
            max_daily_loss_dollars=50.0,
            submit_live_orders=True,
        ),
        settings=live_enabled_settings(),
        order_client=client,
    ).run(now=now)

    assert client.requests == []
    assert manifest["runtime_controls"]["orders_placed"] == 0
    assert manifest["runtime_controls"]["live_run_lock"]["acquired"] is False
    attempts = json.loads(Path(manifest["artifacts"]["live_order_attempts"]["path"]).read_text())
    assert attempts["attempts"][0]["status"] == "skipped"
    assert attempts["attempts"][0]["reason"] == "live_run_lock_held"
    assert attempts["skip_reasons"] == [{"reason": "live_run_lock_held", "count": 1}]


def test_lock_held_duplicate_does_not_replace_latest_dashboard_status(
    tmp_path: Path,
    monkeypatch,
    request,
) -> None:
    live_runtime_repository_or_skip()
    settings = live_enabled_settings()
    status_repository = LiveRunStatusRepository(settings.database_url)
    delete_lock_duplicate_test_statuses(settings.database_url)
    request.addfinalizer(lambda: delete_lock_duplicate_test_statuses(settings.database_url))
    prior_run_id = f"fv_live_prior_{uuid4().hex[:8]}"
    prior_status = build_fair_value_live_status(
        manifest={
            "run_id": prior_run_id,
            "generated_at": "2099-06-04T15:00:00+00:00",
            "runtime_config": {"config_id": "cfg_existing", "version": 1, "snapshot": {}},
            "runtime_controls": {"live_orders_enabled": True, "orders_placed": 1},
            "counts": {"live_attempts": 1, "replay_trades": 1},
        },
        attempts_payload={
            "attempts": [
                {
                    "attempt_id": f"attempt_{prior_run_id}",
                    "submitted_at": "2099-06-04T15:00:00+00:00",
                    "market_ticker": "KXBTC15M-FV-PRIOR",
                    "side": "yes",
                    "status": "submitted",
                    "reason": "submitted",
                }
            ]
        },
        reconciliation={
            "rows": [
                {
                    "attempt_id": f"attempt_{prior_run_id}",
                    "market_ticker": "KXBTC15M-FV-PRIOR",
                    "filled_contracts": 0,
                    "settlement_status": "no_fill",
                }
            ],
            "per_market_exposure": {"markets": []},
        },
    )
    status_repository.persist(prior_status)

    now = datetime(2099, 6, 4, 15, 1, tzinfo=UTC)
    ticker = "KXBTC15M-FV-DUPLICATE-LOCK"
    install_live_job_fixture(monkeypatch, now=now, ticker=ticker)
    monkeypatch.setattr(
        fair_value_live_job,
        "public_market_result",
        lambda *, settings, ticker: {"status": "active", "result": None},
    )
    monkeypatch.setattr(
        fair_value_live_job,
        "acquire_live_run_lock",
        lambda **kwargs: fair_value_live_job.LiveRunLock(
            backend="test",
            acquired=False,
            token="existing-lock",
            reason="live_run_lock_held",
            existing={"run_id": prior_run_id},
        ),
    )
    client = SequencedOrderClient([{"fill_count": 2, "cost": 0.8, "fees": 0.02}])

    FairValueLiveTradingJob(
        config=FairValueLiveTradingJobConfig(
            output_root=tmp_path,
            source="kalshi-public",
            coinbase_source="coinbase-live",
            max_markets=1,
            max_order_dollars=5.0,
            max_ticker_exposure_dollars=5.0,
            max_daily_loss_dollars=50.0,
            submit_live_orders=True,
        ),
        settings=settings,
        order_client=client,
    ).run(now=now)

    latest = status_repository.latest_status()
    assert client.requests == []
    assert latest.run_id == prior_run_id
    assert latest.latest_attempt_reason == "submitted"
    assert latest.fill_status == "no_fill"


def test_live_trading_job_preserves_daily_cap_from_prior_exposure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    current_ticker = "KXBTC15M-FV-DAILY-CURRENT"
    prior_ticker = "KXBTC15M-FV-DAILY-PRIOR"
    install_live_job_fixture(monkeypatch, now=now, ticker=current_ticker)
    monkeypatch.setattr(
        fair_value_live_job,
        "public_market_result",
        lambda *, settings, ticker: {"status": "active", "result": None},
    )
    write_prior_attempt(
        tmp_path,
        run_id="fv_live_20260604T145900Z",
        order_id="prior_daily_order",
        ticker=prior_ticker,
        side="yes",
        fill_count=1,
    )
    client = SequencedOrderClient(
        [],
        order_details={
            "prior_daily_order": {"fill_count": 1, "cost": 49.0, "fees": 0.5},
        },
    )

    manifest = FairValueLiveTradingJob(
        config=FairValueLiveTradingJobConfig(
            output_root=tmp_path,
            source="kalshi-public",
            coinbase_source="coinbase-live",
            max_markets=1,
            max_order_dollars=5.0,
            max_ticker_exposure_dollars=5.0,
            max_daily_loss_dollars=50.0,
            submit_live_orders=True,
        ),
        settings=live_enabled_settings(),
        order_client=client,
    ).run(now=now)

    assert client.requests == []
    attempts = json.loads(Path(manifest["artifacts"]["live_order_attempts"]["path"]).read_text())
    admission_accounting = attempts["admission_daily_loss_accounting"]
    assert admission_accounting["timezone"] == "America/Los_Angeles"
    assert admission_accounting["live_risk_day"] == "2026-06-04"
    assert admission_accounting["same_live_risk_day_rows"] == 1
    assert admission_accounting["same_live_risk_day_filled_rows"] == 1
    assert admission_accounting["daily_loss_used_dollars"] == 49.5
    assert attempts["attempts"][0]["status"] == "skipped"
    assert attempts["attempts"][0]["reason"] == "daily_loss_cap_reached"
    assert attempts["attempts"][0]["daily_loss_used_before_dollars"] == 49.5
    assert attempts["attempts"][0]["daily_loss_accounting"] == admission_accounting


def test_live_trading_job_does_not_reset_daily_cap_at_utc_midnight(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = datetime(2026, 6, 5, 0, 0, 10, tzinfo=UTC)
    current_ticker = "KXBTC15M-FV-UTC-MIDNIGHT-CURRENT"
    prior_ticker = "KXBTC15M-FV-UTC-MIDNIGHT-PRIOR"
    install_live_job_fixture(monkeypatch, now=now, ticker=current_ticker)
    monkeypatch.setattr(
        fair_value_live_job,
        "public_market_result",
        lambda *, settings, ticker: {"status": "active", "result": None},
    )
    write_prior_attempt(
        tmp_path,
        run_id="fv_live_20260604T235900Z",
        order_id="prior_utc_midnight_order",
        ticker=prior_ticker,
        side="yes",
        fill_count=1,
        submitted_at="2026-06-04T23:59:00+00:00",
    )
    client = SequencedOrderClient(
        [],
        order_details={
            "prior_utc_midnight_order": {"fill_count": 1, "cost": 49.0, "fees": 0.5},
        },
    )

    manifest = FairValueLiveTradingJob(
        config=FairValueLiveTradingJobConfig(
            output_root=tmp_path,
            source="kalshi-public",
            coinbase_source="coinbase-live",
            max_markets=1,
            max_order_dollars=5.0,
            max_ticker_exposure_dollars=5.0,
            max_daily_loss_dollars=50.0,
            submit_live_orders=True,
        ),
        settings=live_enabled_settings(),
        order_client=client,
    ).run(now=now)

    assert client.requests == []
    attempts = json.loads(Path(manifest["artifacts"]["live_order_attempts"]["path"]).read_text())
    admission_accounting = attempts["admission_daily_loss_accounting"]
    assert admission_accounting["live_risk_day"] == "2026-06-04"
    assert admission_accounting["window_start_utc"] == "2026-06-04T07:00:00+00:00"
    assert admission_accounting["window_end_utc"] == "2026-06-05T07:00:00+00:00"
    assert admission_accounting["daily_loss_used_dollars"] == 49.5
    assert attempts["attempts"][0]["status"] == "skipped"
    assert attempts["attempts"][0]["reason"] == "daily_loss_cap_reached"


def test_live_trading_job_resets_daily_cap_at_live_risk_day_boundary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = datetime(2026, 6, 5, 7, 0, 10, tzinfo=UTC)
    current_ticker = "KXBTC15M-FV-LA-RESET-CURRENT"
    prior_ticker = "KXBTC15M-FV-LA-RESET-PRIOR"
    install_live_job_fixture(monkeypatch, now=now, ticker=current_ticker)
    monkeypatch.setattr(
        fair_value_live_job,
        "public_market_result",
        lambda *, settings, ticker: {"status": "active", "result": None},
    )
    write_prior_attempt(
        tmp_path,
        run_id="fv_live_20260605T065900Z",
        order_id="prior_la_midnight_order",
        ticker=prior_ticker,
        side="yes",
        fill_count=1,
        submitted_at="2026-06-05T06:59:00+00:00",
    )
    client = SequencedOrderClient(
        [{"fill_count": 1, "cost": 0.4, "fees": 0.01}],
        order_details={
            "prior_la_midnight_order": {"fill_count": 1, "cost": 49.0, "fees": 0.5},
        },
    )

    manifest = FairValueLiveTradingJob(
        config=FairValueLiveTradingJobConfig(
            output_root=tmp_path,
            source="kalshi-public",
            coinbase_source="coinbase-live",
            max_markets=1,
            max_order_dollars=5.0,
            max_ticker_exposure_dollars=5.0,
            max_daily_loss_dollars=50.0,
            submit_live_orders=True,
        ),
        settings=live_enabled_settings(),
        order_client=client,
    ).run(now=now)

    assert len(client.requests) == 1
    attempts = json.loads(Path(manifest["artifacts"]["live_order_attempts"]["path"]).read_text())
    admission_accounting = attempts["admission_daily_loss_accounting"]
    post_run_accounting = manifest["runtime_controls"]["daily_loss_accounting"]
    assert admission_accounting["live_risk_day"] == "2026-06-05"
    assert admission_accounting["window_start_utc"] == "2026-06-05T07:00:00+00:00"
    assert admission_accounting["same_live_risk_day_rows"] == 0
    assert admission_accounting["daily_loss_used_dollars"] == 0.0
    assert post_run_accounting["same_live_risk_day_filled_rows"] == 1
    assert post_run_accounting["daily_loss_used_dollars"] == 0.41
    assert attempts["attempts"][0]["status"] == "submitted"
    assert attempts["attempts"][0]["daily_loss_used_before_dollars"] == 0.0


def test_live_trading_job_daily_cap_counts_settled_loss_and_unsettled_exposure_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = datetime(2026, 6, 5, 16, 0, tzinfo=UTC)
    current_ticker = "KXBTC15M-FV-DAILY-COUNT-CURRENT"
    settled_ticker = "KXBTC15M-FV-DAILY-COUNT-SETTLED"
    unsettled_ticker = "KXBTC15M-FV-DAILY-COUNT-UNSETTLED"
    no_fill_ticker = "KXBTC15M-FV-DAILY-COUNT-NOFILL"
    install_live_job_fixture(monkeypatch, now=now, ticker=current_ticker)

    def market_result(*, settings, ticker):
        if ticker == settled_ticker:
            return {"status": "finalized", "result": "no"}
        return {"status": "active", "result": None}

    monkeypatch.setattr(fair_value_live_job, "public_market_result", market_result)
    write_prior_attempt(
        tmp_path,
        run_id="fv_live_20260605T155500Z",
        order_id="prior_settled_loss_order",
        ticker=settled_ticker,
        side="yes",
        fill_count=1,
        submitted_at="2026-06-05T15:55:00+00:00",
    )
    write_prior_attempt(
        tmp_path,
        run_id="fv_live_20260605T155600Z",
        order_id="prior_unsettled_order",
        ticker=unsettled_ticker,
        side="yes",
        fill_count=1,
        submitted_at="2026-06-05T15:56:00+00:00",
    )
    write_prior_attempt(
        tmp_path,
        run_id="fv_live_20260605T155700Z",
        order_id="prior_no_fill_order",
        ticker=no_fill_ticker,
        side="yes",
        fill_count=0,
        submitted_at="2026-06-05T15:57:00+00:00",
    )
    client = SequencedOrderClient(
        [{"fill_count": 1, "cost": 0.4, "fees": 0.01}],
        order_details={
            "prior_settled_loss_order": {"fill_count": 1, "cost": 20.0, "fees": 0.5},
            "prior_unsettled_order": {"fill_count": 1, "cost": 24.0, "fees": 0.25},
            "prior_no_fill_order": {"fill_count": 0, "cost": 30.0, "fees": 0.0},
        },
    )

    manifest = FairValueLiveTradingJob(
        config=FairValueLiveTradingJobConfig(
            output_root=tmp_path,
            source="kalshi-public",
            coinbase_source="coinbase-live",
            max_markets=1,
            max_order_dollars=5.0,
            max_ticker_exposure_dollars=5.0,
            max_daily_loss_dollars=50.0,
            submit_live_orders=True,
        ),
        settings=live_enabled_settings(),
        order_client=client,
    ).run(now=now)

    assert len(client.requests) == 1
    attempts = json.loads(Path(manifest["artifacts"]["live_order_attempts"]["path"]).read_text())
    admission_accounting = attempts["admission_daily_loss_accounting"]
    assert admission_accounting["same_live_risk_day_rows"] == 3
    assert admission_accounting["same_live_risk_day_filled_rows"] == 2
    assert admission_accounting["same_live_risk_day_no_fill_rows"] == 1
    assert admission_accounting["same_live_risk_day_settled_rows"] == 1
    assert admission_accounting["same_live_risk_day_unsettled_rows"] == 1
    assert admission_accounting["daily_loss_used_dollars"] == 44.75
    assert attempts["attempts"][0]["daily_loss_used_before_dollars"] == 44.75
    assert manifest["runtime_controls"]["daily_loss_accounting"]["daily_loss_used_dollars"] == 45.16


def test_live_trading_job_uses_dashboard_config_for_order_sizing_and_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = live_runtime_repository_or_skip()
    repository.save_config(
        LiveRuntimeConfig(
            max_order_dollars=0.5,
            max_market_exposure_dollars=5.0,
            max_daily_loss_dollars=50.0,
            min_edge=0.0,
            max_markets=1,
        )
    )
    try:
        now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
        ticker = "KXBTC15M-FV-DB-CONFIG"
        install_live_job_fixture(monkeypatch, now=now, ticker=ticker)
        monkeypatch.setattr(
            fair_value_live_job,
            "public_market_result",
            lambda *, settings, ticker: {"status": "active", "result": None},
        )
        client = SequencedOrderClient([{"fill_count": 1, "cost": 0.4, "fees": 0.01}])

        manifest = FairValueLiveTradingJob(
            config=FairValueLiveTradingJobConfig(
                output_root=tmp_path,
                source="kalshi-public",
                coinbase_source="coinbase-live",
                submit_live_orders=True,
                runtime_config_source="postgres",
            ),
            settings=live_enabled_settings(),
            order_client=client,
        ).run(now=now)

        assert float(client.requests[0]["count"]) == 1.0
        assert manifest["config"]["max_order_dollars"] == 0.5
        assert manifest["config"]["max_markets"] == 1
        assert manifest["runtime_config"]["source"] == "dashboard_postgres"
        assert manifest["runtime_config"]["snapshot"]["max_market_exposure_dollars"] == 5.0
        assert manifest["runtime_controls"]["max_order_dollars"] == 0.5
    finally:
        repository.save_config(DEFAULT_FAIR_VALUE_LIVE_CONFIG)


def test_live_trading_job_uses_dashboard_config_for_exposure_and_daily_caps(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = live_runtime_repository_or_skip()
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    ticker = "KXBTC15M-FV-DB-CAPS"
    install_live_job_fixture(monkeypatch, now=now, ticker=ticker)
    monkeypatch.setattr(
        fair_value_live_job,
        "public_market_result",
        lambda *, settings, ticker: {"status": "active", "result": None},
    )
    try:
        repository.save_config(
            LiveRuntimeConfig(
                max_order_dollars=5.0,
                max_market_exposure_dollars=0.1,
                max_daily_loss_dollars=50.0,
                min_edge=0.0,
                max_markets=1,
            )
        )
        exposure_manifest = FairValueLiveTradingJob(
            config=FairValueLiveTradingJobConfig(
                output_root=tmp_path / "exposure",
                source="kalshi-public",
                coinbase_source="coinbase-live",
                submit_live_orders=True,
                runtime_config_source="postgres",
            ),
            settings=live_enabled_settings(),
            order_client=SequencedOrderClient([{"fill_count": 1, "cost": 0.4, "fees": 0.01}]),
        ).run(now=now)
        exposure_attempts = json.loads(
            Path(exposure_manifest["artifacts"]["live_order_attempts"]["path"]).read_text()
        )
        assert exposure_attempts["attempts"][0]["reason"] == "market_exposure_cap_reached"

        repository.save_config(
            LiveRuntimeConfig(
                max_order_dollars=5.0,
                max_market_exposure_dollars=5.0,
                max_daily_loss_dollars=0.5,
                min_edge=0.0,
                max_markets=1,
            )
        )
        write_prior_attempt(
            tmp_path / "daily",
            run_id="fv_live_20260604T150000Z",
            order_id="prior_db_daily_order",
            ticker="KXBTC15M-FV-DB-PRIOR",
            side="yes",
            fill_count=1,
        )
        daily_manifest = FairValueLiveTradingJob(
            config=FairValueLiveTradingJobConfig(
                output_root=tmp_path / "daily",
                source="kalshi-public",
                coinbase_source="coinbase-live",
                submit_live_orders=True,
                runtime_config_source="postgres",
            ),
            settings=live_enabled_settings(),
            order_client=SequencedOrderClient(
                [{"fill_count": 1, "cost": 0.4, "fees": 0.01}],
                order_details={
                    "prior_db_daily_order": {"fill_count": 1, "cost": 0.4, "fees": 0.01},
                },
            ),
        ).run(now=now + timedelta(minutes=1))
        daily_attempts = json.loads(
            Path(daily_manifest["artifacts"]["live_order_attempts"]["path"]).read_text()
        )
        assert daily_attempts["attempts"][0]["reason"] == "daily_loss_cap_reached"
    finally:
        repository.save_config(DEFAULT_FAIR_VALUE_LIVE_CONFIG)


def fixture_candles(now: datetime) -> list[list[float]]:
    base = int((now - timedelta(minutes=3)).timestamp())
    return [
        [base, 99.0, 100.5, 99.5, 100.0, 1.0],
        [base + 60, 100.0, 101.0, 100.0, 100.7, 1.2],
        [base + 120, 100.5, 101.5, 100.7, 101.0, 1.1],
    ]


class SequencedOrderClient:
    def __init__(self, fills: list[dict], *, order_details: dict[str, dict] | None = None):
        self.fills = list(fills)
        self.order_details = dict(order_details or {})
        self.requests: list[dict] = []

    def create_order(self, *, request_payload, settings):
        self.requests.append(dict(request_payload))
        fill = self.fills.pop(0)
        order_id = f"ord_{len(self.requests)}"
        self.order_details[order_id] = fill
        return {
            "order_id": order_id,
            "client_order_id": request_payload["client_order_id"],
            "fill_count": f"{float(fill['fill_count']):.2f}",
            "remaining_count": "0.00",
        }

    def get_order(self, *, order_id, settings):
        fill = self.order_details.get(order_id, {"fill_count": 0, "cost": 0.0, "fees": 0.0})
        return {
            "order": {
                "order_id": order_id,
                "fill_count_fp": f"{float(fill['fill_count']):.2f}",
                "taker_fill_cost_dollars": f"{float(fill['cost']):.6f}",
                "taker_fees_dollars": f"{float(fill['fees']):.6f}",
            }
        }


def live_enabled_settings():
    return settings_from_env(
        {
            "ALPHADB_RUNTIME_MODE": "gated-live",
            "ALPHADB_ENABLE_LIVE_ORDERS": "1",
            "ALPHADB_HUMAN_CUTOVER_APPROVED": "1",
            "KALSHI_API_KEY_ID": "key-id",
            "KALSHI_PRIVATE_KEY_PATH": "/tmp/fake-key.pem",
        }
    )


def install_live_job_fixture(monkeypatch, *, now: datetime, ticker: str) -> None:
    kalshi = FixtureKalshiRestClient(
        markets=[
            {
                "ticker": ticker,
                "series_ticker": "KXBTC15M",
                "event_ticker": f"{ticker}-EVENT",
                "status": "open",
                "open_time": (now - timedelta(minutes=10)).isoformat(),
                "close_time": (now + timedelta(minutes=5)).isoformat(),
                "updated_time": (now - timedelta(seconds=1)).isoformat(),
                "title": "Bitcoin above $100?",
                "payout_threshold": "100.00",
                "yes_ask_dollars": "0.40",
                "no_ask_dollars": "0.60",
            }
        ],
        orderbooks={
            ticker: {
                "orderbook_fp": {
                    "yes_dollars": [["0.39", "10"]],
                    "no_dollars": [["0.59", "10"]],
                }
            }
        },
    )
    monkeypatch.setattr(fair_value_live_job, "make_kalshi_client", lambda source, settings: kalshi)
    monkeypatch.setattr(
        fair_value_live_job,
        "make_coinbase_client",
        lambda source: FixtureCoinbaseClient(candles=fixture_candles(now)),
    )


def write_prior_attempt(
    root: Path,
    *,
    run_id: str,
    order_id: str,
    ticker: str,
    side: str,
    fill_count: int,
    submitted_at: str = "2026-06-04T14:59:00+00:00",
    generated_at: str | None = None,
) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    payload = {
        "schema_version": "kxbtc_fair_value_live_order_attempts.v1",
        "run_id": run_id,
        "generated_at": generated_at or submitted_at,
        "attempts": [
            {
                "attempt_id": f"attempt_{order_id}",
                "run_id": run_id,
                "submitted_at": submitted_at,
                "market_ticker": ticker,
                "side": side,
                "decision": {
                    "ticker": ticker,
                    "side": side,
                    "price": 0.4,
                    "fee_per_contract": 0.01,
                    "intended_contracts": fill_count,
                    "contracts": fill_count,
                    "max_loss_dollars": 0.41 * fill_count,
                },
                "status": "submitted",
                "reason": "submitted",
                "order_id": order_id,
                "fill_count": fill_count,
                "response_payload": {
                    "order_id": order_id,
                    "fill_count": f"{float(fill_count):.2f}",
                },
            }
        ],
    }
    (run_dir / "live_order_attempts.json").write_text(json.dumps(payload), encoding="utf-8")


def live_runtime_repository_or_skip() -> LiveRuntimeConfigRepository:
    database_url = settings_from_env().database_url
    repository = OperationalStateRepository(database_url)
    try:
        with repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    repository.apply_migrations()
    return LiveRuntimeConfigRepository(database_url)


def delete_lock_duplicate_test_statuses(database_url: str) -> None:
    with OperationalStateRepository(database_url).connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                delete from live_run_statuses
                where run_id like 'fv_live_prior_%'
                   or run_id like 'fv_live_2099%'
                """
            )
        connection.commit()
