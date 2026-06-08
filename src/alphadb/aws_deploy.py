"""Local AWS deployment orchestrator for AlphaDB MVP surfaces."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


PLAN_SCHEMA_VERSION = "alphadb.aws_deployment_plan.v1"
MANIFEST_SCHEMA_VERSION = "alphadb.aws_deployment_manifest.v1"
DEFAULT_MANIFEST_ROOT = Path("artifacts/aws-deployments")
SURFACE_ORDER = ("cockpit", "brti-collector", "fair-value")
SUPPORTED_SURFACES = set(SURFACE_ORDER)
SURFACE_ALIASES = {
    "cockpit": "cockpit",
    "dashboard": "cockpit",
    "brti": "brti-collector",
    "brti-collector": "brti-collector",
    "brti-live-collector": "brti-collector",
    "fair-value": "fair-value",
    "fair-value-live": "fair-value",
    "fair-value-wiring": "fair-value",
}
REJECTED_SURFACES = {
    "expensive-yes",
    "expensive-yes-live",
    "expensive-yes-live-trading-job",
}
API_SURFACES = {"api", "alphadb-api", "python-api", "dashboard-api"}


class DeploymentProfileError(ValueError):
    """Raised when the deployment profile is not safe or complete enough."""


class DeploymentApplyError(RuntimeError):
    """Raised when an apply command fails."""


@dataclass(frozen=True)
class SourceRevision:
    git_sha: str
    short_sha: str
    dirty_worktree: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "git_sha": self.git_sha,
            "short_git_sha": self.short_sha,
            "dirty_worktree": self.dirty_worktree,
        }


@dataclass(frozen=True)
class NetworkConfig:
    vpc_id: str
    public_subnet_ids: tuple[str, ...]
    private_subnet_ids: tuple[str, ...]
    worker_subnet_ids: tuple[str, ...]
    assign_public_ip: str


@dataclass(frozen=True)
class SecretConfig:
    database_url_secret_arn: str
    cockpit_pin_secret_arn: str
    cockpit_cookie_secret_arn: str
    kalshi_api_key_id_secret_arn: str
    kalshi_private_key_pem_secret_arn: str

    def as_dict(self) -> dict[str, str]:
        return {
            "database_url_secret_arn": self.database_url_secret_arn,
            "cockpit_pin_secret_arn": self.cockpit_pin_secret_arn,
            "cockpit_cookie_secret_arn": self.cockpit_cookie_secret_arn,
            "kalshi_api_key_id_secret_arn": self.kalshi_api_key_id_secret_arn,
            "kalshi_private_key_pem_secret_arn": self.kalshi_private_key_pem_secret_arn,
        }


@dataclass(frozen=True)
class ImageConfig:
    repository: str
    platform: str


@dataclass(frozen=True)
class CockpitConfig:
    stack_name: str
    service_name: str
    template_file: str
    private_namespace_name: str
    runtime_mode: str
    desired_count: int


@dataclass(frozen=True)
class BrtiCollectorConfig:
    stack_name: str
    service_name: str
    template_file: str
    desired_count: int
    index_id: str
    max_reconnects: str
    kalshi_websocket_url: str


@dataclass(frozen=True)
class FairValueConfig:
    stack_name: str
    service_name: str
    template_file: str
    report_bucket_name: str
    report_prefix: str
    schedule_expression: str
    schedule_policy: str
    min_edge_values: str
    min_contract_price: str


@dataclass(frozen=True)
class DeploymentProfile:
    name: str
    aws_profile: str
    account_id: str
    region: str
    selected_surfaces: tuple[str, ...]
    network: NetworkConfig
    secrets: SecretConfig
    images: ImageConfig
    cockpit: CockpitConfig | None
    brti_collector: BrtiCollectorConfig | None
    fair_value: FairValueConfig | None


@dataclass(frozen=True)
class ImagePlan:
    repository: str
    registry: str
    platform: str
    cockpit_tag: str
    runtime_tag: str
    cockpit_uri: str
    runtime_uri: str
    skip_build: bool
    skip_push: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "registry": self.registry,
            "platform": self.platform,
            "cockpit": {
                "tag": self.cockpit_tag,
                "uri": self.cockpit_uri,
                "local_tag": f"{self.repository}:{self.cockpit_tag}",
            },
            "runtime": {
                "tag": self.runtime_tag,
                "uri": self.runtime_uri,
                "local_tag": f"{self.repository}:{self.runtime_tag}",
            },
            "skip_build": self.skip_build,
            "skip_push": self.skip_push,
        }


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    """Small subprocess boundary that tests can replace."""

    def run(
        self,
        command: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
        capture_output: bool = False,
        check: bool = True,
    ) -> CommandResult:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        completed = subprocess.run(
            list(command),
            input=input_text,
            text=True,
            capture_output=capture_output,
            env=merged_env,
            check=False,
        )
        result = CommandResult(
            args=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
        if check and result.returncode != 0:
            rendered = " ".join(command)
            detail = result.stderr.strip() or result.stdout.strip()
            raise DeploymentApplyError(f"command failed ({result.returncode}): {rendered}\n{detail}")
        return result


class AwsReadClient:
    """Read-only AWS evidence adapter used by plan/apply safety logic."""

    def get_identity(self, *, aws_profile: str, region: str) -> dict[str, Any]:
        raise NotImplementedError

    def describe_stack(self, stack_name: str, *, aws_profile: str, region: str) -> dict[str, Any]:
        raise NotImplementedError

    def describe_event_rule(self, rule_name: str, *, aws_profile: str, region: str) -> dict[str, Any]:
        raise NotImplementedError


class NullAwsReadClient(AwsReadClient):
    def __init__(self, detail: str = "AWS read skipped") -> None:
        self.detail = detail

    def get_identity(self, *, aws_profile: str, region: str) -> dict[str, Any]:
        return {"status": "unavailable", "detail": self.detail}

    def describe_stack(self, stack_name: str, *, aws_profile: str, region: str) -> dict[str, Any]:
        return {"status": "unavailable", "stack_name": stack_name, "detail": self.detail}

    def describe_event_rule(self, rule_name: str, *, aws_profile: str, region: str) -> dict[str, Any]:
        return {"status": "unavailable", "rule_name": rule_name, "detail": self.detail}


class AwsCliReadClient(AwsReadClient):
    def _aws(self, aws_profile: str, region: str, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = ["aws", "--profile", aws_profile, "--region", region, *args]
        return subprocess.run(command, text=True, capture_output=True, check=False)

    def get_identity(self, *, aws_profile: str, region: str) -> dict[str, Any]:
        completed = self._aws(aws_profile, region, ["sts", "get-caller-identity", "--output", "json"])
        if completed.returncode != 0:
            return _unavailable_from_completed("aws_identity", completed)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return {"status": "unavailable", "detail": f"invalid identity JSON: {exc}"}
        return {
            "status": "available",
            "account_id": str(payload.get("Account") or ""),
            "arn": payload.get("Arn"),
            "user_id": payload.get("UserId"),
        }

    def describe_stack(self, stack_name: str, *, aws_profile: str, region: str) -> dict[str, Any]:
        completed = self._aws(
            aws_profile,
            region,
            [
                "cloudformation",
                "describe-stacks",
                "--stack-name",
                stack_name,
                "--output",
                "json",
            ],
        )
        if completed.returncode != 0:
            if "does not exist" in completed.stderr or "ValidationError" in completed.stderr:
                return {"status": "not_found", "stack_name": stack_name, "outputs": {}}
            return _unavailable_from_completed(stack_name, completed)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return {"status": "unavailable", "stack_name": stack_name, "detail": str(exc)}
        stacks = payload.get("Stacks") or []
        if not stacks:
            return {"status": "not_found", "stack_name": stack_name, "outputs": {}}
        stack = stacks[0]
        return {
            "status": "available",
            "stack_name": stack_name,
            "stack_status": stack.get("StackStatus"),
            "outputs": _outputs_to_dict(stack.get("Outputs") or []),
        }

    def describe_event_rule(self, rule_name: str, *, aws_profile: str, region: str) -> dict[str, Any]:
        completed = self._aws(
            aws_profile,
            region,
            ["events", "describe-rule", "--name", rule_name, "--output", "json"],
        )
        if completed.returncode != 0:
            if "ResourceNotFoundException" in completed.stderr:
                return {"status": "not_found", "rule_name": rule_name, "state": None}
            return _unavailable_from_completed(rule_name, completed)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return {"status": "unavailable", "rule_name": rule_name, "detail": str(exc)}
        return {
            "status": "available",
            "rule_name": rule_name,
            "state": payload.get("State"),
            "schedule_expression": payload.get("ScheduleExpression"),
            "arn": payload.get("Arn"),
        }


@dataclass(frozen=True)
class ResolvedDeployment:
    profile: DeploymentProfile
    profile_path: Path
    selected_surfaces: tuple[str, ...]
    source: SourceRevision
    timestamp: str
    deployment_id: str
    images: ImagePlan
    aws_identity: dict[str, Any]
    observed_stacks: dict[str, dict[str, Any]]
    fair_value_schedule: dict[str, Any] | None
    skip_migrate: bool
    skip_smoke: bool
    skip_service_stability: bool

    def plan_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PLAN_SCHEMA_VERSION,
            "deployment_id": self.deployment_id,
            "generated_at_utc": _utc_now_iso(),
            "profile": {
                "name": self.profile.name,
                "path": str(self.profile_path),
                "aws_profile": self.profile.aws_profile,
                "account_id": self.profile.account_id,
                "region": self.profile.region,
            },
            "source_revision": self.source.as_dict(),
            "aws_identity": self.aws_identity,
            "selected_surfaces": list(self.selected_surfaces),
            "surface_order": list(self.selected_surfaces),
            "images": self.images.as_dict(),
            "skip_behavior": {
                "skip_build": self.images.skip_build,
                "skip_push": self.images.skip_push,
                "skip_migrate": self.skip_migrate,
                "skip_smoke": self.skip_smoke,
                "skip_service_stability": self.skip_service_stability,
            },
            "network": {
                "vpc_id": self.profile.network.vpc_id,
                "public_subnet_ids": list(self.profile.network.public_subnet_ids),
                "private_subnet_ids": list(self.profile.network.private_subnet_ids),
                "worker_subnet_ids": list(self.profile.network.worker_subnet_ids),
                "assign_public_ip": self.profile.network.assign_public_ip,
            },
            "surfaces": _surface_plan_dict(self),
            "observed_stacks": self.observed_stacks,
            "fair_value_schedule": self.fair_value_schedule,
        }


def add_aws_deploy_parser(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="aws_action", required=True)
    plan = subparsers.add_parser("plan", help="Resolve a non-mutating AWS deployment plan")
    apply = subparsers.add_parser("apply", help="Apply selected AWS deployment surfaces")
    _add_common_args(plan)
    _add_common_args(apply)


def run_aws_deployment_command(args: argparse.Namespace) -> int:
    try:
        surfaces = parse_surfaces_arg(args.surfaces) if args.surfaces else None
        resolved = create_deployment_plan(
            args.deployment_profile,
            surfaces=surfaces,
            deployment_id=args.deployment_id,
            skip_aws_read=args.skip_aws_read,
            skip_build=args.skip_build,
            skip_push=args.skip_push,
            skip_migrate=args.skip_migrate,
            skip_smoke=args.skip_smoke,
            skip_service_stability=args.skip_service_stability,
            fair_value_safe_disable=args.fair_value_safe_disable,
        )
        if args.aws_action == "plan":
            manifest_path = write_deployment_manifest(
                resolved,
                mode="plan",
                manifest_root=Path(args.manifest_root),
            )
            print(
                json.dumps(
                    {"plan": resolved.plan_dict(), "manifest_path": str(manifest_path)},
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.aws_action == "apply":
            apply_result = apply_deployment(resolved)
            manifest_path = write_deployment_manifest(
                resolved,
                mode="apply",
                apply_result=apply_result,
                manifest_root=Path(args.manifest_root),
            )
            print(
                json.dumps(
                    {
                        "plan": resolved.plan_dict(),
                        "apply": apply_result,
                        "manifest_path": str(manifest_path),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        raise AssertionError(f"unhandled aws action: {args.aws_action}")
    except DeploymentProfileError as exc:
        print(f"deployment profile error: {exc}", file=sys.stderr)
        return 2
    except DeploymentApplyError as exc:
        print(f"deployment apply error: {exc}", file=sys.stderr)
        return 1


def create_deployment_plan(
    profile_path: str | Path,
    *,
    surfaces: Sequence[str] | None = None,
    source: SourceRevision | None = None,
    timestamp: str | None = None,
    deployment_id: str | None = None,
    aws_reader: AwsReadClient | None = None,
    skip_aws_read: bool = False,
    skip_build: bool = False,
    skip_push: bool = False,
    skip_migrate: bool = False,
    skip_smoke: bool = False,
    skip_service_stability: bool = False,
    fair_value_safe_disable: bool = False,
) -> ResolvedDeployment:
    path = Path(profile_path).expanduser().resolve()
    profile = load_deployment_profile(path)
    selected = order_surfaces(surfaces or profile.selected_surfaces)
    _validate_surface_sections(profile, selected)

    source = source or collect_source_revision()
    timestamp = timestamp or datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    deployment_id = deployment_id or f"aws-{timestamp}-{source.short_sha}"
    images = build_image_plan(
        profile,
        source=source,
        timestamp=timestamp,
        skip_build=skip_build,
        skip_push=skip_push,
    )

    reader = NullAwsReadClient() if skip_aws_read else aws_reader or AwsCliReadClient()
    identity = reader.get_identity(aws_profile=profile.aws_profile, region=profile.region)
    _validate_observed_identity(profile, identity)
    observed_stacks = {
        surface: reader.describe_stack(
            _stack_name(profile, surface),
            aws_profile=profile.aws_profile,
            region=profile.region,
        )
        for surface in selected
    }
    fair_value_schedule = None
    if "fair-value" in selected:
        assert profile.fair_value is not None
        observed = reader.describe_event_rule(
            profile.fair_value.service_name,
            aws_profile=profile.aws_profile,
            region=profile.region,
        )
        fair_value_schedule = resolve_fair_value_schedule(
            profile.fair_value.schedule_policy,
            observed=observed,
            safe_disable=fair_value_safe_disable,
            apply_mode=False,
        )

    return ResolvedDeployment(
        profile=profile,
        profile_path=path,
        selected_surfaces=selected,
        source=source,
        timestamp=timestamp,
        deployment_id=deployment_id,
        images=images,
        aws_identity=identity,
        observed_stacks=observed_stacks,
        fair_value_schedule=fair_value_schedule,
        skip_migrate=skip_migrate,
        skip_smoke=skip_smoke,
        skip_service_stability=skip_service_stability,
    )


def apply_deployment(
    resolved: ResolvedDeployment,
    *,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    runner = runner or CommandRunner()
    image_result = prepare_images(resolved, runner=runner)
    surface_results: dict[str, Any] = {}
    for surface in resolved.selected_surfaces:
        if surface == "cockpit":
            surface_results[surface] = apply_cockpit_surface(resolved, runner=runner)
        elif surface == "brti-collector":
            surface_results[surface] = apply_brti_surface(resolved, runner=runner)
        elif surface == "fair-value":
            surface_results[surface] = apply_fair_value_surface(resolved, runner=runner)
        else:  # pragma: no cover - selected surfaces are validated before apply.
            raise DeploymentApplyError(f"unsupported surface at apply time: {surface}")
    return {
        "mode": "apply",
        "deployment_id": resolved.deployment_id,
        "images": image_result,
        "surfaces": surface_results,
    }


def prepare_images(resolved: ResolvedDeployment, *, runner: CommandRunner) -> dict[str, Any]:
    images = resolved.images
    aws = _aws_base(resolved.profile)
    results: dict[str, Any] = {
        "repository": images.repository,
        "registry": images.registry,
        "build": "skipped" if images.skip_build else "pending",
        "push": "skipped" if images.skip_push else "pending",
        "built_images": [],
        "pushed_images": [],
    }
    if not images.skip_push:
        describe = [
            *aws,
            "ecr",
            "describe-repositories",
            "--repository-names",
            images.repository,
        ]
        try:
            runner.run(describe, capture_output=True)
        except DeploymentApplyError:
            runner.run(
                [
                    *aws,
                    "ecr",
                    "create-repository",
                    "--repository-name",
                    images.repository,
                    "--image-scanning-configuration",
                    "scanOnPush=true",
                ],
                capture_output=True,
            )
        password = runner.run([*aws, "ecr", "get-login-password"], capture_output=True).stdout
        runner.run(
            ["docker", "login", "--username", "AWS", "--password-stdin", images.registry],
            input_text=password,
        )

    if not images.skip_build:
        runner.run(
            [
                "docker",
                "build",
                "--platform",
                images.platform,
                "-t",
                f"{images.repository}:{images.cockpit_tag}",
                "-f",
                "apps/dashboard/Dockerfile",
                "apps/dashboard",
            ]
        )
        runner.run(
            [
                "docker",
                "build",
                "--platform",
                images.platform,
                "-t",
                f"{images.repository}:{images.runtime_tag}",
                ".",
            ]
        )
        results["build"] = "passed"
        results["built_images"] = [images.cockpit_uri, images.runtime_uri]

    if not images.skip_push:
        for local_tag, image_uri in (
            (f"{images.repository}:{images.cockpit_tag}", images.cockpit_uri),
            (f"{images.repository}:{images.runtime_tag}", images.runtime_uri),
        ):
            runner.run(["docker", "tag", local_tag, image_uri])
            runner.run(["docker", "push", image_uri])
            results["pushed_images"].append(image_uri)
        results["push"] = "passed"
    return results


def apply_cockpit_surface(
    resolved: ResolvedDeployment,
    *,
    runner: CommandRunner,
) -> dict[str, Any]:
    runner.run(build_cockpit_deploy_command(resolved))
    outputs = describe_stack_outputs(resolved, resolved.profile.cockpit.stack_name, runner=runner)  # type: ignore[union-attr]
    smoke_results: dict[str, Any] = {}
    if resolved.skip_migrate:
        smoke_results["migrations"] = {"status": "skipped"}
        smoke_results["readiness_seed"] = {"status": "skipped"}
        smoke_results["deployment_smoke"] = {"status": "skipped"}
    else:
        _run_api_command(resolved, ["alphadb-deploy", "migrate"], runner=runner)
        smoke_results["migrations"] = {"status": "passed"}
        _run_api_command(
            resolved,
            ["alphadb-deploy", "seed-readiness", "--series", "KXBTC15M"],
            runner=runner,
        )
        smoke_results["readiness_seed"] = {"status": "passed"}
        _run_api_command(resolved, ["alphadb-deploy", "smoke"], runner=runner)
        smoke_results["deployment_smoke"] = {"status": "passed"}

    if resolved.skip_smoke:
        smoke_results["cockpit_smoke"] = {"status": "skipped"}
    else:
        dashboard_url = outputs.get("DashboardUrl") or _stack_output(
            resolved,
            resolved.profile.cockpit.stack_name,  # type: ignore[union-attr]
            "DashboardUrl",
            runner=runner,
        )
        runner.run(
            ["deploy/aws/smoke-cockpit-stack.sh"],
            env={
                "COCKPIT_URL": dashboard_url,
                "COCKPIT_PIN_SECRET_ARN": resolved.profile.secrets.cockpit_pin_secret_arn,
                "AWS_PROFILE": resolved.profile.aws_profile,
                "AWS_REGION": resolved.profile.region,
            },
        )
        smoke_results["cockpit_smoke"] = {"status": "passed"}

    return {
        "status": "deployed",
        "stack_name": resolved.profile.cockpit.stack_name,  # type: ignore[union-attr]
        "stack_outputs": outputs,
        "smoke_results": smoke_results,
    }


def apply_brti_surface(
    resolved: ResolvedDeployment,
    *,
    runner: CommandRunner,
) -> dict[str, Any]:
    assert resolved.profile.brti_collector is not None
    runner.run(build_brti_deploy_command(resolved))
    outputs = describe_stack_outputs(resolved, resolved.profile.brti_collector.stack_name, runner=runner)
    status_result = {"status": "skipped"} if resolved.skip_service_stability else {"status": "passed"}
    if not resolved.skip_service_stability:
        runner.run(
            [
                *_aws_base(resolved.profile),
                "ecs",
                "wait",
                "services-stable",
                "--cluster",
                resolved.profile.brti_collector.service_name,
                "--services",
                resolved.profile.brti_collector.service_name,
            ]
        )
    return {
        "status": "deployed",
        "stack_name": resolved.profile.brti_collector.stack_name,
        "stack_outputs": outputs,
        "status_results": {"service_stability": status_result},
    }


def apply_fair_value_surface(
    resolved: ResolvedDeployment,
    *,
    runner: CommandRunner,
) -> dict[str, Any]:
    assert resolved.profile.fair_value is not None
    observed = (resolved.fair_value_schedule or {}).get("observed", {})
    schedule = resolve_fair_value_schedule(
        resolved.profile.fair_value.schedule_policy,
        observed=observed,
        safe_disable=(resolved.fair_value_schedule or {}).get("profile_policy") == "disable",
        apply_mode=True,
    )
    runner.run(build_fair_value_deploy_command(resolved, schedule=schedule))
    outputs = describe_stack_outputs(resolved, resolved.profile.fair_value.stack_name, runner=runner)
    return {
        "status": "deployed",
        "stack_name": resolved.profile.fair_value.stack_name,
        "stack_outputs": outputs,
        "schedule": schedule,
        "status_results": {"deployment": {"status": "passed"}},
    }


def build_cockpit_deploy_command(resolved: ResolvedDeployment) -> list[str]:
    assert resolved.profile.cockpit is not None
    profile = resolved.profile
    network = profile.network
    secrets = profile.secrets
    cockpit = profile.cockpit
    return [
        *_aws_base(profile),
        "cloudformation",
        "deploy",
        "--stack-name",
        cockpit.stack_name,
        "--template-file",
        cockpit.template_file,
        "--capabilities",
        "CAPABILITY_IAM",
        "--parameter-overrides",
        f"ServiceName={cockpit.service_name}",
        f"CockpitContainerImage={resolved.images.cockpit_uri}",
        f"AlphaDbApiContainerImage={resolved.images.runtime_uri}",
        f"VpcId={network.vpc_id}",
        f"PublicSubnetIds={','.join(network.public_subnet_ids)}",
        f"PrivateSubnetIds={','.join(network.private_subnet_ids)}",
        f"AssignPublicIp={network.assign_public_ip}",
        f"DatabaseUrlSecretArn={secrets.database_url_secret_arn}",
        f"CockpitPinSecretArn={secrets.cockpit_pin_secret_arn}",
        f"CockpitCookieSecretArn={secrets.cockpit_cookie_secret_arn}",
        f"KalshiApiKeyIdSecretArn={secrets.kalshi_api_key_id_secret_arn}",
        f"KalshiPrivateKeyPemSecretArn={secrets.kalshi_private_key_pem_secret_arn}",
        f"PrivateNamespaceName={cockpit.private_namespace_name}",
        f"RuntimeMode={cockpit.runtime_mode}",
        f"DesiredCount={cockpit.desired_count}",
        f"AwsRegionValue={profile.region}",
    ]


def build_brti_deploy_command(resolved: ResolvedDeployment) -> list[str]:
    assert resolved.profile.brti_collector is not None
    profile = resolved.profile
    network = profile.network
    secrets = profile.secrets
    brti = profile.brti_collector
    return [
        *_aws_base(profile),
        "cloudformation",
        "deploy",
        "--stack-name",
        brti.stack_name,
        "--template-file",
        brti.template_file,
        "--capabilities",
        "CAPABILITY_IAM",
        "--parameter-overrides",
        f"ServiceName={brti.service_name}",
        f"ContainerImage={resolved.images.runtime_uri}",
        f"VpcId={network.vpc_id}",
        f"SubnetIds={','.join(network.worker_subnet_ids)}",
        f"AssignPublicIp={network.assign_public_ip}",
        f"DesiredCount={brti.desired_count}",
        f"IndexId={brti.index_id}",
        f"MaxReconnects={brti.max_reconnects}",
        f"KalshiWebSocketUrl={brti.kalshi_websocket_url}",
        f"DatabaseUrlSecretArn={secrets.database_url_secret_arn}",
        f"KalshiApiKeyIdSecretArn={secrets.kalshi_api_key_id_secret_arn}",
        f"KalshiPrivateKeyPemSecretArn={secrets.kalshi_private_key_pem_secret_arn}",
        f"AwsRegionValue={profile.region}",
    ]


def build_fair_value_deploy_command(
    resolved: ResolvedDeployment,
    *,
    schedule: Mapping[str, Any] | None = None,
) -> list[str]:
    assert resolved.profile.fair_value is not None
    profile = resolved.profile
    network = profile.network
    secrets = profile.secrets
    fair_value = profile.fair_value
    schedule = dict(schedule or resolved.fair_value_schedule or {})
    schedule_state = schedule.get("intended_state")
    if schedule_state not in {"ENABLED", "DISABLED"}:
        raise DeploymentApplyError(
            "fair-value apply requires resolved schedule state ENABLED or DISABLED"
        )
    return [
        *_aws_base(profile),
        "cloudformation",
        "deploy",
        "--stack-name",
        fair_value.stack_name,
        "--template-file",
        fair_value.template_file,
        "--capabilities",
        "CAPABILITY_IAM",
        "--parameter-overrides",
        f"ServiceName={fair_value.service_name}",
        f"ContainerImage={resolved.images.runtime_uri}",
        f"VpcId={network.vpc_id}",
        f"SubnetIds={','.join(network.worker_subnet_ids)}",
        f"AssignPublicIp={network.assign_public_ip}",
        f"ReportBucketName={fair_value.report_bucket_name}",
        f"ReportPrefix={fair_value.report_prefix}",
        f"DatabaseUrlSecretArn={secrets.database_url_secret_arn}",
        f"ScheduleExpression={fair_value.schedule_expression}",
        f"ScheduleState={schedule_state}",
        f"MinEdgeValues={fair_value.min_edge_values}",
        f"MinContractPrice={fair_value.min_contract_price}",
        f"KalshiApiKeyIdSecretArn={secrets.kalshi_api_key_id_secret_arn}",
        f"KalshiPrivateKeyPemSecretArn={secrets.kalshi_private_key_pem_secret_arn}",
        f"AwsRegionValue={profile.region}",
    ]


def describe_stack_outputs(
    resolved: ResolvedDeployment,
    stack_name: str,
    *,
    runner: CommandRunner,
) -> dict[str, str]:
    result = runner.run(
        [
            *_aws_base(resolved.profile),
            "cloudformation",
            "describe-stacks",
            "--stack-name",
            stack_name,
            "--query",
            "Stacks[0].Outputs",
            "--output",
            "json",
        ],
        capture_output=True,
    )
    if not result.stdout.strip():
        return {}
    return _outputs_to_dict(json.loads(result.stdout))


def write_deployment_manifest(
    resolved: ResolvedDeployment,
    *,
    mode: str,
    apply_result: Mapping[str, Any] | None = None,
    manifest_root: Path = DEFAULT_MANIFEST_ROOT,
) -> Path:
    manifest = build_deployment_manifest(resolved, mode=mode, apply_result=apply_result)
    manifest_root.mkdir(parents=True, exist_ok=True)
    path = manifest_root / f"{resolved.deployment_id}.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def build_deployment_manifest(
    resolved: ResolvedDeployment,
    *,
    mode: str,
    apply_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    apply_surfaces = dict((apply_result or {}).get("surfaces") or {})
    stack_outputs = {
        surface: (
            apply_surfaces.get(surface, {}).get("stack_outputs")
            or resolved.observed_stacks.get(surface, {}).get("outputs", {})
        )
        for surface in resolved.selected_surfaces
    }
    smoke_results = {
        surface: apply_surfaces.get(surface, {}).get("smoke_results", {})
        for surface in resolved.selected_surfaces
    }
    status_results = {
        surface: apply_surfaces.get(surface, {}).get("status_results", {})
        for surface in resolved.selected_surfaces
    }
    rollback_pointers = {
        surface: {
            "previous_stack_outputs": resolved.observed_stacks.get(surface, {}).get("outputs", {}),
            "previous_task_definition": _previous_task_definition(
                resolved.observed_stacks.get(surface, {}).get("outputs", {})
            ),
        }
        for surface in resolved.selected_surfaces
    }
    if resolved.fair_value_schedule:
        rollback_pointers["fair-value"] = {
            **rollback_pointers.get("fair-value", {}),
            "previous_schedule_state": resolved.fair_value_schedule.get("observed", {}).get("state"),
        }

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "mode": mode,
        "deployment_id": resolved.deployment_id,
        "generated_at_utc": _utc_now_iso(),
        "source_revision": resolved.source.as_dict(),
        "profile": {
            "name": resolved.profile.name,
            "path": str(resolved.profile_path),
            "aws_profile": resolved.profile.aws_profile,
            "account_id": resolved.profile.account_id,
            "region": resolved.profile.region,
            "secret_refs": resolved.profile.secrets.as_dict(),
        },
        "selected_surfaces": list(resolved.selected_surfaces),
        "aws": {
            "account_id": resolved.profile.account_id,
            "region": resolved.profile.region,
            "observed_identity": resolved.aws_identity,
        },
        "images": resolved.images.as_dict(),
        "stack_outputs": stack_outputs,
        "schedules": {"fair-value": resolved.fair_value_schedule}
        if resolved.fair_value_schedule
        else {},
        "smoke_results": smoke_results,
        "status_results": status_results,
        "rollback_pointers": rollback_pointers,
        "apply": dict(apply_result or {}),
        "public_safety": {
            "raw_secret_values_included": False,
            "secret_arn_references_only": True,
            "writes_operational_state_deployment_history": False,
            "writes_s3_deployment_history": False,
        },
    }


def build_image_plan(
    profile: DeploymentProfile,
    *,
    source: SourceRevision,
    timestamp: str,
    skip_build: bool,
    skip_push: bool,
) -> ImagePlan:
    cockpit_tag = f"cockpit-{source.short_sha}-{timestamp}"
    runtime_tag = f"runtime-{source.short_sha}-{timestamp}"
    registry = f"{profile.account_id}.dkr.ecr.{profile.region}.amazonaws.com"
    repository_uri = f"{registry}/{profile.images.repository}"
    return ImagePlan(
        repository=profile.images.repository,
        registry=registry,
        platform=profile.images.platform,
        cockpit_tag=cockpit_tag,
        runtime_tag=runtime_tag,
        cockpit_uri=f"{repository_uri}:{cockpit_tag}",
        runtime_uri=f"{repository_uri}:{runtime_tag}",
        skip_build=skip_build,
        skip_push=skip_push,
    )


def resolve_fair_value_schedule(
    policy: str,
    *,
    observed: Mapping[str, Any],
    safe_disable: bool = False,
    apply_mode: bool = False,
) -> dict[str, Any]:
    normalized = _normalize_schedule_policy(policy)
    if safe_disable:
        normalized = "disable"
    if normalized == "enable":
        raise DeploymentProfileError(
            "fair-value schedule enablement is outside the orchestrator MVP; "
            "use preserve for existing state or disable for safe-disable"
        )
    observed_state = observed.get("state")
    observed_status = observed.get("status")
    if normalized == "disable":
        intended_state = "DISABLED"
        behavior = "safe-disable"
    elif observed_status == "available" and observed_state in {"ENABLED", "DISABLED"}:
        intended_state = observed_state
        behavior = f"preserve-{observed_state.lower()}"
    elif observed_status == "not_found":
        intended_state = "DISABLED"
        behavior = "new-schedule-disabled"
    elif apply_mode:
        raise DeploymentApplyError(
            "fair-value schedule_policy=preserve requires observed schedule state before apply"
        )
    else:
        intended_state = "preserve-observed"
        behavior = "preserve-when-observable"
    return {
        "observed": dict(observed),
        "profile_policy": normalized,
        "intended_state": intended_state,
        "behavior": behavior,
        "enablement_rejected_by_mvp": True,
    }


def load_deployment_profile(path: str | Path) -> DeploymentProfile:
    raw = _load_json_or_yaml(Path(path))
    root = _as_mapping(raw, "profile root")
    aws = _required_mapping(root, "aws", "aws")
    network = _required_mapping(root, "network", "network")
    secrets = _required_mapping(root, "secrets", "secrets")
    images = _required_mapping(root, "images", "images")
    surfaces = _required_mapping(root, "surfaces", "surfaces")
    selected = order_surfaces(_required_str_list(surfaces, "selected", "surfaces.selected"))

    return DeploymentProfile(
        name=_required_str(root, "name", "name"),
        aws_profile=_required_str(aws, "profile", "aws.profile"),
        account_id=_required_str(aws, "account_id", "aws.account_id"),
        region=_required_str(aws, "region", "aws.region"),
        selected_surfaces=selected,
        network=NetworkConfig(
            vpc_id=_required_str(network, "vpc_id", "network.vpc_id"),
            public_subnet_ids=_required_str_list(
                network, "public_subnet_ids", "network.public_subnet_ids"
            ),
            private_subnet_ids=_required_str_list(
                network, "private_subnet_ids", "network.private_subnet_ids"
            ),
            worker_subnet_ids=_optional_str_list(
                network,
                "worker_subnet_ids",
                "network.worker_subnet_ids",
                default=_required_str_list(
                    network,
                    "private_subnet_ids",
                    "network.private_subnet_ids",
                ),
            ),
            assign_public_ip=_optional_str(
                network,
                "assign_public_ip",
                "DISABLED",
            ),
        ),
        secrets=SecretConfig(
            database_url_secret_arn=_required_str(
                secrets, "database_url_secret_arn", "secrets.database_url_secret_arn"
            ),
            cockpit_pin_secret_arn=_required_str(
                secrets, "cockpit_pin_secret_arn", "secrets.cockpit_pin_secret_arn"
            ),
            cockpit_cookie_secret_arn=_required_str(
                secrets,
                "cockpit_cookie_secret_arn",
                "secrets.cockpit_cookie_secret_arn",
            ),
            kalshi_api_key_id_secret_arn=_required_str(
                secrets,
                "kalshi_api_key_id_secret_arn",
                "secrets.kalshi_api_key_id_secret_arn",
            ),
            kalshi_private_key_pem_secret_arn=_required_str(
                secrets,
                "kalshi_private_key_pem_secret_arn",
                "secrets.kalshi_private_key_pem_secret_arn",
            ),
        ),
        images=ImageConfig(
            repository=_required_str(images, "repository", "images.repository"),
            platform=_optional_str(images, "platform", "linux/arm64"),
        ),
        cockpit=_load_cockpit_config(root.get("cockpit")),
        brti_collector=_load_brti_config(root.get("brti_collector")),
        fair_value=_load_fair_value_config(root.get("fair_value")),
    )


def parse_surfaces_arg(raw: str) -> tuple[str, ...]:
    values = [value.strip() for value in raw.split(",") if value.strip()]
    if not values:
        raise DeploymentProfileError("--surfaces must include at least one surface")
    return order_surfaces(values)


def order_surfaces(values: Sequence[str]) -> tuple[str, ...]:
    seen = {_canonical_surface(value) for value in values}
    return tuple(surface for surface in SURFACE_ORDER if surface in seen)


def collect_source_revision() -> SourceRevision:
    full = _git_output(["git", "rev-parse", "HEAD"])
    short = _git_output(["git", "rev-parse", "--short", "HEAD"])
    status = _git_output(["git", "status", "--porcelain"])
    return SourceRevision(git_sha=full, short_sha=short, dirty_worktree=bool(status))


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        dest="deployment_profile",
        required=True,
        help="Path to the explicit AWS deployment profile YAML/JSON",
    )
    parser.add_argument(
        "--surfaces",
        default=None,
        help="Comma-separated surface override: cockpit,brti-collector,fair-value",
    )
    parser.add_argument("--deployment-id", default=None)
    parser.add_argument("--manifest-root", default=str(DEFAULT_MANIFEST_ROOT))
    parser.add_argument("--skip-aws-read", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-push", action="store_true")
    parser.add_argument("--skip-migrate", action="store_true")
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--skip-service-stability", action="store_true")
    parser.add_argument(
        "--fair-value-safe-disable",
        action="store_true",
        help="Force the fair-value EventBridge schedule to DISABLED",
    )


def _load_cockpit_config(raw: Any) -> CockpitConfig | None:
    if raw is None:
        return None
    cockpit = _as_mapping(raw, "cockpit")
    return CockpitConfig(
        stack_name=_required_str(cockpit, "stack_name", "cockpit.stack_name"),
        service_name=_required_str(cockpit, "service_name", "cockpit.service_name"),
        template_file=_optional_str(
            cockpit,
            "template_file",
            "deploy/aws/ecs-fargate-dashboard.yaml",
        ),
        private_namespace_name=_optional_str(cockpit, "private_namespace_name", "alphadb.local"),
        runtime_mode=_optional_str(cockpit, "runtime_mode", "gated-live"),
        desired_count=_optional_int(cockpit, "desired_count", 1),
    )


def _load_brti_config(raw: Any) -> BrtiCollectorConfig | None:
    if raw is None:
        return None
    brti = _as_mapping(raw, "brti_collector")
    return BrtiCollectorConfig(
        stack_name=_required_str(brti, "stack_name", "brti_collector.stack_name"),
        service_name=_required_str(brti, "service_name", "brti_collector.service_name"),
        template_file=_optional_str(
            brti,
            "template_file",
            "deploy/aws/brti-live-collector.yaml",
        ),
        desired_count=_optional_int(brti, "desired_count", 1),
        index_id=_optional_str(brti, "index_id", "BRTI"),
        max_reconnects=_optional_str(brti, "max_reconnects", "1000000"),
        kalshi_websocket_url=_optional_str(
            brti,
            "kalshi_websocket_url",
            "wss://external-api-ws.kalshi.com/trade-api/ws/v2",
        ),
    )


def _load_fair_value_config(raw: Any) -> FairValueConfig | None:
    if raw is None:
        return None
    fair_value = _as_mapping(raw, "fair_value")
    return FairValueConfig(
        stack_name=_required_str(fair_value, "stack_name", "fair_value.stack_name"),
        service_name=_required_str(fair_value, "service_name", "fair_value.service_name"),
        template_file=_optional_str(
            fair_value,
            "template_file",
            "deploy/aws/fair-value-live-trading-job.yaml",
        ),
        report_bucket_name=_required_str(
            fair_value,
            "report_bucket_name",
            "fair_value.report_bucket_name",
        ),
        report_prefix=_optional_str(fair_value, "report_prefix", "fair-value-live"),
        schedule_expression=_optional_str(fair_value, "schedule_expression", "rate(1 minute)"),
        schedule_policy=_required_str(
            fair_value,
            "schedule_policy",
            "fair_value.schedule_policy",
        ),
        min_edge_values=_optional_str(fair_value, "min_edge_values", "0.0,0.05,0.10"),
        min_contract_price=_optional_str(fair_value, "min_contract_price", "0.25"),
    )


def _validate_surface_sections(profile: DeploymentProfile, selected: Sequence[str]) -> None:
    missing: list[str] = []
    if "cockpit" in selected and profile.cockpit is None:
        missing.append("cockpit")
    if "brti-collector" in selected and profile.brti_collector is None:
        missing.append("brti_collector")
    if "fair-value" in selected and profile.fair_value is None:
        missing.append("fair_value")
    if missing:
        joined = ", ".join(missing)
        raise DeploymentProfileError(f"deployment profile missing selected surface section(s): {joined}")
    if "fair-value" in selected:
        assert profile.fair_value is not None
        policy = _normalize_schedule_policy(profile.fair_value.schedule_policy)
        if policy == "enable":
            raise DeploymentProfileError(
                "fair-value schedule enablement is rejected in the orchestrator MVP"
            )


def _validate_observed_identity(profile: DeploymentProfile, identity: Mapping[str, Any]) -> None:
    if identity.get("status") != "available":
        return
    observed = str(identity.get("account_id") or "")
    if observed and observed != profile.account_id:
        raise DeploymentProfileError(
            f"observed AWS account {observed} does not match profile account {profile.account_id}"
        )


def _surface_plan_dict(resolved: ResolvedDeployment) -> dict[str, Any]:
    surfaces: dict[str, Any] = {}
    profile = resolved.profile
    if "cockpit" in resolved.selected_surfaces:
        assert profile.cockpit is not None
        surfaces["cockpit"] = {
            "stack_name": profile.cockpit.stack_name,
            "service_names": {
                "cockpit": f"{profile.cockpit.service_name}-cockpit",
                "alphadb_api": f"{profile.cockpit.service_name}-alphadb-api",
            },
            "public_surface": "Cockpit",
            "private_api": "AlphaDB API",
            "image_uris": {
                "cockpit": resolved.images.cockpit_uri,
                "runtime": resolved.images.runtime_uri,
            },
            "smoke_gates": {
                "migrations": "skipped" if resolved.skip_migrate else "default",
                "readiness_seed": "skipped" if resolved.skip_migrate else "default",
                "deployment_smoke": "skipped" if resolved.skip_migrate else "default",
                "cockpit_smoke": "skipped" if resolved.skip_smoke else "default",
            },
        }
    if "brti-collector" in resolved.selected_surfaces:
        assert profile.brti_collector is not None
        surfaces["brti-collector"] = {
            "stack_name": profile.brti_collector.stack_name,
            "service_name": profile.brti_collector.service_name,
            "desired_count": profile.brti_collector.desired_count,
            "image_uri": resolved.images.runtime_uri,
            "network_ids": list(profile.network.worker_subnet_ids),
            "status_gate": "skipped" if resolved.skip_service_stability else "service-stability",
        }
    if "fair-value" in resolved.selected_surfaces:
        assert profile.fair_value is not None
        surfaces["fair-value"] = {
            "stack_name": profile.fair_value.stack_name,
            "service_name": profile.fair_value.service_name,
            "image_uri": resolved.images.runtime_uri,
            "network_ids": list(profile.network.worker_subnet_ids),
            "schedule": resolved.fair_value_schedule,
            "live_authority_enablement": "rejected-by-mvp",
        }
    return surfaces


def _run_api_command(
    resolved: ResolvedDeployment,
    command_args: Sequence[str],
    *,
    runner: CommandRunner,
) -> None:
    assert resolved.profile.cockpit is not None
    stack_name = resolved.profile.cockpit.stack_name
    cluster = _stack_output(resolved, stack_name, "ClusterName", runner=runner)
    task_definition = _stack_output(
        resolved,
        stack_name,
        "AlphaDbApiTaskDefinitionArn",
        runner=runner,
    )
    security_group = _stack_output(
        resolved,
        stack_name,
        "AlphaDbApiSecurityGroupId",
        runner=runner,
    )
    subnets = _stack_output(resolved, stack_name, "PrivateSubnetIds", runner=runner)
    overrides = json.dumps(
        {"containerOverrides": [{"name": "api", "command": list(command_args)}]}
    )
    task = runner.run(
        [
            *_aws_base(resolved.profile),
            "ecs",
            "run-task",
            "--cluster",
            cluster,
            "--launch-type",
            "FARGATE",
            "--task-definition",
            task_definition,
            "--network-configuration",
            (
                "awsvpcConfiguration="
                f"{{subnets=[{subnets}],securityGroups=[{security_group}],"
                f"assignPublicIp={resolved.profile.network.assign_public_ip}}}"
            ),
            "--overrides",
            overrides,
            "--query",
            "tasks[0].taskArn",
            "--output",
            "text",
        ],
        capture_output=True,
    ).stdout.strip()
    if not task or task == "None":
        raise DeploymentApplyError(f"failed to start ECS one-off task: {' '.join(command_args)}")
    runner.run([*_aws_base(resolved.profile), "ecs", "wait", "tasks-stopped", "--cluster", cluster, "--tasks", task])
    exit_code = runner.run(
        [
            *_aws_base(resolved.profile),
            "ecs",
            "describe-tasks",
            "--cluster",
            cluster,
            "--tasks",
            task,
            "--query",
            "tasks[0].containers[?name=='api'].exitCode | [0]",
            "--output",
            "text",
        ],
        capture_output=True,
    ).stdout.strip()
    if exit_code != "0":
        stopped_reason = runner.run(
            [
                *_aws_base(resolved.profile),
                "ecs",
                "describe-tasks",
                "--cluster",
                cluster,
                "--tasks",
                task,
                "--query",
                "tasks[0].stoppedReason",
                "--output",
                "text",
            ],
            capture_output=True,
            check=False,
        ).stdout.strip()
        raise DeploymentApplyError(
            f"ECS one-off failed: {' '.join(command_args)}; "
            f"task={task} exit_code={exit_code} stopped_reason={stopped_reason}"
        )


def _stack_output(
    resolved: ResolvedDeployment,
    stack_name: str,
    key: str,
    *,
    runner: CommandRunner,
) -> str:
    return runner.run(
        [
            *_aws_base(resolved.profile),
            "cloudformation",
            "describe-stacks",
            "--stack-name",
            stack_name,
            "--query",
            f"Stacks[0].Outputs[?OutputKey=='{key}'].OutputValue | [0]",
            "--output",
            "text",
        ],
        capture_output=True,
    ).stdout.strip()


def _stack_name(profile: DeploymentProfile, surface: str) -> str:
    if surface == "cockpit":
        assert profile.cockpit is not None
        return profile.cockpit.stack_name
    if surface == "brti-collector":
        assert profile.brti_collector is not None
        return profile.brti_collector.stack_name
    if surface == "fair-value":
        assert profile.fair_value is not None
        return profile.fair_value.stack_name
    raise DeploymentProfileError(f"unsupported surface: {surface}")


def _aws_base(profile: DeploymentProfile) -> list[str]:
    return ["aws", "--profile", profile.aws_profile, "--region", profile.region]


def _canonical_surface(value: str) -> str:
    key = value.strip().lower().replace("_", "-")
    if key in SURFACE_ALIASES:
        return SURFACE_ALIASES[key]
    if key in REJECTED_SURFACES:
        raise DeploymentProfileError(
            "expensive-yes is outside the orchestrator MVP because its current "
            "AWS path defaults to an enabled schedule without the fair-value safety gates"
        )
    if key in API_SURFACES:
        raise DeploymentProfileError(
            "AlphaDB API is deployed as the private API inside the cockpit surface; "
            "select cockpit rather than a separate api surface"
        )
    raise DeploymentProfileError(
        f"unsupported AWS deployment surface {value!r}; supported surfaces are "
        f"{', '.join(SURFACE_ORDER)}"
    )


def _normalize_schedule_policy(value: str) -> str:
    key = value.strip().lower().replace("_", "-")
    if key in {"preserve", "preserve-observed"}:
        return "preserve"
    if key in {"disable", "disabled", "safe-disable", "safe-disabled"}:
        return "disable"
    if key in {"enable", "enabled"}:
        return "enable"
    raise DeploymentProfileError(
        "fair_value.schedule_policy must be preserve or disable; enable is rejected"
    )


def _load_json_or_yaml(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeploymentProfileError(f"deployment profile could not be read: {path}") from exc
    try:
        if path.suffix.lower() == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise DeploymentProfileError(f"deployment profile is not valid JSON/YAML: {path}") from exc


def _as_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DeploymentProfileError(f"{path} must be a mapping")
    return value


def _required_mapping(parent: Mapping[str, Any], key: str, path: str) -> Mapping[str, Any]:
    if key not in parent:
        raise DeploymentProfileError(f"missing required deployment profile field: {path}")
    return _as_mapping(parent[key], path)


def _required_str(parent: Mapping[str, Any], key: str, path: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DeploymentProfileError(f"missing required deployment profile field: {path}")
    return value.strip()


def _optional_str(parent: Mapping[str, Any], key: str, default: str) -> str:
    value = parent.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise DeploymentProfileError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_int(parent: Mapping[str, Any], key: str, default: int) -> int:
    value = parent.get(key, default)
    if not isinstance(value, int) or value < 0:
        raise DeploymentProfileError(f"{key} must be a non-negative integer")
    return value


def _required_str_list(parent: Mapping[str, Any], key: str, path: str) -> tuple[str, ...]:
    if key not in parent:
        raise DeploymentProfileError(f"missing required deployment profile field: {path}")
    return _str_list(parent[key], path)


def _optional_str_list(
    parent: Mapping[str, Any],
    key: str,
    path: str,
    *,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    if key not in parent:
        return default
    return _str_list(parent[key], path)


def _str_list(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise DeploymentProfileError(f"{path} must be a list of strings")
    strings = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    if len(strings) != len(value) or not strings:
        raise DeploymentProfileError(f"{path} must be a non-empty list of strings")
    return strings


def _outputs_to_dict(outputs: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in outputs:
        key = item.get("OutputKey")
        value = item.get("OutputValue")
        if isinstance(key, str) and value is not None:
            result[key] = str(value)
    return result


def _previous_task_definition(outputs: Mapping[str, str]) -> str | None:
    for key in (
        "TaskDefinitionArn",
        "AlphaDbApiTaskDefinitionArn",
        "CollectorTaskDefinitionArn",
    ):
        if outputs.get(key):
            return outputs[key]
    return None


def _unavailable_from_completed(label: str, completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
    return {"status": "unavailable", "resource": label, "detail": detail}


def _git_output(command: Sequence[str]) -> str:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise DeploymentProfileError(f"git command failed: {' '.join(command)}: {detail}")
    return completed.stdout.strip()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
