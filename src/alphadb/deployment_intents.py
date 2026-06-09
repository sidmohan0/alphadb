"""Deployment intent records for Cockpit-driven AWS deployment control."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.state.repository import OperationalStateRepository

DEPLOYMENT_INTENT_SCHEMA_VERSION = "alphadb.deployment_intent.v1"
DEFAULT_DEPLOYMENT_PROFILE_PATH = "deploy/aws/deployment-profile.example.yaml"
INTENT_STATUSES = {"pending", "planning", "planned", "failed", "canceled"}
FINAL_INTENT_STATUSES = {"planned", "failed", "canceled"}
CREATE_INTENT_FIELDS = {
    "actor",
    "source",
    "reason",
    "profile_path",
    "profile_reference",
    "surfaces",
    "requested_surfaces",
    "build_policy",
    "schedule_policy",
    "live_authority",
    "confirmation",
    "image_identities",
    "rollback_pointers",
    "metadata",
}
FORBIDDEN_SECRET_KEYS = {
    "aws_access_key_id",
    "aws_secret_access_key",
    "aws_session_token",
    "database_url",
    "kalshi_api_key_id",
    "kalshi_private_key_pem",
    "password",
    "private_key",
    "secret_value",
}
PRIVATE_KEY_HEADER_PREFIX = "-----BEGIN "
PRIVATE_KEY_HEADER_SUFFIX = "PRIVATE KEY-----"
FORBIDDEN_SECRET_STRINGS = (
    f"{PRIVATE_KEY_HEADER_PREFIX}{PRIVATE_KEY_HEADER_SUFFIX}",
    f"{PRIVATE_KEY_HEADER_PREFIX}RSA {PRIVATE_KEY_HEADER_SUFFIX}",
    "postgresql://",
    "AWS_SECRET_ACCESS_KEY",
)


@dataclass(frozen=True)
class DeploymentIntent:
    deployment_intent_id: str
    status: str
    actor: str
    source: str
    reason: str
    profile_path: str
    requested_surfaces: tuple[str, ...]
    build_policy: dict[str, Any]
    schedule_policy: dict[str, Any]
    live_authority: dict[str, Any]
    confirmation: dict[str, Any]
    image_identities: dict[str, Any]
    evidence: dict[str, Any]
    rollback_pointers: dict[str, Any]
    metadata: dict[str, Any]
    error: dict[str, Any]
    claimed_by: str | None
    created_at: datetime
    updated_at: datetime
    claimed_at: datetime | None
    completed_at: datetime | None
    canceled_at: datetime | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DEPLOYMENT_INTENT_SCHEMA_VERSION,
            "deployment_intent_id": self.deployment_intent_id,
            "status": self.status,
            "actor": self.actor,
            "source": self.source,
            "reason": self.reason,
            "profile_path": self.profile_path,
            "requested_surfaces": list(self.requested_surfaces),
            "build_policy": self.build_policy,
            "schedule_policy": self.schedule_policy,
            "live_authority": self.live_authority,
            "confirmation": self.confirmation,
            "image_identities": self.image_identities,
            "evidence": self.evidence,
            "rollback_pointers": self.rollback_pointers,
            "metadata": self.metadata,
            "error": self.error,
            "claimed_by": self.claimed_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "claimed_at": self.claimed_at.isoformat() if self.claimed_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "canceled_at": self.canceled_at.isoformat() if self.canceled_at else None,
        }


class DeploymentIntentRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def apply_migrations(self) -> list[str]:
        return OperationalStateRepository(self.database_url).apply_migrations()

    def create_intent(
        self,
        *,
        actor: str,
        reason: str,
        requested_surfaces: Sequence[str],
        source: str = "cockpit",
        profile_path: str = DEFAULT_DEPLOYMENT_PROFILE_PATH,
        build_policy: Mapping[str, Any] | None = None,
        schedule_policy: Mapping[str, Any] | None = None,
        live_authority: Mapping[str, Any] | None = None,
        confirmation: Mapping[str, Any] | None = None,
        image_identities: Mapping[str, Any] | None = None,
        rollback_pointers: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        deployment_intent_id: str | None = None,
    ) -> DeploymentIntent:
        actor = _required_text(actor, "actor")
        reason = _required_text(reason, "reason")
        source = _required_text(source, "source")
        profile_path = _required_text(profile_path, "profile_path")
        surfaces = _surface_tuple(requested_surfaces)
        confirmation_payload = dict(confirmation or {})
        if confirmation_payload.get("confirmed") is not True:
            raise ValueError("deployment intent requires confirmation.confirmed=true")
        payloads = {
            "build_policy": dict(build_policy or {}),
            "schedule_policy": dict(schedule_policy or {}),
            "live_authority": dict(live_authority or {}),
            "confirmation": confirmation_payload,
            "image_identities": dict(image_identities or {}),
            "rollback_pointers": dict(rollback_pointers or {}),
            "metadata": dict(metadata or {}),
        }
        _assert_no_raw_secret_values(payloads)
        intent_id = deployment_intent_id or f"deploy_intent_{uuid4().hex}"
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into deployment_intents (
                        deployment_intent_id,
                        status,
                        actor,
                        source,
                        reason,
                        profile_path,
                        requested_surfaces,
                        build_policy,
                        schedule_policy,
                        live_authority,
                        confirmation,
                        image_identities,
                        rollback_pointers,
                        metadata
                    )
                    values (
                        %s, 'pending', %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    returning *
                    """,
                    (
                        intent_id,
                        actor,
                        source,
                        reason,
                        profile_path,
                        Jsonb(list(surfaces)),
                        Jsonb(payloads["build_policy"]),
                        Jsonb(payloads["schedule_policy"]),
                        Jsonb(payloads["live_authority"]),
                        Jsonb(payloads["confirmation"]),
                        Jsonb(payloads["image_identities"]),
                        Jsonb(payloads["rollback_pointers"]),
                        Jsonb(payloads["metadata"]),
                    ),
                )
                row = cursor.fetchone()
            connection.commit()
        return _intent_from_row(row)

    def list_intents(self, *, limit: int = 50) -> list[DeploymentIntent]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from deployment_intents
                    order by created_at desc
                    limit %s
                    """,
                    (limit,),
                )
                return [_intent_from_row(row) for row in cursor.fetchall()]

    def get_intent(self, deployment_intent_id: str) -> DeploymentIntent:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from deployment_intents
                    where deployment_intent_id = %s
                    """,
                    (deployment_intent_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise KeyError(f"deployment intent not found: {deployment_intent_id}")
        return _intent_from_row(row)

    def cancel_intent(
        self,
        deployment_intent_id: str,
        *,
        actor: str,
        reason: str = "",
    ) -> DeploymentIntent:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update deployment_intents
                    set status = 'canceled',
                        canceled_at = now(),
                        completed_at = now(),
                        updated_at = now(),
                        metadata = metadata || %s::jsonb
                    where deployment_intent_id = %s
                        and status = 'pending'
                    returning *
                    """,
                    (
                        Jsonb(
                            {
                                "canceled_by": _required_text(actor, "actor"),
                                "cancel_reason": str(reason or ""),
                            }
                        ),
                        deployment_intent_id,
                    ),
                )
                row = cursor.fetchone()
            connection.commit()
        if row is None:
            current = self.get_intent(deployment_intent_id)
            raise ValueError(f"cannot cancel deployment intent in status {current.status}")
        return _intent_from_row(row)

    def claim_next(self, *, worker_id: str) -> DeploymentIntent | None:
        worker_id = _required_text(worker_id, "worker_id")
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select deployment_intent_id
                    from deployment_intents
                    where status = 'pending'
                    order by created_at
                    for update skip locked
                    limit 1
                    """
                )
                row = cursor.fetchone()
                if row is None:
                    connection.commit()
                    return None
                cursor.execute(
                    """
                    update deployment_intents
                    set status = 'planning',
                        claimed_by = %s,
                        claimed_at = now(),
                        updated_at = now()
                    where deployment_intent_id = %s
                    returning *
                    """,
                    (worker_id, row["deployment_intent_id"]),
                )
                claimed = cursor.fetchone()
            connection.commit()
        return _intent_from_row(claimed)

    def mark_planned(
        self,
        deployment_intent_id: str,
        *,
        evidence: Mapping[str, Any],
        rollback_pointers: Mapping[str, Any] | None = None,
        image_identities: Mapping[str, Any] | None = None,
    ) -> DeploymentIntent:
        return self._mark_terminal(
            deployment_intent_id,
            status="planned",
            evidence=evidence,
            rollback_pointers=rollback_pointers,
            image_identities=image_identities,
            error={},
        )

    def mark_failed(
        self,
        deployment_intent_id: str,
        *,
        error: Mapping[str, Any],
        evidence: Mapping[str, Any] | None = None,
    ) -> DeploymentIntent:
        return self._mark_terminal(
            deployment_intent_id,
            status="failed",
            evidence=evidence or {},
            rollback_pointers=None,
            image_identities=None,
            error=error,
        )

    def _mark_terminal(
        self,
        deployment_intent_id: str,
        *,
        status: str,
        evidence: Mapping[str, Any],
        rollback_pointers: Mapping[str, Any] | None,
        image_identities: Mapping[str, Any] | None,
        error: Mapping[str, Any],
    ) -> DeploymentIntent:
        if status not in FINAL_INTENT_STATUSES:
            raise ValueError(f"unsupported terminal deployment intent status: {status}")
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update deployment_intents
                    set status = %s,
                        evidence = evidence || %s::jsonb,
                        rollback_pointers = rollback_pointers || %s::jsonb,
                        image_identities = image_identities || %s::jsonb,
                        error = %s::jsonb,
                        completed_at = now(),
                        updated_at = now()
                    where deployment_intent_id = %s
                        and status = 'planning'
                    returning *
                    """,
                    (
                        status,
                        Jsonb(dict(evidence)),
                        Jsonb(dict(rollback_pointers or {})),
                        Jsonb(dict(image_identities or {})),
                        Jsonb(dict(error)),
                        deployment_intent_id,
                    ),
                )
                row = cursor.fetchone()
            connection.commit()
        if row is None:
            current = self.get_intent(deployment_intent_id)
            raise ValueError(f"cannot mark deployment intent in status {current.status}")
        return _intent_from_row(row)


def deployment_intent_kwargs_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    extra = set(payload) - CREATE_INTENT_FIELDS
    if extra:
        joined = ", ".join(sorted(extra))
        raise ValueError(f"unsupported deployment intent field(s): {joined}")
    _assert_no_raw_secret_values(payload)
    profile_path = payload.get("profile_path") or payload.get("profile_reference")
    return {
        "actor": _required_text(payload.get("actor"), "actor"),
        "source": str(payload.get("source") or "cockpit"),
        "reason": _required_text(payload.get("reason"), "reason"),
        "profile_path": str(profile_path or DEFAULT_DEPLOYMENT_PROFILE_PATH),
        "requested_surfaces": _surface_tuple(
            payload.get("requested_surfaces") or payload.get("surfaces") or ()
        ),
        "build_policy": _mapping(payload.get("build_policy"), "build_policy"),
        "schedule_policy": _mapping(payload.get("schedule_policy"), "schedule_policy"),
        "live_authority": _mapping(payload.get("live_authority"), "live_authority"),
        "confirmation": _mapping(payload.get("confirmation"), "confirmation"),
        "image_identities": _mapping(payload.get("image_identities"), "image_identities"),
        "rollback_pointers": _mapping(payload.get("rollback_pointers"), "rollback_pointers"),
        "metadata": _mapping(payload.get("metadata"), "metadata"),
    }


def _intent_from_row(row: Mapping[str, Any] | None) -> DeploymentIntent:
    if row is None:
        raise RuntimeError("deployment intent query did not return a row")
    return DeploymentIntent(
        deployment_intent_id=str(row["deployment_intent_id"]),
        status=str(row["status"]),
        actor=str(row["actor"]),
        source=str(row["source"]),
        reason=str(row["reason"]),
        profile_path=str(row["profile_path"]),
        requested_surfaces=tuple(str(item) for item in (row["requested_surfaces"] or [])),
        build_policy=dict(row["build_policy"] or {}),
        schedule_policy=dict(row["schedule_policy"] or {}),
        live_authority=dict(row["live_authority"] or {}),
        confirmation=dict(row["confirmation"] or {}),
        image_identities=dict(row["image_identities"] or {}),
        evidence=dict(row["evidence"] or {}),
        rollback_pointers=dict(row["rollback_pointers"] or {}),
        metadata=dict(row["metadata"] or {}),
        error=dict(row["error"] or {}),
        claimed_by=row["claimed_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        claimed_at=row["claimed_at"],
        completed_at=row["completed_at"],
        canceled_at=row["canceled_at"],
    )


def _surface_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("deployment intent surfaces must be a list of strings")
    surfaces = tuple(str(item).strip() for item in value if str(item).strip())
    if not surfaces:
        raise ValueError("deployment intent must request at least one surface")
    return surfaces


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"deployment intent requires {name}")
    return text


def _assert_no_raw_secret_values(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = str(key).lower()
            if normalized_key in FORBIDDEN_SECRET_KEYS:
                raise ValueError(f"raw secret field is not allowed in deployment intent: {key}")
            _assert_no_raw_secret_values(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            _assert_no_raw_secret_values(child)
    elif isinstance(value, str):
        for forbidden in FORBIDDEN_SECRET_STRINGS:
            if forbidden in value:
                raise ValueError("raw secret value is not allowed in deployment intent")
