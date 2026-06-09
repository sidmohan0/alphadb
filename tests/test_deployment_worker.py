from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg
import pytest

from alphadb.config import settings_from_env
from alphadb.deployment_intents import (
    DeploymentIntentRepository,
    deployment_intent_kwargs_from_payload,
)
from alphadb.deployment_worker import DeploymentIntentWorker


def repository_or_skip() -> DeploymentIntentRepository:
    repository = DeploymentIntentRepository(settings_from_env().database_url)
    try:
        repository.apply_migrations()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    return repository


def test_deployment_worker_claims_intent_and_records_dry_run_plan_evidence(
    tmp_path: Path,
) -> None:
    repository = repository_or_skip()
    profile = write_profile(tmp_path)
    intent = repository.create_intent(
        **deployment_intent_kwargs_from_payload(
            {
                "actor": "sid",
                "reason": "plan cockpit deploy",
                "profile_path": str(profile),
                "surfaces": ["cockpit"],
                "build_policy": {"skip_build": True, "skip_push": True},
                "confirmation": {"confirmed": True},
            }
        )
    )

    result = DeploymentIntentWorker(
        repository,
        manifest_root=tmp_path / "manifests",
    ).run_once(worker_id="worker-test")

    assert result.status == "planned"
    planned = repository.get_intent(intent.deployment_intent_id)
    assert planned.status == "planned"
    assert planned.claimed_by == "worker-test"
    assert planned.evidence["mode"] == "plan"
    assert planned.evidence["mutates_aws"] is False
    assert planned.evidence["skip_aws_read"] is True
    assert planned.evidence["selected_surfaces"] == ["cockpit"]
    assert Path(planned.evidence["manifest_path"]).exists()
    assert planned.image_identities["cockpit"]["tag"].startswith("cockpit-")


def test_deployment_worker_does_not_claim_canceled_intent(tmp_path: Path) -> None:
    repository = repository_or_skip()
    profile = write_profile(tmp_path)
    intent = repository.create_intent(
        **deployment_intent_kwargs_from_payload(
            {
                "actor": "sid",
                "reason": "plan cockpit deploy",
                "profile_path": str(profile),
                "surfaces": ["cockpit"],
                "confirmation": {"confirmed": True},
            }
        )
    )
    repository.cancel_intent(intent.deployment_intent_id, actor="sid")

    result = DeploymentIntentWorker(repository, manifest_root=tmp_path).run_once(
        worker_id="worker-test"
    )

    assert result.status == "idle"
    assert repository.get_intent(intent.deployment_intent_id).status == "canceled"


def test_deployment_worker_records_failure_evidence(tmp_path: Path) -> None:
    repository = repository_or_skip()
    profile = write_profile(tmp_path)
    intent = repository.create_intent(
        **deployment_intent_kwargs_from_payload(
            {
                "actor": "sid",
                "reason": "bad plan",
                "profile_path": str(profile),
                "surfaces": ["cockpit"],
                "confirmation": {"confirmed": True},
            }
        )
    )

    def broken_plan_factory(*_: Any, **__: Any) -> Any:
        raise RuntimeError("planner exploded")

    result = DeploymentIntentWorker(
        repository,
        manifest_root=tmp_path,
        plan_factory=broken_plan_factory,
    ).run_once(worker_id="worker-test")

    failed = repository.get_intent(intent.deployment_intent_id)
    assert result.status == "failed"
    assert failed.status == "failed"
    assert failed.error["type"] == "RuntimeError"
    assert failed.error["phase"] == "plan"
    assert failed.evidence["mutates_aws"] is False


def write_profile(tmp_path: Path) -> Path:
    payload = {
        "name": "alphadb-test",
        "aws": {
            "profile": "alphadb",
            "account_id": "123456789012",
            "region": "us-east-2",
        },
        "network": {
            "vpc_id": "vpc-0123456789abcdef0",
            "public_subnet_ids": ["subnet-0publica", "subnet-0publicb"],
            "private_subnet_ids": ["subnet-0privatea", "subnet-0privateb"],
            "worker_subnet_ids": ["subnet-0privatea", "subnet-0privateb"],
            "assign_public_ip": "DISABLED",
        },
        "secrets": {
            "database_url_secret_arn": (
                "arn:aws:secretsmanager:us-east-2:123456789012:secret:database"
            ),
            "cockpit_pin_secret_arn": (
                "arn:aws:secretsmanager:us-east-2:123456789012:secret:pin"
            ),
            "cockpit_cookie_secret_arn": (
                "arn:aws:secretsmanager:us-east-2:123456789012:secret:cookie"
            ),
            "kalshi_api_key_id_secret_arn": (
                "arn:aws:secretsmanager:us-east-2:123456789012:secret:kalshi-key-id"
            ),
            "kalshi_private_key_pem_secret_arn": (
                "arn:aws:secretsmanager:us-east-2:123456789012:secret:kalshi-private-key"
            ),
        },
        "images": {"repository": "alphadb-orchestrated", "platform": "linux/arm64"},
        "surfaces": {"selected": ["cockpit"]},
        "cockpit": {
            "stack_name": "alphadb-cockpit",
            "service_name": "alphadb-cockpit",
            "template_file": "deploy/aws/ecs-fargate-dashboard.yaml",
            "private_namespace_name": "alphadb.local",
            "runtime_mode": "gated-live",
            "desired_count": 1,
        },
    }
    path = tmp_path / "deployment-profile.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
