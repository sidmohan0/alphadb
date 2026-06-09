from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from alphadb.config import settings_from_env
from alphadb.dashboard.app import DashboardService, make_handler
from alphadb.deployment_intents import DeploymentIntent


@dataclass
class FakeDeploymentIntentRepository:
    intents: dict[str, DeploymentIntent]

    def create_intent(self, **kwargs: Any) -> DeploymentIntent:
        kwargs.pop("image_identities", None)
        kwargs.pop("rollback_pointers", None)
        intent = fake_intent(
            deployment_intent_id=f"deploy_intent_{len(self.intents) + 1}",
            status="pending",
            **kwargs,
        )
        self.intents[intent.deployment_intent_id] = intent
        return intent

    def list_intents(self, *, limit: int = 50) -> list[DeploymentIntent]:
        return list(self.intents.values())[:limit]

    def get_intent(self, deployment_intent_id: str) -> DeploymentIntent:
        return self.intents[deployment_intent_id]

    def cancel_intent(
        self,
        deployment_intent_id: str,
        *,
        actor: str,
        reason: str = "",
    ) -> DeploymentIntent:
        current = self.intents[deployment_intent_id]
        intent = fake_intent(
            deployment_intent_id=deployment_intent_id,
            status="canceled",
            actor=current.actor,
            source=current.source,
            reason=current.reason,
            profile_path=current.profile_path,
            requested_surfaces=current.requested_surfaces,
            build_policy=current.build_policy,
            schedule_policy=current.schedule_policy,
            live_authority=current.live_authority,
            confirmation=current.confirmation,
            metadata={**current.metadata, "canceled_by": actor, "cancel_reason": reason},
        )
        self.intents[deployment_intent_id] = intent
        return intent


def fake_intent(
    *,
    deployment_intent_id: str,
    status: str,
    actor: str = "sid",
    source: str = "cockpit",
    reason: str = "deploy",
    profile_path: str = "deploy/aws/deployment-profile.example.yaml",
    requested_surfaces: tuple[str, ...] = ("cockpit",),
    build_policy: Mapping[str, Any] | None = None,
    schedule_policy: Mapping[str, Any] | None = None,
    live_authority: Mapping[str, Any] | None = None,
    confirmation: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DeploymentIntent:
    now = datetime(2026, 6, 9, 12, tzinfo=UTC)
    return DeploymentIntent(
        deployment_intent_id=deployment_intent_id,
        status=status,
        actor=actor,
        source=source,
        reason=reason,
        profile_path=profile_path,
        requested_surfaces=requested_surfaces,
        build_policy=dict(build_policy or {}),
        schedule_policy=dict(schedule_policy or {}),
        live_authority=dict(live_authority or {}),
        confirmation=dict(confirmation or {"confirmed": True}),
        image_identities={},
        evidence={},
        rollback_pointers={},
        metadata=dict(metadata or {}),
        error={},
        claimed_by=None,
        created_at=now,
        updated_at=now,
        claimed_at=None,
        completed_at=None,
        canceled_at=now if status == "canceled" else None,
    )


def test_dashboard_service_deployment_intent_methods_validate_and_delegate() -> None:
    fake_repository = FakeDeploymentIntentRepository({})
    service = DashboardService(
        settings=settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"}),
        deployment_intent_repository_factory=lambda _: fake_repository,
    )

    created = service.create_deployment_intent(
        {
            "actor": "sid",
            "reason": "deploy cockpit",
            "surfaces": ["cockpit"],
            "confirmation": {"confirmed": True},
        }
    )

    intent_id = created["intent"]["deployment_intent_id"]
    assert created["intent"]["requested_surfaces"] == ["cockpit"]
    assert service.list_deployment_intents()["intents"][0]["deployment_intent_id"] == intent_id
    assert service.get_deployment_intent(intent_id)["intent"]["status"] == "pending"
    canceled = service.cancel_deployment_intent(
        intent_id,
        {"actor": "sid", "reason": "not now"},
    )
    assert canceled["intent"]["status"] == "canceled"
    assert canceled["intent"]["metadata"]["cancel_reason"] == "not now"

    with pytest.raises(ValueError, match="unsupported deployment intent field"):
        service.create_deployment_intent(
            {
                "actor": "sid",
                "reason": "bad",
                "surfaces": ["cockpit"],
                "confirmation": {"confirmed": True},
                "aws_secret_access_key": "raw-secret",
            }
        )


def test_dashboard_http_exposes_deployment_intent_endpoints() -> None:
    fake_repository = FakeDeploymentIntentRepository({})
    service = DashboardService(
        settings=settings_from_env({"DATABASE_URL": "postgresql://example.test/alphadb"}),
        deployment_intent_repository_factory=lambda _: fake_repository,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        created = request_json(
            host,
            port,
            "POST",
            "/api/deployment/intents",
            {
                "actor": "sid",
                "reason": "deploy cockpit",
                "surfaces": ["cockpit"],
                "confirmation": {"confirmed": True},
            },
        )
        assert created["status"] == 202
        intent_id = created["body"]["data"]["intent"]["deployment_intent_id"]

        listed = request_json(host, port, "GET", "/api/deployment/intents")
        assert listed["status"] == 200
        assert listed["body"]["data"]["intents"][0]["deployment_intent_id"] == intent_id

        fetched = request_json(host, port, "GET", f"/api/deployment/intents/{intent_id}")
        assert fetched["body"]["data"]["intent"]["status"] == "pending"

        canceled = request_json(
            host,
            port,
            "POST",
            f"/api/deployment/intents/{intent_id}/cancel",
            {"actor": "sid", "reason": "pause"},
        )
        assert canceled["body"]["data"]["intent"]["status"] == "canceled"
    finally:
        server.shutdown()
        server.server_close()


def request_json(
    host: str,
    port: int,
    method: str,
    path: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    connection = HTTPConnection(host, port, timeout=5)
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    response_body = json.loads(response.read().decode("utf-8"))
    connection.close()
    return {"status": response.status, "body": response_body}
