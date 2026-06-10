from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from alphadb.config import settings_from_env
from alphadb.live_authority import LiveDecisionAuthorityLeaseRepository
from alphadb.state.repository import OperationalStateRepository


def repository_or_skip() -> LiveDecisionAuthorityLeaseRepository:
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
    return LiveDecisionAuthorityLeaseRepository(database_url)


def test_live_decision_authority_migration_creates_lease_table() -> None:
    repository = repository_or_skip()

    with psycopg.connect(repository.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "select to_regclass('public.live_decision_authority_leases')"
            )
            row = cursor.fetchone()

    assert row is not None
    assert row[0] == "live_decision_authority_leases"


def test_live_decision_authority_acquire_held_expired_and_release() -> None:
    repository = repository_or_skip()
    strategy = f"test_authority_{uuid4().hex[:10]}"
    now = datetime(2026, 6, 9, 21, 0, tzinfo=UTC)

    first = repository.acquire(
        strategy=strategy,
        run_id="run_first",
        owner_id="worker_first",
        now=now,
        ttl_seconds=60,
    )
    held = repository.acquire(
        strategy=strategy,
        run_id="run_second",
        owner_id="worker_second",
        now=now + timedelta(seconds=10),
        ttl_seconds=60,
    )
    released = repository.release(
        strategy=strategy,
        owner_id="worker_first",
        fencing_token=first.lease.fencing_token,
        now=now + timedelta(seconds=20),
    )
    reacquired = repository.acquire(
        strategy=strategy,
        run_id="run_third",
        owner_id="worker_third",
        now=now + timedelta(seconds=21),
        ttl_seconds=60,
    )

    assert first.acquired is True
    assert first.lease is not None
    assert first.lease.fencing_token == 1
    assert held.acquired is False
    assert held.reason == "live_decision_authority_held"
    assert held.current_lease is not None
    assert held.current_lease.fencing_token == 1
    assert released.released is True
    assert released.lease is not None
    assert released.lease.status == "released"
    assert reacquired.acquired is True
    assert reacquired.lease is not None
    assert reacquired.lease.fencing_token == 2


def test_live_decision_authority_expired_reclaim_denies_stale_release() -> None:
    repository = repository_or_skip()
    strategy = f"test_authority_{uuid4().hex[:10]}"
    now = datetime(2026, 6, 9, 22, 0, tzinfo=UTC)

    first = repository.acquire(
        strategy=strategy,
        run_id="run_first",
        owner_id="worker_first",
        now=now,
        ttl_seconds=30,
    )
    reclaimed = repository.acquire(
        strategy=strategy,
        run_id="run_reclaimed",
        owner_id="worker_reclaimed",
        now=now + timedelta(seconds=31),
        ttl_seconds=30,
    )
    stale_release = repository.release(
        strategy=strategy,
        owner_id="worker_first",
        fencing_token=first.lease.fencing_token,
        now=now + timedelta(seconds=32),
    )
    current = repository.get(strategy=strategy)

    assert first.acquired is True
    assert first.lease is not None
    assert reclaimed.acquired is True
    assert reclaimed.lease is not None
    assert reclaimed.lease.fencing_token == first.lease.fencing_token + 1
    assert stale_release.released is False
    assert stale_release.reason == "stale_live_decision_authority_token"
    assert stale_release.current_lease is not None
    assert stale_release.current_lease.fencing_token == reclaimed.lease.fencing_token
    assert current is not None
    assert current.owner_id == "worker_reclaimed"
    assert current.status == "active"


def test_live_decision_authority_validate_active_denies_stale_token() -> None:
    repository = repository_or_skip()
    strategy = f"test_authority_{uuid4().hex[:10]}"
    now = datetime(2026, 6, 9, 22, 30, tzinfo=UTC)

    first = repository.acquire(
        strategy=strategy,
        run_id="run_first",
        owner_id="worker_first",
        now=now,
        ttl_seconds=30,
    )
    valid_first = repository.validate_active(
        strategy=strategy,
        owner_id="worker_first",
        fencing_token=first.lease.fencing_token,
        now=now + timedelta(seconds=5),
    )
    reclaimed = repository.acquire(
        strategy=strategy,
        run_id="run_reclaimed",
        owner_id="worker_reclaimed",
        now=now + timedelta(seconds=31),
        ttl_seconds=30,
    )
    stale_first = repository.validate_active(
        strategy=strategy,
        owner_id="worker_first",
        fencing_token=first.lease.fencing_token,
        now=now + timedelta(seconds=32),
    )
    valid_reclaimed = repository.validate_active(
        strategy=strategy,
        owner_id="worker_reclaimed",
        fencing_token=reclaimed.lease.fencing_token,
        now=now + timedelta(seconds=32),
    )

    assert first.lease is not None
    assert reclaimed.lease is not None
    assert valid_first.valid is True
    assert valid_first.reason is None
    assert stale_first.valid is False
    assert stale_first.reason == "stale_live_decision_authority_token"
    assert stale_first.current_lease is not None
    assert stale_first.current_lease.fencing_token == reclaimed.lease.fencing_token
    assert valid_reclaimed.valid is True
