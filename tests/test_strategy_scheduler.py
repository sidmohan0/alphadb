from datetime import UTC, datetime

import psycopg
import pytest

from alphadb.config import settings_from_env
from alphadb.markets.spec import kxbtc15m_spec
from alphadb.strategy.scheduler import Kxbtc15mHandledMarketScheduler, MarketCandidate
from alphadb.strategy.state import StrategyRunRepository, fresh_outcome
from alphadb.state.repository import OperationalStateRepository


def scheduler_repository_or_skip() -> OperationalStateRepository:
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


def candidate(repository: OperationalStateRepository) -> MarketCandidate:
    tracer = repository.create_tracer_run(
        kxbtc15m_spec(),
        now=datetime(2026, 5, 31, 21, 0, tzinfo=UTC),
    )
    return MarketCandidate(
        market_ticker=tracer.market_ticker,
        open_time=datetime(2026, 5, 31, 21, 0, tzinfo=UTC),
        close_time=datetime(2026, 5, 31, 21, 15, tzinfo=UTC),
    )


def strategy_run(repository: OperationalStateRepository) -> str:
    return StrategyRunRepository(repository.database_url).start_run(
        market_series="KXBTC15M",
        runtime_mode="paper",
        started_at=datetime(2026, 5, 31, 21, 0, tzinfo=UTC),
    ).run_id


def test_scheduler_waits_before_decision_window_without_marking_handled() -> None:
    repository = scheduler_repository_or_skip()
    run_id = strategy_run(repository)
    market = candidate(repository)
    scheduler = Kxbtc15mHandledMarketScheduler(
        database_url=repository.database_url,
        spec=kxbtc15m_spec(),
    )

    result = scheduler.scan(
        run_id=run_id,
        markets=[market],
        now=datetime(2026, 5, 31, 21, 11, tzinfo=UTC),
        handler=lambda _market, _now: pytest.fail("handler should not be called"),
    )

    assert result.waiting == 1
    assert result.outcomes == ()


def test_scheduler_handles_in_window_market_and_prevents_duplicates() -> None:
    repository = scheduler_repository_or_skip()
    run_id = strategy_run(repository)
    market = candidate(repository)
    scheduler = Kxbtc15mHandledMarketScheduler(
        database_url=repository.database_url,
        spec=kxbtc15m_spec(),
    )

    def handler(market_: MarketCandidate, now: datetime):
        return fresh_outcome(
            run_id=run_id,
            market_ticker=market_.market_ticker,
            decision_timestamp=now,
            status="handled",
            metadata={"test": "handled"},
        )

    first = scheduler.scan(
        run_id=run_id,
        markets=[market],
        now=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
        handler=handler,
    )
    second = scheduler.scan(
        run_id=run_id,
        markets=[market],
        now=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
        handler=handler,
    )

    assert first.handled == 1
    assert first.outcomes[0].inserted is True
    assert second.duplicate_prevented == 1
    assert second.outcomes[0].inserted is False


def test_scheduler_marks_missed_window_skip_and_retryable_handler_error() -> None:
    repository = scheduler_repository_or_skip()
    missed_run_id = strategy_run(repository)
    error_run_id = strategy_run(repository)
    missed = candidate(repository)
    error_market = candidate(repository)
    scheduler = Kxbtc15mHandledMarketScheduler(
        database_url=repository.database_url,
        spec=kxbtc15m_spec(),
    )

    missed_result = scheduler.scan(
        run_id=missed_run_id,
        markets=[missed],
        now=datetime(2026, 5, 31, 21, 14, 30, tzinfo=UTC),
        handler=lambda _market, _now: pytest.fail("missed handler should not be called"),
    )
    error_result = scheduler.scan(
        run_id=error_run_id,
        markets=[error_market],
        now=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
        handler=lambda _market, _now: (_ for _ in ()).throw(RuntimeError("temporary")),
    )

    assert missed_result.skipped == 1
    assert missed_result.outcomes[0].reason == "missed_decision_window"
    assert error_result.errored == 1
    assert error_result.outcomes[0].metadata["retryable"] is True
