from __future__ import annotations

from typing import Any

import psycopg
import pytest

from alphadb.config import settings_from_env
from alphadb.deployment_intents import (
    DeploymentIntentRepository,
    deployment_intent_kwargs_from_payload,
)


def repository_or_skip() -> DeploymentIntentRepository:
    repository = DeploymentIntentRepository(settings_from_env().database_url)
    try:
        repository.apply_migrations()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    return repository


def intent_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "actor": "sid",
        "source": "cockpit",
        "reason": "validate deployment-intent tracer bullet",
        "profile_path": "deploy/aws/deployment-profile.example.yaml",
        "surfaces": ["cockpit", "fair-value"],
        "build_policy": {"skip_build": True, "skip_push": True},
        "schedule_policy": {"fair-value": {"action": "preserve"}},
        "live_authority": {"action": "preserve", "strategy": "fair_value_live"},
        "confirmation": {"confirmed": True, "confirmed_by": "sid"},
        "rollback_pointers": {"fair-value": {"previous_schedule_state": "DISABLED"}},
        "metadata": {"source_issue": "ADB-312"},
    }
    payload.update(overrides)
    return payload


def test_deployment_intent_repository_persists_lists_and_cancels_pending_intent() -> None:
    repository = repository_or_skip()

    intent = repository.create_intent(**deployment_intent_kwargs_from_payload(intent_payload()))

    fetched = repository.get_intent(intent.deployment_intent_id)
    assert fetched.status == "pending"
    assert fetched.actor == "sid"
    assert fetched.requested_surfaces == ("cockpit", "fair-value")
    assert fetched.build_policy["skip_build"] is True
    assert fetched.confirmation["confirmed"] is True
    assert fetched.live_authority["strategy"] == "fair_value_live"
    assert any(
        item.deployment_intent_id == intent.deployment_intent_id
        for item in repository.list_intents(limit=20)
    )

    canceled = repository.cancel_intent(
        intent.deployment_intent_id,
        actor="sid",
        reason="operator changed mind",
    )

    assert canceled.status == "canceled"
    assert canceled.canceled_at is not None
    assert canceled.metadata["canceled_by"] == "sid"
    assert canceled.metadata["cancel_reason"] == "operator changed mind"


def test_deployment_intent_claim_skips_canceled_intents_and_marks_planned() -> None:
    repository = repository_or_skip()
    canceled = repository.create_intent(**deployment_intent_kwargs_from_payload(intent_payload()))
    active = repository.create_intent(
        **deployment_intent_kwargs_from_payload(intent_payload(actor="agent"))
    )
    repository.cancel_intent(canceled.deployment_intent_id, actor="sid")

    claimed = repository.claim_next(worker_id="worker-a")
    assert claimed is not None
    assert claimed.deployment_intent_id == active.deployment_intent_id
    assert claimed.status == "planning"
    assert claimed.claimed_by == "worker-a"
    assert claimed.claimed_at is not None

    planned = repository.mark_planned(
        claimed.deployment_intent_id,
        evidence={"mode": "plan", "status": "passed"},
        rollback_pointers={"cockpit": {"status": "unavailable"}},
        image_identities={"runtime": {"tag": "runtime-test"}},
    )
    assert planned.status == "planned"
    assert planned.evidence["status"] == "passed"
    assert planned.rollback_pointers["cockpit"]["status"] == "unavailable"
    assert planned.image_identities["runtime"]["tag"] == "runtime-test"


def test_deployment_intent_payload_rejects_raw_secret_values() -> None:
    with pytest.raises(ValueError, match="unsupported deployment intent field"):
        deployment_intent_kwargs_from_payload(
            intent_payload(secrets={"database_url": "postgresql://user:secret@example/db"})
        )

    with pytest.raises(ValueError, match="raw secret value"):
        deployment_intent_kwargs_from_payload(
            intent_payload(metadata={"debug": "postgresql://user:secret@example/db"})
        )

    private_key_marker = "-----BEGIN " + "RSA PRIVATE KEY-----"
    with pytest.raises(ValueError, match="raw secret value"):
        deployment_intent_kwargs_from_payload(intent_payload(metadata={"debug": private_key_marker}))


def test_deployment_intent_payload_requires_confirmation() -> None:
    repository = repository_or_skip()
    kwargs = deployment_intent_kwargs_from_payload(
        intent_payload(confirmation={"confirmed": False})
    )

    with pytest.raises(ValueError, match="confirmation.confirmed=true"):
        repository.create_intent(**kwargs)
