from datetime import UTC, datetime

import psycopg
import pytest

from alphadb.config import settings_from_env
from alphadb.markets.spec import kxbtc15m_spec
from alphadb.strategy.state import StrategyRunRepository, fresh_outcome
from alphadb.state.repository import OperationalStateRepository

pytest.importorskip("streamlit")
from alphadb.dashboard.app import (  # noqa: E402
    latest_strategy_outcome_rows,
    live_order_rows,
    strategy_run_rows,
)


def dashboard_repository_or_skip() -> OperationalStateRepository:
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


def test_dashboard_strategy_rows_reflect_persisted_runner_state() -> None:
    repository = dashboard_repository_or_skip()
    run = StrategyRunRepository(repository.database_url).start_run(
        market_series="KXBTC15M",
        runtime_mode="paper",
        started_at=datetime(2026, 6, 2, 21, 0, tzinfo=UTC),
    )
    market = repository.create_tracer_run(kxbtc15m_spec()).market_ticker
    StrategyRunRepository(repository.database_url).record_outcome(
        fresh_outcome(
            run_id=run.run_id,
            market_ticker=market,
            decision_timestamp=datetime(2026, 5, 31, 21, 13, tzinfo=UTC),
            status="skipped",
            reason="ev_below_threshold",
            latency_checkpoints={"model_inference_ms": 1.0},
        )
    )
    StrategyRunRepository(repository.database_url).finish_run(
        run_id=run.run_id,
        status="completed",
        metadata_patch={"latest_counts": {"scanned": 1, "skipped": 1}},
    )

    run_rows = strategy_run_rows(repository.database_url)
    outcome_rows = latest_strategy_outcome_rows(repository.database_url)
    live_rows = live_order_rows(repository.database_url)

    assert any(row["metric"] == "run_id" and row["value"] == run.run_id for row in run_rows)
    assert any(row["metric"] == "cycles_skipped" and row["value"] >= 1 for row in run_rows)
    assert outcome_rows[0]["market"] == market
    assert outcome_rows[0]["cycle_status"] == "cycle_skipped"
    assert outcome_rows[0]["execution_status"] == "no_live_order"
    assert live_rows
