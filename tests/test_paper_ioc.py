from datetime import UTC, datetime

import psycopg
import pytest
from psycopg.types.json import Jsonb

from alphadb.config import settings_from_env
from alphadb.markets.spec import kxbtc15m_spec
from alphadb.paper.ioc import (
    PaperExecutionRepository,
    PaperIocExecutor,
    PaperLiquidity,
)
from alphadb.state.repository import OperationalStateRepository


def paper_repository_or_skip() -> OperationalStateRepository:
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


def approved_yes_intent(repository: OperationalStateRepository) -> str:
    return repository.create_tracer_run(kxbtc15m_spec()).order_intent_id


def approved_no_intent(repository: OperationalStateRepository) -> str:
    tracer = repository.create_tracer_run(kxbtc15m_spec())
    with repository.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                update decisions
                set probability_yes = %s, selected_side = %s, metadata = %s
                where decision_id = %s
                """,
                (0.35, "no", Jsonb({"test_side": "no"}), tracer.decision_id),
            )
            cursor.execute(
                """
                update order_intents
                set side = %s, price = %s, quantity = %s, max_cost_dollars = %s
                where order_intent_id = %s
                """,
                ("no", 0.40, 2, 0.80, tracer.order_intent_id),
            )
        connection.commit()
    return tracer.order_intent_id


def test_paper_ioc_fills_approved_yes_order_and_updates_position_reconciliation() -> None:
    repository = paper_repository_or_skip()
    order_intent_id = approved_yes_intent(repository)

    result = PaperIocExecutor(repository.database_url).execute(
        order_intent_id=order_intent_id,
        liquidity=PaperLiquidity(
            side="yes",
            available_price_dollars=0.49,
            available_quantity=10,
            mark_price_dollars=0.55,
        ),
        executed_at=datetime(2026, 5, 31, 21, 20, tzinfo=UTC),
    )

    assert result.status == "filled"
    assert result.side == "yes"
    assert result.filled_quantity == 1
    assert result.fill_price_dollars == 0.49
    assert result.position_quantity == 1
    assert result.realized_pnl_dollars == 0
    assert result.unrealized_pnl_dollars == pytest.approx(0.06)
    assert result.live_orders_sent == 0


def test_paper_ioc_represents_no_side_price_semantics() -> None:
    repository = paper_repository_or_skip()
    order_intent_id = approved_no_intent(repository)

    result = PaperIocExecutor(repository.database_url).execute(
        order_intent_id=order_intent_id,
        liquidity=PaperLiquidity(
            side="no",
            available_price_dollars=0.39,
            available_quantity=2,
            mark_price_dollars=0.45,
        ),
    )

    assert result.status == "filled"
    assert result.side == "no"
    assert result.limit_price_dollars == 0.40
    assert result.fill_price_dollars == 0.39
    assert result.filled_quantity == 2
    assert result.unrealized_pnl_dollars == pytest.approx(0.12)


def test_paper_ioc_handles_non_fill_and_partial_fill_cases() -> None:
    repository = paper_repository_or_skip()
    unfilled_intent = approved_yes_intent(repository)
    partial_intent = approved_no_intent(repository)

    unfilled = PaperIocExecutor(repository.database_url).execute(
        order_intent_id=unfilled_intent,
        liquidity=PaperLiquidity(
            side="yes",
            available_price_dollars=0.99,
            available_quantity=5,
        ),
    )
    partial = PaperIocExecutor(repository.database_url).execute(
        order_intent_id=partial_intent,
        liquidity=PaperLiquidity(
            side="no",
            available_price_dollars=0.39,
            available_quantity=1,
            mark_price_dollars=0.40,
        ),
    )

    assert unfilled.status == "unfilled"
    assert unfilled.filled_quantity == 0
    assert unfilled.fill_price_dollars is None
    assert unfilled.position_quantity == 0
    assert partial.status == "partial"
    assert partial.filled_quantity == 1
    assert partial.position_quantity >= 1


def test_paper_ioc_has_no_live_order_client_and_is_idempotent() -> None:
    repository = paper_repository_or_skip()
    order_intent_id = approved_yes_intent(repository)
    executor = PaperIocExecutor(repository.database_url)

    first = executor.execute(
        order_intent_id=order_intent_id,
        liquidity=PaperLiquidity(
            side="yes",
            available_price_dollars=0.49,
            available_quantity=1,
        ),
    )
    second = executor.execute(
        order_intent_id=order_intent_id,
        liquidity=PaperLiquidity(
            side="yes",
            available_price_dollars=0.49,
            available_quantity=1,
        ),
    )

    assert executor.live_order_client is None
    assert first.inserted is True
    assert second.inserted is False
    assert second.paper_order_id == first.paper_order_id
    assert len(PaperExecutionRepository(repository.database_url).list_fills()) >= 1
