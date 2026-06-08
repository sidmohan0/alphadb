from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from alphadb.aws_deploy import (
    AwsReadClient,
    CommandResult,
    CommandRunner,
    DeploymentProfileError,
    SourceRevision,
    build_brti_deploy_command,
    build_cockpit_deploy_command,
    build_deployment_manifest,
    build_fair_value_deploy_command,
    create_deployment_plan,
    prepare_images,
    resolve_fair_value_schedule,
)


SOURCE = SourceRevision(
    git_sha="abcdef1234567890",
    short_sha="abcdef1",
    dirty_worktree=False,
)
TIMESTAMP = "20260608211530"


class FakeAwsReader(AwsReadClient):
    def __init__(self, *, account_id: str = "123456789012", schedule_state: str = "DISABLED"):
        self.account_id = account_id
        self.schedule_state = schedule_state

    def get_identity(self, *, aws_profile: str, region: str) -> dict[str, Any]:
        return {
            "status": "available",
            "account_id": self.account_id,
            "arn": f"arn:aws:iam::{self.account_id}:user/deployer",
        }

    def describe_stack(self, stack_name: str, *, aws_profile: str, region: str) -> dict[str, Any]:
        return {
            "status": "available",
            "stack_name": stack_name,
            "stack_status": "UPDATE_COMPLETE",
            "outputs": {
                "TaskDefinitionArn": f"arn:aws:ecs:{region}:{self.account_id}:task/{stack_name}",
                "DashboardUrl": "http://example.test",
            },
        }

    def describe_event_rule(self, rule_name: str, *, aws_profile: str, region: str) -> dict[str, Any]:
        return {
            "status": "available",
            "rule_name": rule_name,
            "state": self.schedule_state,
            "schedule_expression": "rate(1 minute)",
        }


class RecordingRunner(CommandRunner):
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        command,
        *,
        env=None,
        input_text=None,
        capture_output=False,
        check=True,
    ) -> CommandResult:
        self.commands.append(tuple(command))
        return CommandResult(args=tuple(command), returncode=0, stdout="", stderr="")


def test_aws_deployment_plan_orders_surfaces_and_builds_predictable_tags(tmp_path: Path) -> None:
    profile = write_profile(tmp_path, selected=["fair-value", "cockpit", "brti-collector"])

    resolved = create_deployment_plan(
        profile,
        source=SOURCE,
        timestamp=TIMESTAMP,
        aws_reader=FakeAwsReader(schedule_state="ENABLED"),
    )
    plan = resolved.plan_dict()

    assert plan["surface_order"] == ["cockpit", "brti-collector", "fair-value"]
    assert plan["images"]["cockpit"]["tag"] == f"cockpit-{SOURCE.short_sha}-{TIMESTAMP}"
    assert plan["images"]["runtime"]["tag"] == f"runtime-{SOURCE.short_sha}-{TIMESTAMP}"
    assert plan["images"]["runtime"]["uri"].endswith(":runtime-abcdef1-20260608211530")
    assert plan["surfaces"]["cockpit"]["private_api"] == "AlphaDB API"
    assert plan["fair_value_schedule"]["intended_state"] == "ENABLED"
    assert plan["fair_value_schedule"]["behavior"] == "preserve-enabled"


def test_aws_deployment_profile_missing_required_field_errors(tmp_path: Path) -> None:
    payload = profile_payload()
    del payload["network"]["vpc_id"]
    profile = write_profile(tmp_path, payload=payload)

    with pytest.raises(DeploymentProfileError, match="network.vpc_id"):
        create_deployment_plan(profile, source=SOURCE, timestamp=TIMESTAMP, skip_aws_read=True)


def test_aws_deployment_rejects_expensive_yes_surface(tmp_path: Path) -> None:
    profile = write_profile(tmp_path, selected=["cockpit", "expensive-yes"])

    with pytest.raises(DeploymentProfileError, match="expensive-yes is outside"):
        create_deployment_plan(profile, source=SOURCE, timestamp=TIMESTAMP, skip_aws_read=True)


def test_aws_deployment_rejects_fair_value_schedule_enablement(tmp_path: Path) -> None:
    profile = write_profile(tmp_path, fair_value_schedule_policy="enabled")

    with pytest.raises(DeploymentProfileError, match="enablement is rejected"):
        create_deployment_plan(profile, source=SOURCE, timestamp=TIMESTAMP, skip_aws_read=True)


def test_fair_value_schedule_preserves_observed_state_and_safe_disables() -> None:
    observed = {"status": "available", "state": "ENABLED", "rule_name": "alphadb-fv"}

    preserved = resolve_fair_value_schedule("preserve", observed=observed)
    disabled = resolve_fair_value_schedule("preserve", observed=observed, safe_disable=True)

    assert preserved["intended_state"] == "ENABLED"
    assert preserved["behavior"] == "preserve-enabled"
    assert disabled["intended_state"] == "DISABLED"
    assert disabled["behavior"] == "safe-disable"


def test_plan_renders_skip_build_and_push_behavior(tmp_path: Path) -> None:
    profile = write_profile(tmp_path)

    resolved = create_deployment_plan(
        profile,
        source=SOURCE,
        timestamp=TIMESTAMP,
        skip_aws_read=True,
        skip_build=True,
        skip_push=True,
    )

    assert resolved.plan_dict()["skip_behavior"] == {
        "skip_build": True,
        "skip_push": True,
        "skip_migrate": False,
        "skip_smoke": False,
        "skip_service_stability": False,
    }


def test_prepare_images_builds_each_unique_image_once_without_real_docker(tmp_path: Path) -> None:
    profile = write_profile(tmp_path, selected=["cockpit"])
    resolved = create_deployment_plan(
        profile,
        source=SOURCE,
        timestamp=TIMESTAMP,
        skip_aws_read=True,
        skip_push=True,
    )
    runner = RecordingRunner()

    result = prepare_images(resolved, runner=runner)

    docker_builds = [command for command in runner.commands if command[:2] == ("docker", "build")]
    assert len(docker_builds) == 2
    assert result["build"] == "passed"
    assert result["push"] == "skipped"
    assert {command[5] for command in docker_builds} == {
        "alphadb-orchestrated:cockpit-abcdef1-20260608211530",
        "alphadb-orchestrated:runtime-abcdef1-20260608211530",
    }


def test_apply_commands_use_shared_runtime_image_and_explicit_profile_inputs(
    tmp_path: Path,
) -> None:
    profile = write_profile(tmp_path)
    resolved = create_deployment_plan(
        profile,
        source=SOURCE,
        timestamp=TIMESTAMP,
        aws_reader=FakeAwsReader(schedule_state="DISABLED"),
    )

    cockpit = build_cockpit_deploy_command(resolved)
    brti = build_brti_deploy_command(resolved)
    fair_value = build_fair_value_deploy_command(resolved)

    runtime_param = f"AlphaDbApiContainerImage={resolved.images.runtime_uri}"
    assert f"CockpitContainerImage={resolved.images.cockpit_uri}" in cockpit
    assert runtime_param in cockpit
    assert f"ContainerImage={resolved.images.runtime_uri}" in brti
    assert f"ContainerImage={resolved.images.runtime_uri}" in fair_value
    assert "VpcId=vpc-0123456789abcdef0" in cockpit
    assert "SubnetIds=subnet-0privatea,subnet-0privateb" in brti
    assert "SubnetIds=subnet-0privatea,subnet-0privateb" in fair_value
    assert "ScheduleState=DISABLED" in fair_value
    assert not any("describe-vpcs" in item or "describe-subnets" in item for item in brti)


def test_manifest_shape_records_evidence_without_raw_secret_values(tmp_path: Path) -> None:
    profile = write_profile(tmp_path)
    resolved = create_deployment_plan(
        profile,
        source=SourceRevision(SOURCE.git_sha, SOURCE.short_sha, dirty_worktree=True),
        timestamp=TIMESTAMP,
        aws_reader=FakeAwsReader(schedule_state="DISABLED"),
    )
    apply_result = {
        "mode": "apply",
        "deployment_id": resolved.deployment_id,
        "surfaces": {
            "cockpit": {
                "stack_outputs": {"DashboardUrl": "http://example.test"},
                "smoke_results": {"cockpit_smoke": {"status": "passed"}},
            },
            "brti-collector": {
                "stack_outputs": {"ServiceName": "alphadb-brti-live-collector"},
                "status_results": {"service_stability": {"status": "passed"}},
            },
            "fair-value": {
                "stack_outputs": {"ScheduleName": "alphadb-fair-value-live"},
                "status_results": {"deployment": {"status": "passed"}},
            },
        },
    }

    manifest = build_deployment_manifest(resolved, mode="apply", apply_result=apply_result)
    encoded = json.dumps(manifest, sort_keys=True)

    assert manifest["schema_version"] == "alphadb.aws_deployment_manifest.v1"
    assert manifest["source_revision"]["dirty_worktree"] is True
    assert manifest["stack_outputs"]["cockpit"]["DashboardUrl"] == "http://example.test"
    assert manifest["smoke_results"]["cockpit"]["cockpit_smoke"]["status"] == "passed"
    assert manifest["schedules"]["fair-value"]["intended_state"] == "DISABLED"
    assert manifest["public_safety"]["raw_secret_values_included"] is False
    assert "postgresql://user:secret" not in encoded


def write_profile(
    tmp_path: Path,
    *,
    selected: list[str] | None = None,
    fair_value_schedule_policy: str = "preserve",
    payload: dict[str, Any] | None = None,
) -> Path:
    profile = payload or profile_payload(
        selected=selected,
        fair_value_schedule_policy=fair_value_schedule_policy,
    )
    path = tmp_path / "deployment-profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def profile_payload(
    *,
    selected: list[str] | None = None,
    fair_value_schedule_policy: str = "preserve",
) -> dict[str, Any]:
    return {
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
        "surfaces": {"selected": selected or ["cockpit", "brti-collector", "fair-value"]},
        "cockpit": {
            "stack_name": "alphadb-cockpit",
            "service_name": "alphadb-cockpit",
            "template_file": "deploy/aws/ecs-fargate-dashboard.yaml",
            "private_namespace_name": "alphadb.local",
            "runtime_mode": "gated-live",
            "desired_count": 1,
        },
        "brti_collector": {
            "stack_name": "alphadb-brti-live-collector",
            "service_name": "alphadb-brti-live-collector",
            "template_file": "deploy/aws/brti-live-collector.yaml",
            "desired_count": 1,
            "index_id": "BRTI",
            "max_reconnects": "1000000",
            "kalshi_websocket_url": "wss://external-api-ws.kalshi.com/trade-api/ws/v2",
        },
        "fair_value": {
            "stack_name": "alphadb-fair-value-live",
            "service_name": "alphadb-fair-value-live",
            "template_file": "deploy/aws/fair-value-live-trading-job.yaml",
            "report_bucket_name": "alphadb-artifacts-123456789012-us-east-2",
            "report_prefix": "fair-value-live",
            "schedule_expression": "rate(1 minute)",
            "schedule_policy": fair_value_schedule_policy,
            "min_edge_values": "0.0,0.05,0.10",
            "min_contract_price": "0.25",
        },
    }
