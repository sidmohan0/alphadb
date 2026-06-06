from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from alphadb.config import settings_from_env
from alphadb.live_risk import LiveRiskAdmissionRepository
from alphadb.state.repository import OperationalStateRepository


def repository_or_skip() -> LiveRiskAdmissionRepository:
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


def test_live_risk_admission_reserves_releases_and_converts_pending_exposure() -> None:
    repository = repository_or_skip()
    strategy = f"test_strategy_{uuid4().hex[:8]}"
    risk_day = date(2026, 6, 4)
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    repository.upsert_state(strategy=strategy, live_risk_day=risk_day, updated_at=now)

    reserved = repository.admit_order(
        strategy=strategy,
        live_risk_day=risk_day,
        market_ticker="KXBTC15M-RISK",
        max_loss_dollars=0.5,
        max_daily_loss_dollars=10.0,
        max_market_exposure_dollars=2.0,
        now=now,
        reservation_id="res_release",
    )
    released = repository.release_reservation(
        strategy=strategy,
        live_risk_day=risk_day,
        reservation_id="res_release",
        now=now + timedelta(seconds=1),
    )
    converted_reservation = repository.admit_order(
        strategy=strategy,
        live_risk_day=risk_day,
        market_ticker="KXBTC15M-RISK",
        max_loss_dollars=0.5,
        max_daily_loss_dollars=10.0,
        max_market_exposure_dollars=2.0,
        now=now + timedelta(seconds=2),
        reservation_id="res_fill",
    )
    converted = repository.convert_reservation(
        strategy=strategy,
        live_risk_day=risk_day,
        reservation_id="res_fill",
        filled_max_loss_dollars=0.25,
        now=now + timedelta(seconds=3),
    )
    state = repository.get_state(strategy=strategy, live_risk_day=risk_day)

    assert reserved.approved is True
    assert reserved.state.pending_exposure_dollars == 0.5
    assert released.approved is True
    assert released.state.pending_exposure_dollars == 0.0
    assert converted_reservation.approved is True
    assert converted.approved is True
    assert state is not None
    assert state.pending_exposure_dollars == 0.0
    assert state.open_exposure_dollars == 0.25
    assert state.market_exposure_dollars("KXBTC15M-RISK") == 0.25


def test_live_risk_admission_retains_unknown_response_until_reconciliation() -> None:
    repository = repository_or_skip()
    strategy = f"test_strategy_{uuid4().hex[:8]}"
    risk_day = date(2026, 6, 4)
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    repository.upsert_state(strategy=strategy, live_risk_day=risk_day, updated_at=now)
    reserved = repository.admit_order(
        strategy=strategy,
        live_risk_day=risk_day,
        market_ticker="KXBTC15M-UNKNOWN",
        max_loss_dollars=0.75,
        max_daily_loss_dollars=10.0,
        max_market_exposure_dollars=2.0,
        now=now,
        reservation_id="res_unknown",
    )
    retained = repository.retain_reservation(
        strategy=strategy,
        live_risk_day=risk_day,
        reservation_id="res_unknown",
        now=now + timedelta(seconds=1),
    )

    assert reserved.approved is True
    assert retained.approved is True
    assert retained.reason == "reserved_until_reconciliation"
    assert retained.state.pending_exposure_dollars == 0.75


def test_live_risk_admission_fails_closed_for_missing_stale_locked_and_caps() -> None:
    repository = repository_or_skip()
    strategy = f"test_strategy_{uuid4().hex[:8]}"
    risk_day = date(2026, 6, 4)
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)

    missing = repository.admit_order(
        strategy=strategy,
        live_risk_day=risk_day,
        market_ticker="KXBTC15M-MISSING",
        max_loss_dollars=0.5,
        max_daily_loss_dollars=10.0,
        max_market_exposure_dollars=2.0,
        now=now,
    )
    repository.upsert_state(
        strategy=strategy,
        live_risk_day=risk_day,
        updated_at=now - timedelta(minutes=5),
    )
    stale = repository.admit_order(
        strategy=strategy,
        live_risk_day=risk_day,
        market_ticker="KXBTC15M-STALE",
        max_loss_dollars=0.5,
        max_daily_loss_dollars=10.0,
        max_market_exposure_dollars=2.0,
        now=now,
    )
    repository.upsert_state(
        strategy=strategy,
        live_risk_day=risk_day,
        daily_loss_used_dollars=9.75,
        updated_at=now,
        status="locked",
    )
    locked = repository.admit_order(
        strategy=strategy,
        live_risk_day=risk_day,
        market_ticker="KXBTC15M-LOCKED",
        max_loss_dollars=0.5,
        max_daily_loss_dollars=10.0,
        max_market_exposure_dollars=2.0,
        now=now,
    )
    repository.upsert_state(
        strategy=strategy,
        live_risk_day=risk_day,
        daily_loss_used_dollars=9.75,
        updated_at=now,
    )
    cap = repository.admit_order(
        strategy=strategy,
        live_risk_day=risk_day,
        market_ticker="KXBTC15M-CAP",
        max_loss_dollars=0.5,
        max_daily_loss_dollars=10.0,
        max_market_exposure_dollars=2.0,
        now=now,
    )

    assert missing.reason == "risk_state_missing"
    assert stale.reason == "risk_state_stale"
    assert locked.reason == "risk_state_locked"
    assert cap.reason == "daily_loss_cap_reached"
