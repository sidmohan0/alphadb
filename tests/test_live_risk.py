from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from alphadb.config import settings_from_env
from alphadb.live_risk import LiveRiskAdmissionRepository, LiveRiskAdmissionState
from alphadb.model_evaluation.fair_value_live_job import live_risk_accounting_report
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


def test_live_risk_daily_loss_cap_uses_realized_loss_not_existing_exposure() -> None:
    repository = repository_or_skip()
    strategy = f"test_strategy_{uuid4().hex[:8]}"
    risk_day = date(2026, 6, 4)
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    repository.upsert_state(
        strategy=strategy,
        live_risk_day=risk_day,
        daily_loss_used_dollars=1.0,
        open_exposure_dollars=8.0,
        per_market_exposure_dollars={"KXBTC15M-OPEN": 8.0},
        updated_at=now,
    )

    reserved = repository.admit_order(
        strategy=strategy,
        live_risk_day=risk_day,
        market_ticker="KXBTC15M-NEW",
        max_loss_dollars=1.0,
        max_daily_loss_dollars=5.0,
        max_market_exposure_dollars=10.0,
        now=now,
        reservation_id="res_daily_loss_is_realized",
    )

    assert reserved.approved is True
    assert reserved.daily_risk_used_before_dollars == 1.0
    assert reserved.state is not None
    assert reserved.state.daily_loss_used_dollars == 1.0
    assert reserved.state.open_exposure_dollars == 8.0
    assert reserved.state.pending_exposure_dollars == 1.0


def test_live_risk_accounting_reports_realized_daily_loss_separately_from_exposure() -> None:
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    state = LiveRiskAdmissionState(
        strategy="fair_value_live",
        live_risk_day=date(2026, 6, 4),
        daily_loss_used_dollars=1.25,
        open_exposure_dollars=8.0,
        pending_exposure_dollars=0.75,
        per_market_exposure_dollars={"KXBTC15M-OPEN": 8.0, "KXBTC15M-PENDING": 0.75},
        pending_reservations={},
        updated_at=now,
        version=1,
    )

    report = live_risk_accounting_report(
        state,
        generated_at=now,
        live_risk_timezone="America/Los_Angeles",
    )

    assert report["daily_loss_realized_dollars"] == 1.25
    assert report["daily_loss_used_dollars"] == 1.25
    assert report["open_exposure_dollars"] == 8.0
    assert report["pending_exposure_dollars"] == 0.75


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


def test_live_risk_admission_persists_blocked_reason_and_denies_non_active_states() -> None:
    repository = repository_or_skip()
    strategy = f"test_strategy_{uuid4().hex[:8]}"
    risk_day = date(2026, 6, 4)
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)

    blocked_state = repository.upsert_state(
        strategy=strategy,
        live_risk_day=risk_day,
        updated_at=now,
        status="blocked",
        metadata={"blocked_reason": "unresolved_pending_reservation"},
    )
    blocked = repository.admit_order(
        strategy=strategy,
        live_risk_day=risk_day,
        market_ticker="KXBTC15M-BLOCKED",
        max_loss_dollars=0.5,
        max_daily_loss_dollars=10.0,
        max_market_exposure_dollars=2.0,
        now=now,
    )
    stale_status = repository.upsert_state(
        strategy=strategy,
        live_risk_day=risk_day,
        updated_at=now,
        status="stale",
    )
    stale = repository.admit_order(
        strategy=strategy,
        live_risk_day=risk_day,
        market_ticker="KXBTC15M-STALE-STATUS",
        max_loss_dollars=0.5,
        max_daily_loss_dollars=10.0,
        max_market_exposure_dollars=2.0,
        now=now,
    )
    repository.upsert_state(
        strategy=strategy,
        live_risk_day=risk_day,
        updated_at=now,
        status="reconciling",
    )
    reconciling = repository.admit_order(
        strategy=strategy,
        live_risk_day=risk_day,
        market_ticker="KXBTC15M-RECONCILING",
        max_loss_dollars=0.5,
        max_daily_loss_dollars=10.0,
        max_market_exposure_dollars=2.0,
        now=now,
    )

    assert blocked_state.status == "blocked"
    assert blocked_state.as_dict()["blocked_reason"] == "unresolved_pending_reservation"
    assert blocked.status == "denied"
    assert blocked.reason == "unresolved_pending_reservation"
    assert blocked.state.as_dict()["reason"] == "unresolved_pending_reservation"
    assert stale_status.as_dict()["reason"] == "risk_state_stale"
    assert stale.reason == "risk_state_stale"
    assert reconciling.reason == "risk_state_reconciling"


def test_live_risk_refresh_claim_serializes_admission_and_version_conflicts() -> None:
    repository = repository_or_skip()
    strategy = f"test_strategy_{uuid4().hex[:8]}"
    risk_day = date(2026, 6, 4)
    now = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
    repository.upsert_state(strategy=strategy, live_risk_day=risk_day, updated_at=now)

    claim = repository.claim_refresh(
        strategy=strategy,
        live_risk_day=risk_day,
        now=now,
        run_id="run_refresh_claim",
    )
    denied_during_refresh = repository.admit_order(
        strategy=strategy,
        live_risk_day=risk_day,
        market_ticker="KXBTC15M-REFRESH-LOCK",
        max_loss_dollars=0.5,
        max_daily_loss_dollars=10.0,
        max_market_exposure_dollars=2.0,
        now=now,
    )
    conflict = repository.complete_refresh(
        strategy=strategy,
        live_risk_day=risk_day,
        expected_version=claim.state_version_after - 1,
        resolutions=[],
        now=now,
    )
    completed = repository.complete_refresh(
        strategy=strategy,
        live_risk_day=risk_day,
        expected_version=claim.state_version_after,
        resolutions=[],
        now=now,
    )

    assert claim.approved is True
    assert claim.state.status == "reconciling"
    assert denied_during_refresh.status == "denied"
    assert denied_during_refresh.reason == "risk_state_reconciling"
    assert conflict.status == "denied"
    assert conflict.reason == "risk_state_conflict"
    assert completed.approved is True
    assert completed.reason == "refresh_active"
    assert completed.state.status == "active"
