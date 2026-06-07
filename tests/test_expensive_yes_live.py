from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

from alphadb.collectors.coinbase import FixtureCoinbaseClient
from alphadb.collectors.kalshi_rest import FixtureKalshiRestClient
from alphadb.config import settings_from_env
from alphadb.live_runtime import EXPENSIVE_YES_LIVE_STRATEGY
from alphadb.live_risk import LiveRiskAdmissionRepository
from alphadb.model_evaluation import fair_value_live_job
from alphadb.model_evaluation.fair_value_live_job import (
    FairValueLiveTradingJob,
    FairValueLiveTradingJobConfig,
    apply_live_freshness_gates,
    expensive_yes_decision,
)
from alphadb.model_evaluation.fair_value_replay import FairValueReplayConfig
from alphadb.state.repository import OperationalStateRepository


def test_expensive_yes_decision_rule_threshold_skips_and_sizes() -> None:
    config = FairValueReplayConfig(min_contract_price=0.65, max_order_dollars=1.0)

    trade = expensive_yes_decision(row("KXBTC15M-TRADE", yes_ask=0.65), config=config)
    below = expensive_yes_decision(row("KXBTC15M-BELOW", yes_ask=0.64), config=config)
    missing = expensive_yes_decision({"ticker": "KXBTC15M-MISSING"}, config=config)
    too_small = expensive_yes_decision(
        row("KXBTC15M-SMALL", yes_ask=0.99),
        config=FairValueReplayConfig(min_contract_price=0.65, max_order_dollars=0.5),
    )

    assert trade["decision"] == "trade"
    assert trade["side"] == "yes"
    assert trade["observed_yes_ask"] == 0.65
    assert trade["yes_ask_threshold"] == 0.65
    assert trade["intended_contracts"] == 1
    assert trade["max_loss_dollars"] > 0.65
    assert below["reason"] == "yes_ask_below_threshold"
    assert missing["reason"] == "missing_yes_ask"
    assert too_small["reason"] == "sizing_impossible"


def test_expensive_yes_freshness_gate_skips_stale_quote() -> None:
    decision = expensive_yes_decision(
        row("KXBTC15M-STALE", yes_ask=0.7),
        config=FairValueReplayConfig(min_contract_price=0.65, max_order_dollars=1.0),
    )
    gated = apply_live_freshness_gates(
        decision,
        {
            **row("KXBTC15M-STALE", yes_ask=0.7),
            "quote_observed_at": "2026-06-04T14:59:00+00:00",
        },
        generated_at=datetime(2026, 6, 4, 15, 0, tzinfo=UTC),
        quote_stale_seconds=15,
        coinbase_feature_stale_seconds=0,
        require_coinbase_freshness=False,
    )

    assert gated["decision"] == "skip"
    assert gated["reason"] == "quote_stale"


def test_expensive_yes_live_disabled_smoke_records_per_market_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    install_expensive_yes_fixture(monkeypatch, now=now)
    client = SequencedOrderClient([{"fill_count": 1, "cost": 0.7, "fees": 0.01}])

    manifest = FairValueLiveTradingJob(
        config=expensive_yes_config(tmp_path, submit_live_orders=False),
        settings=settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"}),
        order_client=client,
    ).run(now=now)

    attempts = json.loads(Path(manifest["artifacts"]["live_order_attempts"]["path"]).read_text())
    reasons = {attempt["market_ticker"]: attempt["reason"] for attempt in attempts["attempts"]}
    trade_attempt = next(
        attempt
        for attempt in attempts["attempts"]
        if attempt["market_ticker"] == "KXBTC15M-EXP-TRADE"
    )

    assert manifest["strategy"] == EXPENSIVE_YES_LIVE_STRATEGY
    assert manifest["decision_policy"] == "expensive_yes"
    assert manifest["counts"]["live_attempts"] == 3
    assert client.requests == []
    assert reasons["KXBTC15M-EXP-TRADE"] == "submit_live_orders_false"
    assert reasons["KXBTC15M-EXP-BELOW"] == "yes_ask_below_threshold"
    assert reasons["KXBTC15M-EXP-MISSING"] == "missing_orderbook_quote"
    assert trade_attempt["decision"]["observed_yes_ask"] == 0.7
    assert trade_attempt["decision"]["yes_ask_threshold"] == 0.65
    assert trade_attempt["market_exposure"]["sized_contracts"] == 1


def test_expensive_yes_guarded_ioc_uses_strategy_isolated_risk_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = live_risk_repository_or_skip()
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    install_expensive_yes_fixture(monkeypatch, now=now, include_only_trade=True)
    seed_live_risk_state(repository, now=now, strategy=EXPENSIVE_YES_LIVE_STRATEGY)
    seed_live_risk_state(repository, now=now, strategy="fair_value_live", daily_loss=9.5)
    monkeypatch.setattr(
        fair_value_live_job,
        "public_market_result",
        lambda *, settings, ticker: {"status": "active", "result": None},
    )
    client = SequencedOrderClient([{"fill_count": 1, "cost": 0.7, "fees": 0.01}])

    manifest = FairValueLiveTradingJob(
        config=expensive_yes_config(tmp_path, submit_live_orders=True),
        settings=live_enabled_settings(),
        order_client=client,
    ).run(now=now)

    attempts = json.loads(Path(manifest["artifacts"]["live_order_attempts"]["path"]).read_text())
    attempt = attempts["attempts"][0]
    risk_state = repository.get_state(
        strategy=EXPENSIVE_YES_LIVE_STRATEGY,
        live_risk_day=fair_value_live_job.live_risk_window(
            generated_at=now,
            live_risk_timezone="America/Los_Angeles",
        )[0],
    )

    assert len(client.requests) == 1
    assert client.requests[0]["side"] == "bid"
    assert float(client.requests[0]["price"]) == 0.7
    assert attempt["status"] == "submitted"
    assert attempt["risk_admission"]["status"] == "approved"
    assert attempt["risk_admission"]["state"]["strategy"] == EXPENSIVE_YES_LIVE_STRATEGY
    assert risk_state is not None
    assert risk_state.open_exposure_dollars > 0
    assert manifest["runtime_controls"]["orders_placed"] == 1


def test_expensive_yes_guard_denial_does_not_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    install_expensive_yes_fixture(monkeypatch, now=now, include_only_trade=True)
    client = SequencedOrderClient([{"fill_count": 1, "cost": 0.7, "fees": 0.01}])

    manifest = FairValueLiveTradingJob(
        config=expensive_yes_config(tmp_path, submit_live_orders=True),
        settings=settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"}),
        order_client=client,
    ).run(now=now)

    attempts = json.loads(Path(manifest["artifacts"]["live_order_attempts"]["path"]).read_text())
    attempt = attempts["attempts"][0]

    assert client.requests == []
    assert attempt["status"] == "skipped"
    assert attempt["reason"] != "submit_live_orders_false"
    assert attempt["runtime_guard"]["can_submit_live_orders"] is False


def test_expensive_yes_risk_denial_blocks_ioc_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = live_risk_repository_or_skip()
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    install_expensive_yes_fixture(monkeypatch, now=now, include_only_trade=True)
    seed_live_risk_state(
        repository,
        now=now,
        strategy=EXPENSIVE_YES_LIVE_STRATEGY,
        daily_loss=9.5,
    )
    client = SequencedOrderClient([{"fill_count": 1, "cost": 0.7, "fees": 0.01}])

    manifest = FairValueLiveTradingJob(
        config=expensive_yes_config(tmp_path, submit_live_orders=True),
        settings=live_enabled_settings(),
        order_client=client,
    ).run(now=now)

    attempts = json.loads(Path(manifest["artifacts"]["live_order_attempts"]["path"]).read_text())
    attempt = attempts["attempts"][0]

    assert client.requests == []
    assert attempt["status"] == "skipped"
    assert attempt["reason"] == "daily_loss_cap_reached"
    assert attempt["risk_admission"]["status"] == "denied"


def test_expensive_yes_no_fill_releases_risk_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = live_risk_repository_or_skip()
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    install_expensive_yes_fixture(monkeypatch, now=now, include_only_trade=True)
    seed_live_risk_state(repository, now=now, strategy=EXPENSIVE_YES_LIVE_STRATEGY)
    monkeypatch.setattr(
        fair_value_live_job,
        "public_market_result",
        lambda *, settings, ticker: {"status": "active", "result": None},
    )
    client = SequencedOrderClient([{"fill_count": 0, "cost": 0.0, "fees": 0.0}])

    manifest = FairValueLiveTradingJob(
        config=expensive_yes_config(tmp_path, submit_live_orders=True),
        settings=live_enabled_settings(),
        order_client=client,
    ).run(now=now)

    attempts = json.loads(Path(manifest["artifacts"]["live_order_attempts"]["path"]).read_text())
    reconciliation = json.loads(
        Path(manifest["artifacts"]["live_reconciliation_report"]["path"]).read_text()
    )
    state = repository.get_state(
        strategy=EXPENSIVE_YES_LIVE_STRATEGY,
        live_risk_day=fair_value_live_job.live_risk_window(
            generated_at=now,
            live_risk_timezone="America/Los_Angeles",
        )[0],
    )

    assert attempts["attempts"][0]["status"] == "submitted"
    assert attempts["attempts"][0]["fill_count"] == 0
    assert attempts["attempts"][0]["risk_transition"]["reason"] == "released"
    assert reconciliation["rows"][0]["settlement_status"] == "no_fill"
    assert state is not None
    assert state.pending_exposure_dollars == 0.0
    assert state.open_exposure_dollars == 0.0


def row(ticker: str, *, yes_ask: float) -> dict[str, Any]:
    return {
        "row_type": "decision",
        "ticker": ticker,
        "market_ticker": ticker,
        "decision_timestamp": "2026-06-04T15:00:00+00:00",
        "yes_ask": yes_ask,
    }


def expensive_yes_config(
    output_root: Path,
    *,
    submit_live_orders: bool,
) -> FairValueLiveTradingJobConfig:
    return FairValueLiveTradingJobConfig(
        output_root=output_root,
        strategy=EXPENSIVE_YES_LIVE_STRATEGY,
        decision_policy="expensive_yes",
        source="kalshi-public",
        coinbase_source="fixture",
        max_markets=3,
        min_edge=0.0,
        min_contract_price=0.65,
        min_edge_values=(0.0,),
        max_order_dollars=1.0,
        max_ticker_exposure_dollars=1.0,
        max_daily_loss_dollars=10.0,
        submit_live_orders=submit_live_orders,
        runtime_config_source="cli",
        quote_stale_seconds=120,
        coinbase_feature_stale_seconds=0,
    )


def install_expensive_yes_fixture(
    monkeypatch: pytest.MonkeyPatch,
    *,
    now: datetime,
    include_only_trade: bool = False,
) -> None:
    markets = [
        market("KXBTC15M-EXP-TRADE", now=now),
    ]
    orderbooks: dict[str, dict[str, Any]] = {
        "KXBTC15M-EXP-TRADE": orderbook_for_yes_ask(0.7),
    }
    if not include_only_trade:
        markets.extend(
            [
                market("KXBTC15M-EXP-BELOW", now=now),
                market("KXBTC15M-EXP-MISSING", now=now),
            ]
        )
        orderbooks["KXBTC15M-EXP-BELOW"] = orderbook_for_yes_ask(0.6)
        orderbooks["KXBTC15M-EXP-MISSING"] = {
            "orderbook_fp": {"yes_dollars": [], "no_dollars": []}
        }
    kalshi = FixtureKalshiRestClient(markets=markets, orderbooks=orderbooks)
    monkeypatch.setattr(fair_value_live_job, "make_kalshi_client", lambda source, settings: kalshi)
    monkeypatch.setattr(
        fair_value_live_job,
        "make_coinbase_client",
        lambda source: FixtureCoinbaseClient(candles=[]),
    )


def market(ticker: str, *, now: datetime) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "series_ticker": "KXBTC15M",
        "event_ticker": f"{ticker}-EVENT",
        "status": "open",
        "open_time": (now - timedelta(minutes=10)).isoformat(),
        "close_time": (now + timedelta(minutes=5)).isoformat(),
        "updated_time": (now - timedelta(seconds=1)).isoformat(),
        "title": "Bitcoin above $100?",
        "payout_threshold": "100.00",
    }


def orderbook_for_yes_ask(yes_ask: float) -> dict[str, Any]:
    no_bid = round(1.0 - yes_ask, 6)
    yes_bid = round(1.0 - no_bid, 6)
    return {
        "orderbook_fp": {
            "yes_dollars": [[f"{yes_bid:.4f}", "10"]],
            "no_dollars": [[f"{no_bid:.4f}", "10"]],
        }
    }


class SequencedOrderClient:
    def __init__(self, fills: list[dict[str, Any]]):
        self.fills = list(fills)
        self.requests: list[dict[str, Any]] = []

    def create_order(self, *, request_payload: dict[str, Any], settings: Any) -> dict[str, Any]:
        self.requests.append(dict(request_payload))
        fill = self.fills.pop(0)
        return {
            "order_id": f"ord_{len(self.requests)}",
            "client_order_id": request_payload["client_order_id"],
            "fill_count": f"{float(fill['fill_count']):.2f}",
            "remaining_count": "0.00",
        }

    def get_order(self, *, order_id: str, settings: Any) -> dict[str, Any]:
        return {
            "order": {
                "order_id": order_id,
                "fill_count_fp": "1.00",
                "taker_fill_cost_dollars": "0.700000",
                "taker_fees_dollars": "0.010000",
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


def live_risk_repository_or_skip() -> LiveRiskAdmissionRepository:
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
    return LiveRiskAdmissionRepository(database_url)


def seed_live_risk_state(
    repository: LiveRiskAdmissionRepository,
    *,
    now: datetime,
    strategy: str,
    daily_loss: float = 0.0,
) -> None:
    live_risk_day = fair_value_live_job.live_risk_window(
        generated_at=now,
        live_risk_timezone="America/Los_Angeles",
    )[0]
    repository.upsert_state(
        strategy=strategy,
        live_risk_day=live_risk_day,
        daily_loss_used_dollars=daily_loss,
        updated_at=now,
    )
