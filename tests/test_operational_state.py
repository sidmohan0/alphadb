from __future__ import annotations

from datetime import UTC, datetime

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from alphadb.config import settings_from_env
from alphadb.markets.spec import kxbtc15m_spec
from alphadb.state.repository import OperationalStateRepository


def repository_or_skip() -> OperationalStateRepository:
    repository = OperationalStateRepository(settings_from_env().database_url)
    try:
        with repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                cursor.fetchone()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    return repository


def test_migrations_are_idempotent_and_create_complete_tracer_run() -> None:
    repository = repository_or_skip()

    repository.apply_migrations()
    assert repository.apply_migrations() == []

    tracer = repository.create_tracer_run(
        kxbtc15m_spec(),
        now=datetime(2026, 5, 31, 20, 0, tzinfo=UTC),
    )
    summary = repository.get_run_summary(tracer.run_id)

    assert summary["run_id"] == tracer.run_id
    assert summary["mode"] == "tracer"
    assert summary["market_series"] == "KXBTC15M"
    assert summary["decisions"] == 1
    assert summary["risk_decisions"] == 1
    assert summary["order_intents"] == 1

    counts = repository.counts()
    assert counts.runs >= 1
    assert counts.market_instances >= 1
    assert counts.decisions >= 1
    assert counts.risk_decisions >= 1
    assert counts.order_intents >= 1


def test_decision_uniqueness_preserves_one_authoritative_outcome_per_run_instance() -> None:
    repository = repository_or_skip()
    repository.apply_migrations()
    tracer = repository.create_tracer_run(kxbtc15m_spec())

    with pytest.raises(errors.UniqueViolation):
        with repository.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into decisions (
                        decision_id,
                        run_id,
                        market_ticker,
                        decision_timestamp,
                        outcome,
                        probability_yes,
                        selected_side,
                        skip_reason,
                        metadata
                    )
                    values (%s, %s, %s, now(), %s, %s, %s, %s, %s)
                    """,
                    (
                        f"{tracer.decision_id}_duplicate",
                        tracer.run_id,
                        tracer.market_ticker,
                        "skip",
                        None,
                        None,
                        "duplicate",
                        Jsonb({}),
                    ),
                )
                connection.commit()
