"""Compact live risk admission state for one-cycle live workers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.live_runtime import FAIR_VALUE_LIVE_STRATEGY
from alphadb.state.repository import OperationalStateRepository


DEFAULT_LIVE_RISK_STALE_SECONDS = 60
LIVE_RISK_ADMISSION_STATE_SCHEMA = "live_risk_admission_state.v1"
LIVE_RISK_ADMISSION_RESULT_SCHEMA = "live_risk_admission_result.v1"
UNRESOLVED_PENDING_RESERVATION_REASON = "unresolved_pending_reservation"
RiskAdmissionStatus = Literal["approved", "denied"]


@dataclass(frozen=True)
class LiveRiskAdmissionState:
    strategy: str
    live_risk_day: date
    daily_loss_used_dollars: float
    open_exposure_dollars: float
    pending_exposure_dollars: float
    per_market_exposure_dollars: Mapping[str, float]
    pending_reservations: Mapping[str, Mapping[str, Any]]
    updated_at: datetime
    version: int
    status: str = "active"
    metadata: Mapping[str, Any] | None = None

    @property
    def total_risk_used_dollars(self) -> float:
        return round(
            self.daily_loss_used_dollars
            + self.open_exposure_dollars
            + self.pending_exposure_dollars,
            6,
        )

    def market_exposure_dollars(self, market_ticker: str) -> float:
        return round(float(self.per_market_exposure_dollars.get(market_ticker, 0.0)), 6)

    def as_dict(self) -> dict[str, Any]:
        reason = state_status_reason(self)
        return {
            "schema_version": LIVE_RISK_ADMISSION_STATE_SCHEMA,
            "strategy": self.strategy,
            "live_risk_day": self.live_risk_day.isoformat(),
            "daily_loss_used_dollars": round(self.daily_loss_used_dollars, 6),
            "open_exposure_dollars": round(self.open_exposure_dollars, 6),
            "pending_exposure_dollars": round(self.pending_exposure_dollars, 6),
            "total_risk_used_dollars": self.total_risk_used_dollars,
            "per_market_exposure_dollars": dict(self.per_market_exposure_dollars),
            "pending_reservations": {
                key: dict(value) for key, value in self.pending_reservations.items()
            },
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "status": self.status,
            "reason": reason,
            "blocked_reason": reason if self.status == "blocked" else None,
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class LiveRiskAdmissionResult:
    status: RiskAdmissionStatus
    reason: str
    reservation_id: str | None = None
    market_ticker: str | None = None
    reserved_max_loss_dollars: float = 0.0
    daily_risk_used_before_dollars: float | None = None
    market_exposure_before_dollars: float | None = None
    state_version_before: int | None = None
    state_version_after: int | None = None
    state: LiveRiskAdmissionState | None = None
    message: str | None = None

    @property
    def approved(self) -> bool:
        return self.status == "approved"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LIVE_RISK_ADMISSION_RESULT_SCHEMA,
            "status": self.status,
            "reason": self.reason,
            "reservation_id": self.reservation_id,
            "market_ticker": self.market_ticker,
            "reserved_max_loss_dollars": round(self.reserved_max_loss_dollars, 6),
            "daily_risk_used_before_dollars": self.daily_risk_used_before_dollars,
            "market_exposure_before_dollars": self.market_exposure_before_dollars,
            "state_version_before": self.state_version_before,
            "state_version_after": self.state_version_after,
            "state": self.state.as_dict() if self.state else None,
            "message": self.message,
        }


class LiveRiskAdmissionRepository:
    """Postgres-backed, row-locked live order-admission state."""

    def __init__(self, database_url: str):
        self.database_url = database_url

    def upsert_state(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        live_risk_day: date,
        daily_loss_used_dollars: float = 0.0,
        open_exposure_dollars: float = 0.0,
        pending_exposure_dollars: float = 0.0,
        per_market_exposure_dollars: Mapping[str, float] | None = None,
        pending_reservations: Mapping[str, Mapping[str, Any]] | None = None,
        updated_at: datetime | None = None,
        status: str = "active",
        metadata: Mapping[str, Any] | None = None,
    ) -> LiveRiskAdmissionState:
        OperationalStateRepository(self.database_url).apply_migrations()
        observed_at = ensure_utc(updated_at or datetime.now(UTC))
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into live_risk_admission_states (
                        strategy,
                        live_risk_day,
                        daily_loss_used_dollars,
                        open_exposure_dollars,
                        pending_exposure_dollars,
                        per_market_exposure,
                        pending_reservations,
                        updated_at,
                        version,
                        status,
                        metadata
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
                    on conflict (strategy, live_risk_day) do update set
                        daily_loss_used_dollars = excluded.daily_loss_used_dollars,
                        open_exposure_dollars = excluded.open_exposure_dollars,
                        pending_exposure_dollars = excluded.pending_exposure_dollars,
                        per_market_exposure = excluded.per_market_exposure,
                        pending_reservations = excluded.pending_reservations,
                        updated_at = excluded.updated_at,
                        version = live_risk_admission_states.version + 1,
                        status = excluded.status,
                        metadata = excluded.metadata
                    returning *
                    """,
                    (
                        strategy,
                        live_risk_day,
                        round(daily_loss_used_dollars, 6),
                        round(open_exposure_dollars, 6),
                        round(pending_exposure_dollars, 6),
                        Jsonb(_float_mapping(per_market_exposure_dollars or {})),
                        Jsonb({key: dict(value) for key, value in (pending_reservations or {}).items()}),
                        observed_at,
                        status,
                        Jsonb(dict(metadata or {})),
                    ),
                )
                row = cursor.fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError("live risk admission state upsert returned no row")
        return state_from_row(row)

    def get_state(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        live_risk_day: date,
        apply_migrations: bool = True,
    ) -> LiveRiskAdmissionState | None:
        if apply_migrations:
            OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from live_risk_admission_states
                    where strategy = %s and live_risk_day = %s
                    """,
                    (strategy, live_risk_day),
                )
                row = cursor.fetchone()
        return None if row is None else state_from_row(row)

    def create_zero_state_if_missing(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        live_risk_day: date,
        updated_at: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[LiveRiskAdmissionState, bool]:
        OperationalStateRepository(self.database_url).apply_migrations()
        observed_at = ensure_utc(updated_at or datetime.now(UTC))
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into live_risk_admission_states (
                        strategy,
                        live_risk_day,
                        daily_loss_used_dollars,
                        open_exposure_dollars,
                        pending_exposure_dollars,
                        per_market_exposure,
                        pending_reservations,
                        updated_at,
                        version,
                        status,
                        metadata
                    )
                    values (%s, %s, 0, 0, 0, %s, %s, %s, 1, 'active', %s)
                    on conflict (strategy, live_risk_day) do nothing
                    returning *
                    """,
                    (
                        strategy,
                        live_risk_day,
                        Jsonb({}),
                        Jsonb({}),
                        observed_at,
                        Jsonb(dict(metadata or {})),
                    ),
                )
                row = cursor.fetchone()
                if row is not None:
                    connection.commit()
                    return state_from_row(row), True
                cursor.execute(
                    """
                    select *
                    from live_risk_admission_states
                    where strategy = %s and live_risk_day = %s
                    """,
                    (strategy, live_risk_day),
                )
                existing = cursor.fetchone()
            connection.commit()
        if existing is None:
            raise RuntimeError("live risk admission state bootstrap returned no row")
        return state_from_row(existing), False

    def admit_order(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        live_risk_day: date,
        market_ticker: str,
        max_loss_dollars: float,
        max_daily_loss_dollars: float,
        max_market_exposure_dollars: float,
        now: datetime | None = None,
        stale_after_seconds: int = DEFAULT_LIVE_RISK_STALE_SECONDS,
        reservation_id: str | None = None,
        run_id: str | None = None,
        reservation_metadata: Mapping[str, Any] | None = None,
    ) -> LiveRiskAdmissionResult:
        if max_loss_dollars <= 0:
            return denied("risk_state_inconsistent", market_ticker=market_ticker)
        OperationalStateRepository(self.database_url).apply_migrations()
        observed_at = ensure_utc(now or datetime.now(UTC))
        reservation_id = reservation_id or f"live_risk_res_{uuid4().hex[:12]}"
        try:
            with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    row = locked_state_row(
                        cursor,
                        strategy=strategy,
                        live_risk_day=live_risk_day,
                    )
                    if row is None:
                        connection.rollback()
                        return denied("risk_state_missing", market_ticker=market_ticker)
                    state = state_from_row(row)
                    invalid_reason = state_denial_reason(
                        state,
                        now=observed_at,
                        stale_after_seconds=stale_after_seconds,
                    )
                    if invalid_reason is not None:
                        connection.rollback()
                        return denied(
                            invalid_reason,
                            state=state,
                            market_ticker=market_ticker,
                        )
                    daily_before = state.total_risk_used_dollars
                    market_before = state.market_exposure_dollars(market_ticker)
                    if daily_before + max_loss_dollars > max_daily_loss_dollars:
                        connection.rollback()
                        return denied(
                            "daily_loss_cap_reached",
                            state=state,
                            market_ticker=market_ticker,
                            daily_risk_used_before_dollars=daily_before,
                            market_exposure_before_dollars=market_before,
                        )
                    if market_before + max_loss_dollars > max_market_exposure_dollars:
                        connection.rollback()
                        return denied(
                            "market_exposure_cap_reached",
                            state=state,
                            market_ticker=market_ticker,
                            daily_risk_used_before_dollars=daily_before,
                            market_exposure_before_dollars=market_before,
                        )
                    per_market = dict(state.per_market_exposure_dollars)
                    per_market[market_ticker] = round(market_before + max_loss_dollars, 6)
                    reservations = {
                        key: dict(value) for key, value in state.pending_reservations.items()
                    }
                    reservation = {
                        "reservation_id": reservation_id,
                        "market_ticker": market_ticker,
                        "max_loss_dollars": round(max_loss_dollars, 6),
                        "created_at": observed_at.isoformat(),
                        "run_id": run_id,
                    }
                    reservation.update(dict(reservation_metadata or {}))
                    reservations[reservation_id] = reservation
                    cursor.execute(
                        """
                        update live_risk_admission_states
                        set pending_exposure_dollars = %s,
                            per_market_exposure = %s,
                            pending_reservations = %s,
                            updated_at = %s,
                            version = version + 1
                        where strategy = %s
                          and live_risk_day = %s
                          and version = %s
                        returning *
                        """,
                        (
                            round(state.pending_exposure_dollars + max_loss_dollars, 6),
                            Jsonb(per_market),
                            Jsonb(reservations),
                            observed_at,
                            strategy,
                            live_risk_day,
                            state.version,
                        ),
                    )
                    updated = cursor.fetchone()
                    if updated is None:
                        connection.rollback()
                        return denied(
                            "risk_state_conflict",
                            state=state,
                            market_ticker=market_ticker,
                        )
                connection.commit()
            next_state = state_from_row(updated)
            return LiveRiskAdmissionResult(
                status="approved",
                reason="reserved",
                reservation_id=reservation_id,
                market_ticker=market_ticker,
                reserved_max_loss_dollars=round(max_loss_dollars, 6),
                daily_risk_used_before_dollars=daily_before,
                market_exposure_before_dollars=market_before,
                state_version_before=state.version,
                state_version_after=next_state.version,
                state=next_state,
            )
        except psycopg.errors.LockNotAvailable:
            return denied("risk_state_locked", market_ticker=market_ticker)
        except Exception as exc:
            return denied(
                "risk_state_unavailable",
                market_ticker=market_ticker,
                message=f"{type(exc).__name__}: {exc}",
            )

    def release_reservation(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        live_risk_day: date,
        reservation_id: str,
        now: datetime | None = None,
    ) -> LiveRiskAdmissionResult:
        return self._settle_reservation(
            strategy=strategy,
            live_risk_day=live_risk_day,
            reservation_id=reservation_id,
            filled_max_loss_dollars=0.0,
            reason="released",
            now=now,
        )

    def convert_reservation(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        live_risk_day: date,
        reservation_id: str,
        filled_max_loss_dollars: float,
        now: datetime | None = None,
    ) -> LiveRiskAdmissionResult:
        return self._settle_reservation(
            strategy=strategy,
            live_risk_day=live_risk_day,
            reservation_id=reservation_id,
            filled_max_loss_dollars=max(0.0, filled_max_loss_dollars),
            reason="converted_to_open_exposure",
            now=now,
        )

    def retain_reservation(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        live_risk_day: date,
        reservation_id: str,
        now: datetime | None = None,
    ) -> LiveRiskAdmissionResult:
        state = self.get_state(strategy=strategy, live_risk_day=live_risk_day)
        reservation = (state.pending_reservations if state else {}).get(reservation_id, {})
        return LiveRiskAdmissionResult(
            status="approved" if state and reservation else "denied",
            reason="reserved_until_reconciliation" if state and reservation else "risk_state_missing",
            reservation_id=reservation_id,
            market_ticker=str(reservation.get("market_ticker") or "") or None,
            reserved_max_loss_dollars=float(reservation.get("max_loss_dollars") or 0.0),
            state_version_after=state.version if state else None,
            state=state,
        )

    def claim_refresh(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        live_risk_day: date,
        now: datetime | None = None,
        run_id: str | None = None,
    ) -> LiveRiskAdmissionResult:
        OperationalStateRepository(self.database_url).apply_migrations()
        observed_at = ensure_utc(now or datetime.now(UTC))
        try:
            with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    row = locked_state_row(
                        cursor,
                        strategy=strategy,
                        live_risk_day=live_risk_day,
                    )
                    if row is None:
                        connection.rollback()
                        return denied("risk_state_missing")
                    state = state_from_row(row)
                    if state.status in {"locked", "reconciling"}:
                        connection.rollback()
                        return denied(state_status_reason(state) or "risk_state_locked", state=state)
                    metadata = dict(state.metadata or {})
                    metadata["refresh_claim"] = {
                        "run_id": run_id,
                        "claimed_at": observed_at.isoformat(),
                        "previous_status": state.status,
                        "previous_version": state.version,
                    }
                    cursor.execute(
                        """
                        update live_risk_admission_states
                        set status = 'reconciling',
                            metadata = %s,
                            version = version + 1
                        where strategy = %s
                          and live_risk_day = %s
                          and version = %s
                        returning *
                        """,
                        (
                            Jsonb(metadata),
                            strategy,
                            live_risk_day,
                            state.version,
                        ),
                    )
                    updated = cursor.fetchone()
                    if updated is None:
                        connection.rollback()
                        return denied("risk_state_conflict", state=state)
                connection.commit()
            next_state = state_from_row(updated)
            return LiveRiskAdmissionResult(
                status="approved",
                reason="refresh_claimed",
                state_version_before=state.version,
                state_version_after=next_state.version,
                state=next_state,
            )
        except psycopg.errors.LockNotAvailable:
            return denied("risk_state_locked")
        except Exception as exc:
            return denied("risk_state_unavailable", message=f"{type(exc).__name__}: {exc}")

    def complete_refresh(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        live_risk_day: date,
        expected_version: int,
        resolutions: Sequence[Mapping[str, Any]],
        now: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> LiveRiskAdmissionResult:
        OperationalStateRepository(self.database_url).apply_migrations()
        observed_at = ensure_utc(now or datetime.now(UTC))
        try:
            with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    row = locked_state_row(
                        cursor,
                        strategy=strategy,
                        live_risk_day=live_risk_day,
                    )
                    if row is None:
                        connection.rollback()
                        return denied("risk_state_missing")
                    state = state_from_row(row)
                    if state.version != expected_version or state.status != "reconciling":
                        connection.rollback()
                        return denied("risk_state_conflict", state=state)
                    next_state_values = refreshed_state_values(state, resolutions)
                    refresh_blocks = any(
                        str(resolution.get("action") or "") in {"block", "preserve"}
                        for resolution in resolutions
                    )
                    next_status = "blocked" if refresh_blocks else "active"
                    next_metadata = dict(state.metadata or {})
                    next_metadata.update(dict(metadata or {}))
                    next_metadata["last_refresh_completed_at"] = observed_at.isoformat()
                    if refresh_blocks:
                        next_metadata["blocked_reason"] = UNRESOLVED_PENDING_RESERVATION_REASON
                    else:
                        next_metadata.pop("blocked_reason", None)
                    cursor.execute(
                        """
                        update live_risk_admission_states
                        set open_exposure_dollars = %s,
                            pending_exposure_dollars = %s,
                            per_market_exposure = %s,
                            pending_reservations = %s,
                            updated_at = %s,
                            status = %s,
                            metadata = %s,
                            version = version + 1
                        where strategy = %s
                          and live_risk_day = %s
                          and version = %s
                        returning *
                        """,
                        (
                            round(next_state_values["open_exposure_dollars"], 6),
                            round(next_state_values["pending_exposure_dollars"], 6),
                            Jsonb(next_state_values["per_market_exposure"]),
                            Jsonb(next_state_values["pending_reservations"]),
                            observed_at,
                            next_status,
                            Jsonb(next_metadata),
                            strategy,
                            live_risk_day,
                            state.version,
                        ),
                    )
                    updated = cursor.fetchone()
                    if updated is None:
                        connection.rollback()
                        return denied("risk_state_conflict", state=state)
                connection.commit()
            next_state = state_from_row(updated)
            return LiveRiskAdmissionResult(
                status="approved",
                reason="refresh_blocked" if refresh_blocks else "refresh_active",
                state_version_before=state.version,
                state_version_after=next_state.version,
                state=next_state,
            )
        except psycopg.errors.LockNotAvailable:
            return denied("risk_state_locked")
        except Exception as exc:
            return denied("risk_state_unavailable", message=f"{type(exc).__name__}: {exc}")

    def _settle_reservation(
        self,
        *,
        strategy: str,
        live_risk_day: date,
        reservation_id: str,
        filled_max_loss_dollars: float,
        reason: str,
        now: datetime | None,
    ) -> LiveRiskAdmissionResult:
        OperationalStateRepository(self.database_url).apply_migrations()
        observed_at = ensure_utc(now or datetime.now(UTC))
        try:
            with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    row = locked_state_row(
                        cursor,
                        strategy=strategy,
                        live_risk_day=live_risk_day,
                    )
                    if row is None:
                        connection.rollback()
                        return denied("risk_state_missing", reservation_id=reservation_id)
                    state = state_from_row(row)
                    reservations = {
                        key: dict(value) for key, value in state.pending_reservations.items()
                    }
                    reservation = reservations.pop(reservation_id, None)
                    if not reservation:
                        connection.rollback()
                        return denied(
                            "risk_state_conflict",
                            state=state,
                            reservation_id=reservation_id,
                        )
                    market_ticker = str(reservation.get("market_ticker") or "")
                    reserved = float(reservation.get("max_loss_dollars") or 0.0)
                    next_pending = max(0.0, state.pending_exposure_dollars - reserved)
                    next_open = state.open_exposure_dollars + filled_max_loss_dollars
                    per_market = dict(state.per_market_exposure_dollars)
                    per_market[market_ticker] = round(
                        max(
                            0.0,
                            float(per_market.get(market_ticker, 0.0))
                            - reserved
                            + filled_max_loss_dollars,
                        ),
                        6,
                    )
                    if per_market[market_ticker] == 0.0:
                        per_market.pop(market_ticker, None)
                    cursor.execute(
                        """
                        update live_risk_admission_states
                        set open_exposure_dollars = %s,
                            pending_exposure_dollars = %s,
                            per_market_exposure = %s,
                            pending_reservations = %s,
                            updated_at = %s,
                            version = version + 1
                        where strategy = %s
                          and live_risk_day = %s
                          and version = %s
                        returning *
                        """,
                        (
                            round(next_open, 6),
                            round(next_pending, 6),
                            Jsonb(per_market),
                            Jsonb(reservations),
                            observed_at,
                            strategy,
                            live_risk_day,
                            state.version,
                        ),
                    )
                    updated = cursor.fetchone()
                    if updated is None:
                        connection.rollback()
                        return denied(
                            "risk_state_conflict",
                            state=state,
                            reservation_id=reservation_id,
                            market_ticker=market_ticker,
                        )
                connection.commit()
            next_state = state_from_row(updated)
            return LiveRiskAdmissionResult(
                status="approved",
                reason=reason,
                reservation_id=reservation_id,
                market_ticker=market_ticker,
                reserved_max_loss_dollars=round(reserved, 6),
                state_version_before=state.version,
                state_version_after=next_state.version,
                state=next_state,
            )
        except psycopg.errors.LockNotAvailable:
            return denied("risk_state_locked", reservation_id=reservation_id)
        except Exception as exc:
            return denied(
                "risk_state_unavailable",
                reservation_id=reservation_id,
                message=f"{type(exc).__name__}: {exc}",
            )


def locked_state_row(
    cursor: psycopg.Cursor,
    *,
    strategy: str,
    live_risk_day: date,
) -> Mapping[str, Any] | None:
    cursor.execute(
        """
        select *
        from live_risk_admission_states
        where strategy = %s and live_risk_day = %s
        for update nowait
        """,
        (strategy, live_risk_day),
    )
    return cursor.fetchone()


def state_denial_reason(
    state: LiveRiskAdmissionState,
    *,
    now: datetime,
    stale_after_seconds: int,
) -> str | None:
    if state.status != "active":
        return state_status_reason(state) or f"risk_state_{state.status}"
    if state.updated_at < ensure_utc(now) - timedelta(seconds=stale_after_seconds):
        return "risk_state_stale"
    if state.version < 1:
        return "risk_state_inconsistent"
    values = (
        state.daily_loss_used_dollars,
        state.open_exposure_dollars,
        state.pending_exposure_dollars,
        *state.per_market_exposure_dollars.values(),
    )
    if any(value < 0 for value in values):
        return "risk_state_inconsistent"
    return None


def state_status_reason(state: LiveRiskAdmissionState) -> str | None:
    metadata = dict(state.metadata or {})
    if state.status == "active":
        return None
    if state.status == "blocked":
        reason = metadata.get("blocked_reason") or metadata.get("reason")
        return str(reason or UNRESOLVED_PENDING_RESERVATION_REASON)
    if state.status == "locked":
        return "risk_state_locked"
    if state.status == "stale":
        return "risk_state_stale"
    if state.status == "reconciling":
        return "risk_state_reconciling"
    return f"risk_state_{state.status}"


def refreshed_state_values(
    state: LiveRiskAdmissionState,
    resolutions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    reservations = {
        key: dict(value) for key, value in state.pending_reservations.items()
    }
    per_market = dict(state.per_market_exposure_dollars)
    pending_exposure = state.pending_exposure_dollars
    open_exposure = state.open_exposure_dollars
    for resolution in resolutions:
        action = str(resolution.get("action") or "")
        if action not in {"release", "convert"}:
            continue
        reservation_id = str(resolution.get("reservation_id") or "")
        reservation = reservations.pop(reservation_id, None)
        if not reservation:
            continue
        market_ticker = str(reservation.get("market_ticker") or "")
        reserved = _float(reservation.get("max_loss_dollars"))
        converted = _float(resolution.get("convert_max_loss_dollars"))
        pending_exposure = max(0.0, pending_exposure - reserved)
        open_exposure = round(open_exposure + converted, 6)
        if market_ticker:
            per_market[market_ticker] = round(
                max(0.0, _float(per_market.get(market_ticker)) - reserved + converted),
                6,
            )
            if per_market[market_ticker] == 0.0:
                per_market.pop(market_ticker, None)
    return {
        "open_exposure_dollars": round(open_exposure, 6),
        "pending_exposure_dollars": round(pending_exposure, 6),
        "per_market_exposure": per_market,
        "pending_reservations": reservations,
    }


def denied(
    reason: str,
    *,
    state: LiveRiskAdmissionState | None = None,
    reservation_id: str | None = None,
    market_ticker: str | None = None,
    daily_risk_used_before_dollars: float | None = None,
    market_exposure_before_dollars: float | None = None,
    message: str | None = None,
) -> LiveRiskAdmissionResult:
    return LiveRiskAdmissionResult(
        status="denied",
        reason=reason,
        reservation_id=reservation_id,
        market_ticker=market_ticker,
        daily_risk_used_before_dollars=daily_risk_used_before_dollars,
        market_exposure_before_dollars=market_exposure_before_dollars,
        state_version_before=state.version if state else None,
        state=state,
        message=message,
    )


def state_from_row(row: Mapping[str, Any]) -> LiveRiskAdmissionState:
    return LiveRiskAdmissionState(
        strategy=str(row["strategy"]),
        live_risk_day=_date(row["live_risk_day"]),
        daily_loss_used_dollars=_float(row["daily_loss_used_dollars"]),
        open_exposure_dollars=_float(row["open_exposure_dollars"]),
        pending_exposure_dollars=_float(row["pending_exposure_dollars"]),
        per_market_exposure_dollars=_float_mapping(row["per_market_exposure"]),
        pending_reservations=_reservations(row["pending_reservations"]),
        updated_at=ensure_utc(row["updated_at"]),
        version=int(row["version"]),
        status=str(row["status"]),
        metadata=dict(row["metadata"] or {}),
    )


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value)).date()


def _float(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0.0)


def _float_mapping(value: Mapping[str, Any] | Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): round(_float(item), 6) for key, item in value.items()}


def _reservations(value: Mapping[str, Any] | Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): dict(item)
        for key, item in value.items()
        if isinstance(item, Mapping)
    }
