"""Postgres-backed live-decision authority leases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.live_runtime import FAIR_VALUE_LIVE_STRATEGY
from alphadb.state.repository import OperationalStateRepository


LIVE_DECISION_AUTHORITY_LEASE_SCHEMA = "alphadb_live_decision_authority_lease.v1"
LIVE_DECISION_AUTHORITY_RESULT_SCHEMA = "alphadb_live_decision_authority_result.v1"
AuthorityAcquireStatus = Literal["acquired", "held"]
AuthorityReleaseStatus = Literal["released", "stale"]
AuthorityValidationStatus = Literal["validated", "stale"]


@dataclass(frozen=True)
class LiveDecisionAuthorityLease:
    strategy: str
    run_id: str
    owner_id: str
    fencing_token: int
    acquired_at: datetime
    expires_at: datetime
    released_at: datetime | None
    status: str
    metadata: Mapping[str, Any]

    @property
    def active(self) -> bool:
        return self.status == "active" and self.released_at is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LIVE_DECISION_AUTHORITY_LEASE_SCHEMA,
            "backend": "postgres",
            "strategy": self.strategy,
            "run_id": self.run_id,
            "owner_id": self.owner_id,
            "fencing_token": self.fencing_token,
            "token": str(self.fencing_token),
            "acquired_at": self.acquired_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "released_at": self.released_at.isoformat() if self.released_at else None,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class LiveDecisionAuthorityAcquireResult:
    status: AuthorityAcquireStatus
    lease: LiveDecisionAuthorityLease | None
    current_lease: LiveDecisionAuthorityLease | None = None
    reason: str | None = None

    @property
    def acquired(self) -> bool:
        return self.status == "acquired"

    def as_dict(self) -> dict[str, Any]:
        lease = self.lease or self.current_lease
        return {
            "schema_version": LIVE_DECISION_AUTHORITY_RESULT_SCHEMA,
            "backend": "postgres",
            "acquired": self.acquired,
            "status": self.status,
            "reason": self.reason,
            "lease": lease.as_dict() if lease else None,
        }


@dataclass(frozen=True)
class LiveDecisionAuthorityReleaseResult:
    status: AuthorityReleaseStatus
    lease: LiveDecisionAuthorityLease | None
    current_lease: LiveDecisionAuthorityLease | None = None
    reason: str | None = None

    @property
    def released(self) -> bool:
        return self.status == "released"

    def as_dict(self) -> dict[str, Any]:
        lease = self.lease or self.current_lease
        return {
            "schema_version": LIVE_DECISION_AUTHORITY_RESULT_SCHEMA,
            "backend": "postgres",
            "released": self.released,
            "status": self.status,
            "reason": self.reason,
            "lease": lease.as_dict() if lease else None,
        }


@dataclass(frozen=True)
class LiveDecisionAuthorityValidationResult:
    status: AuthorityValidationStatus
    lease: LiveDecisionAuthorityLease | None = None
    current_lease: LiveDecisionAuthorityLease | None = None
    reason: str | None = None

    @property
    def valid(self) -> bool:
        return self.status == "validated"

    def as_dict(self) -> dict[str, Any]:
        lease = self.lease or self.current_lease
        return {
            "schema_version": LIVE_DECISION_AUTHORITY_RESULT_SCHEMA,
            "backend": "postgres",
            "valid": self.valid,
            "status": self.status,
            "reason": self.reason,
            "lease": lease.as_dict() if lease else None,
        }


class LiveDecisionAuthorityLeaseRepository:
    """Strategy-scoped Postgres authority lease with fencing tokens."""

    def __init__(self, database_url: str):
        self.database_url = database_url

    def acquire(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        run_id: str,
        owner_id: str,
        now: datetime | None = None,
        ttl_seconds: int = 180,
        metadata: Mapping[str, Any] | None = None,
    ) -> LiveDecisionAuthorityAcquireResult:
        OperationalStateRepository(self.database_url).apply_migrations()
        acquired_at = ensure_utc(now or datetime.now(UTC))
        expires_at = acquired_at + timedelta(seconds=ttl_seconds)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into live_decision_authority_leases (
                        strategy,
                        run_id,
                        owner_id,
                        fencing_token,
                        acquired_at,
                        expires_at,
                        released_at,
                        status,
                        metadata,
                        updated_at
                    )
                    values (%s, %s, %s, 1, %s, %s, null, 'active', %s, %s)
                    on conflict (strategy) do update set
                        run_id = excluded.run_id,
                        owner_id = excluded.owner_id,
                        fencing_token = live_decision_authority_leases.fencing_token + 1,
                        acquired_at = excluded.acquired_at,
                        expires_at = excluded.expires_at,
                        released_at = null,
                        status = 'active',
                        metadata = excluded.metadata,
                        updated_at = excluded.updated_at
                    where live_decision_authority_leases.status = 'released'
                        or live_decision_authority_leases.released_at is not null
                        or live_decision_authority_leases.expires_at <= %s
                    returning *
                    """,
                    (
                        strategy,
                        run_id,
                        owner_id,
                        acquired_at,
                        expires_at,
                        Jsonb(dict(metadata or {})),
                        acquired_at,
                        acquired_at,
                    ),
                )
                row = cursor.fetchone()
                if row is not None:
                    connection.commit()
                    return LiveDecisionAuthorityAcquireResult(
                        status="acquired",
                        lease=lease_from_row(row),
                    )
                cursor.execute(
                    """
                    select *
                    from live_decision_authority_leases
                    where strategy = %s
                    """,
                    (strategy,),
                )
                current = cursor.fetchone()
            connection.commit()
        return LiveDecisionAuthorityAcquireResult(
            status="held",
            lease=None,
            current_lease=lease_from_row(current) if current else None,
            reason="live_decision_authority_held",
        )

    def get(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        apply_migrations: bool = True,
    ) -> LiveDecisionAuthorityLease | None:
        if apply_migrations:
            OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from live_decision_authority_leases
                    where strategy = %s
                    """,
                    (strategy,),
                )
                row = cursor.fetchone()
        return lease_from_row(row) if row else None

    def release(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        owner_id: str,
        fencing_token: int,
        now: datetime | None = None,
    ) -> LiveDecisionAuthorityReleaseResult:
        OperationalStateRepository(self.database_url).apply_migrations()
        released_at = ensure_utc(now or datetime.now(UTC))
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update live_decision_authority_leases
                    set released_at = %s,
                        status = 'released',
                        updated_at = %s
                    where strategy = %s
                        and owner_id = %s
                        and fencing_token = %s
                        and status = 'active'
                        and released_at is null
                    returning *
                    """,
                    (released_at, released_at, strategy, owner_id, fencing_token),
                )
                row = cursor.fetchone()
                if row is not None:
                    connection.commit()
                    return LiveDecisionAuthorityReleaseResult(
                        status="released",
                        lease=lease_from_row(row),
                    )
                cursor.execute(
                    """
                    select *
                    from live_decision_authority_leases
                    where strategy = %s
                    """,
                    (strategy,),
                )
                current = cursor.fetchone()
            connection.commit()
        return LiveDecisionAuthorityReleaseResult(
            status="stale",
            lease=None,
            current_lease=lease_from_row(current) if current else None,
            reason="stale_live_decision_authority_token",
        )

    def validate_active(
        self,
        *,
        strategy: str = FAIR_VALUE_LIVE_STRATEGY,
        owner_id: str,
        fencing_token: int,
        now: datetime | None = None,
    ) -> LiveDecisionAuthorityValidationResult:
        OperationalStateRepository(self.database_url).apply_migrations()
        observed_at = ensure_utc(now or datetime.now(UTC))
        current = self.get(strategy=strategy, apply_migrations=False)
        if (
            current is not None
            and current.owner_id == owner_id
            and current.fencing_token == fencing_token
            and current.status == "active"
            and current.released_at is None
            and current.expires_at > observed_at
        ):
            return LiveDecisionAuthorityValidationResult(
                status="validated",
                lease=current,
            )
        return LiveDecisionAuthorityValidationResult(
            status="stale",
            lease=None,
            current_lease=current,
            reason="stale_live_decision_authority_token",
        )


def lease_from_row(row: Mapping[str, Any]) -> LiveDecisionAuthorityLease:
    return LiveDecisionAuthorityLease(
        strategy=str(row["strategy"]),
        run_id=str(row["run_id"]),
        owner_id=str(row["owner_id"]),
        fencing_token=int(row["fencing_token"]),
        acquired_at=ensure_utc(row["acquired_at"]),
        expires_at=ensure_utc(row["expires_at"]),
        released_at=ensure_utc(row["released_at"]) if row.get("released_at") else None,
        status=str(row["status"]),
        metadata=dict(row.get("metadata") or {}),
    )


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
