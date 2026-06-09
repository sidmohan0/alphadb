from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import psycopg
import pytest

from alphadb.config import settings_from_env
from alphadb.live_orders import LiveOrderAttempt, LiveOrderRepository
from alphadb.live_settlement import (
    MarketResultObservation,
    LiveTradeReconciliationRepository,
    reconcile_live_order_attempt,
    reconcile_live_settlements,
    summarize_live_trade_reconciliations,
)
from alphadb.performance import build_performance_summary
from alphadb.state.repository import OperationalStateRepository


NOW = datetime(2026, 6, 9, 17, 30, tzinfo=UTC)


class FakeMarketResultClient:
    def __init__(self, observations: dict[str, MarketResultObservation]):
        self.observations = observations
        self.calls: list[str] = []

    def get_market_result(self, *, ticker, settings, observed_at):
        self.calls.append(ticker)
        observation = self.observations[ticker]
        return MarketResultObservation(
            market_ticker=observation.market_ticker,
            status=observation.status,
            result=observation.result,
            source=observation.source,
            observed_at=observed_at,
            metadata=observation.metadata,
        )


def repository_or_skip() -> OperationalStateRepository:
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


def test_reconcile_live_order_attempt_settles_public_win_with_actual_economics() -> None:
    row = reconcile_live_order_attempt(
        {
            "live_order_attempt_id": "live_order_win",
            "strategy": "fair_value_live",
            "market_ticker": "KXBTC15M-WIN",
            "intended_side": "yes",
            "intended_price_dollars": 0.91,
            "fill_count": 2,
            "request_payload": {
                "metadata": {
                    "run_id": "fv_live_20260609T173000Z",
                    "market_context_source": "brti_primary",
                }
            },
            "response_payload": {
                "order": {
                    "taker_fill_cost_dollars": 1.80,
                    "taker_fees_dollars": 0.02,
                }
            },
            "status": "accepted",
        },
        market_result=MarketResultObservation(
            market_ticker="KXBTC15M-WIN",
            status="finalized",
            result="yes",
            observed_at=NOW,
        ),
        reconciled_at=NOW,
    )

    assert row["settlement_status"] == "settled_win"
    assert row["payout_dollars"] == 2.0
    assert row["net_pnl_dollars"] == pytest.approx(0.18)
    assert row["decision_source"] == "brti_primary"
    assert row["settlement_source"] == "kalshi_public_market_api"
    assert row["metadata"]["cost_source"] == "response_payload.actual_cost"
    assert row["metadata"]["fees_source"] == "response_payload.actual_fees"


def test_reconcile_live_order_attempt_covers_loss_no_fill_open_and_lookup_failure() -> None:
    loss = reconcile_live_order_attempt(
        attempt("loss", side="yes", fill_count=1, price=0.4),
        market_result=MarketResultObservation(
            market_ticker="KXBTC15M-LOSS",
            status="finalized",
            result="no",
            observed_at=NOW,
        ),
        reconciled_at=NOW,
    )
    no_fill = reconcile_live_order_attempt(
        attempt("none", side="no", fill_count=0, price=0.7),
        market_result=None,
        reconciled_at=NOW,
    )
    open_row = reconcile_live_order_attempt(
        attempt("open", side="yes", fill_count=1, price=0.4),
        market_result=MarketResultObservation(
            market_ticker="KXBTC15M-OPEN",
            status="active",
            result=None,
            observed_at=NOW,
        ),
        reconciled_at=NOW,
    )
    failed = reconcile_live_order_attempt(
        attempt("failed", side="yes", fill_count=1, price=0.4),
        market_result=MarketResultObservation(
            market_ticker="KXBTC15M-FAILED",
            status="unknown",
            result=None,
            observed_at=NOW,
            metadata={"error": "HTTPError: 502"},
        ),
        reconciled_at=NOW,
    )

    assert loss["settlement_status"] == "settled_loss"
    assert loss["payout_dollars"] == 0.0
    assert loss["net_pnl_dollars"] < 0
    assert no_fill["settlement_status"] == "no_fill"
    assert no_fill["net_pnl_dollars"] == 0.0
    assert no_fill["unsettled_exposure_dollars"] == 0.0
    assert open_row["settlement_status"] == "open"
    assert open_row["unsettled_exposure_dollars"] > 0
    assert failed["settlement_status"] == "lookup_failed"
    assert failed["metadata"]["lookup_error"] == "HTTPError: 502"


def test_reconcile_live_order_attempt_uses_partial_fill_and_records_fallbacks() -> None:
    row = reconcile_live_order_attempt(
        {
            **attempt("partial", side="no", fill_count=0.5, price=0.6),
            "intended_quantity": 10,
        },
        market_result=MarketResultObservation(
            market_ticker="KXBTC15M-PARTIAL",
            status="active",
            result=None,
            observed_at=NOW,
        ),
        reconciled_at=NOW,
    )

    assert row["filled_contracts"] == 0.5
    assert row["cost_dollars"] == pytest.approx(0.3)
    assert row["fees_dollars"] == pytest.approx(0.0084)
    assert row["unsettled_exposure_dollars"] == pytest.approx(0.3084)
    assert row["metadata"]["cost_source"] == "fallback_intended_price_times_fill"
    assert row["metadata"]["fees_source"] == "fallback_taker_fee_assumption"


def test_live_reconciliation_summary_and_performance_prefer_canonical_rows() -> None:
    rows = [
        reconcile_live_order_attempt(
            attempt("win", side="yes", fill_count=2, price=0.9),
            market_result=MarketResultObservation(
                market_ticker="KXBTC15M-WIN",
                status="finalized",
                result="yes",
                observed_at=NOW,
            ),
            reconciled_at=NOW,
        ),
        reconcile_live_order_attempt(
            attempt("open", side="no", fill_count=1, price=0.4),
            market_result=MarketResultObservation(
                market_ticker="KXBTC15M-OPEN",
                status="active",
                result=None,
                observed_at=NOW,
            ),
            reconciled_at=NOW,
        ),
        reconcile_live_order_attempt(
            attempt("none", side="yes", fill_count=0, price=0.5),
            market_result=None,
            reconciled_at=NOW,
        ),
    ]

    summary = summarize_live_trade_reconciliations(rows, generated_at=NOW)
    performance = build_performance_summary(
        strategy="fair_value_live",
        market_series="KXBTC15M",
        generated_at=NOW,
        live_reconciliation_rows=rows,
    )

    assert summary["pnl"]["settled_trade_count"] == 1
    assert summary["pnl"]["open_trade_count"] == 1
    assert summary["pnl"]["no_fill_count"] == 1
    assert summary["settlement"]["state"] == "partial"
    assert performance["pnl"]["status"] == "partial"
    assert performance["pnl"]["settlement_state"] == "partial"
    assert performance["pnl"]["gross_cost_dollars"] > 0
    assert performance["pnl"]["payout_dollars"] == 2.0
    assert performance["pnl"]["win_rate"] == 1.0


def test_brti_primary_live_smoke_needs_no_manual_lookup_after_reconciliation() -> None:
    row = reconcile_live_order_attempt(
        {
            **attempt("brti", side="no", fill_count=10, price=0.999),
            "request_payload": {
                "metadata": {
                    "run_id": "fv_live_20260609T173000Z",
                    "market_context_source": "brti_primary",
                }
            },
        },
        market_result=MarketResultObservation(
            market_ticker="KXBTC15M-BRTI",
            status="finalized",
            result="no",
            observed_at=NOW,
        ),
        reconciled_at=NOW,
    )
    performance = build_performance_summary(
        strategy="fair_value_live",
        market_series="KXBTC15M",
        generated_at=NOW,
        live_reconciliation_rows=[row],
    )

    assert row["decision_source"] == "brti_primary"
    assert row["settlement_status"] == "settled_win"
    assert row["metadata"]["market_result_observation"]["source"] == "kalshi_public_market_api"
    assert performance["pnl"]["status"] == "ok"
    assert performance["pnl"]["realized_pnl_dollars"] > 0
    assert performance["pnl"]["unsettled_exposure_dollars"] == 0.0


def test_reconcile_live_settlements_is_idempotent_scoped_and_caches_market_results() -> None:
    repository = repository_or_skip()
    strategy = f"settlement_test_{uuid4().hex[:8]}"
    other_strategy = f"settlement_other_{uuid4().hex[:8]}"
    risk_day = date(2026, 6, 9)
    live_orders = LiveOrderRepository(repository.database_url)
    first = live_orders.persist(
        live_attempt("first", strategy=strategy, ticker="KXBTC15M-BATCH", risk_day=risk_day)
    )
    second = live_orders.persist(
        live_attempt("second", strategy=strategy, ticker="KXBTC15M-BATCH", risk_day=risk_day)
    )
    failed = live_orders.persist(
        live_attempt("failed", strategy=strategy, ticker="KXBTC15M-FAIL", risk_day=risk_day)
    )
    live_orders.persist(
        live_attempt("other", strategy=other_strategy, ticker="KXBTC15M-BATCH", risk_day=risk_day)
    )
    client = FakeMarketResultClient(
        {
            "KXBTC15M-BATCH": MarketResultObservation(
                market_ticker="KXBTC15M-BATCH",
                status="finalized",
                result="yes",
            ),
            "KXBTC15M-FAIL": MarketResultObservation(
                market_ticker="KXBTC15M-FAIL",
                status="unknown",
                result=None,
                metadata={"error": "timeout"},
            ),
        }
    )

    first_summary = reconcile_live_settlements(
        database_url=repository.database_url,
        settings=settings_from_env(),
        strategy=strategy,
        live_risk_day=risk_day,
        market_client=client,
        reconciled_at=NOW,
    )
    second_summary = reconcile_live_settlements(
        database_url=repository.database_url,
        settings=settings_from_env(),
        strategy=strategy,
        live_risk_day=risk_day,
        market_client=client,
        reconciled_at=NOW,
    )
    rows = LiveTradeReconciliationRepository(repository.database_url).recent_rows(
        strategy=strategy,
        limit=10,
    )

    assert first.live_order_attempt_id in {row["live_order_attempt_id"] for row in rows}
    assert second.live_order_attempt_id in {row["live_order_attempt_id"] for row in rows}
    assert failed.live_order_attempt_id in {row["live_order_attempt_id"] for row in rows}
    assert len(rows) == 3
    assert first_summary["lookup_count"] == 2
    assert second_summary["lookup_count"] == 2
    assert client.calls.count("KXBTC15M-BATCH") == 2
    assert client.calls.count("KXBTC15M-FAIL") == 2
    assert first_summary["counts"]["settled_win"] == 2
    assert first_summary["counts"]["lookup_failed"] == 1


def attempt(
    suffix: str,
    *,
    side: str,
    fill_count: float,
    price: float,
) -> dict:
    ticker = f"KXBTC15M-{suffix.upper()}"
    return {
        "live_order_attempt_id": f"live_order_{suffix}",
        "strategy": "fair_value_live",
        "market_ticker": ticker,
        "intended_side": side,
        "intended_price_dollars": price,
        "fill_count": fill_count,
        "runtime_mode": "gated-live",
        "status": "accepted",
        "request_payload": {
            "ticker": ticker,
            "side": "bid" if side == "yes" else "ask",
            "price": price if side == "yes" else 1.0 - price,
        },
        "response_payload": {"fill_count": str(fill_count)},
    }


def live_attempt(
    suffix: str,
    *,
    strategy: str,
    ticker: str,
    risk_day: date,
) -> LiveOrderAttempt:
    return LiveOrderAttempt(
        live_order_attempt_id=f"live_order_{suffix}_{uuid4().hex[:8]}",
        order_intent_id=None,
        risk_decision_id=None,
        strategy=strategy,
        live_risk_day=risk_day,
        reservation_id=f"res_{suffix}_{uuid4().hex[:8]}",
        market_ticker=ticker,
        client_order_id=f"client_{suffix}_{uuid4().hex[:8]}",
        intended_side="yes",
        intended_price_dollars=0.9,
        intended_quantity=1,
        intended_max_loss_dollars=0.91,
        runtime_mode="gated-live",
        status="accepted",
        guard_reason=None,
        request_payload={
            "ticker": ticker,
            "side": "bid",
            "price": "0.9000",
            "metadata": {"market_context_source": "brti_primary"},
        },
        response_payload={"fill_count": "1.00"},
        submitted_at=NOW,
        exchange_order_id=f"ord_{suffix}",
        exchange_status="accepted",
        exchange_response_at=NOW,
        fill_count=1,
        remaining_count=0,
    )
