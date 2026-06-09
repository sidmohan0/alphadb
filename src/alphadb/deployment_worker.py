"""Server-side worker for backend-mediated deployment intents."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alphadb.aws_deploy import (
    ResolvedDeployment,
    create_deployment_plan,
    write_deployment_manifest,
)
from alphadb.deployment_intents import DeploymentIntent, DeploymentIntentRepository

PlanFactory = Callable[..., ResolvedDeployment]
ManifestWriter = Callable[..., Path]


@dataclass(frozen=True)
class DeploymentWorkerResult:
    status: str
    worker_id: str
    deployment_intent_id: str | None
    detail: str
    intent: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "worker_id": self.worker_id,
            "deployment_intent_id": self.deployment_intent_id,
            "detail": self.detail,
            "intent": self.intent,
        }


class DeploymentIntentWorker:
    def __init__(
        self,
        repository: DeploymentIntentRepository,
        *,
        manifest_root: Path,
        plan_factory: PlanFactory = create_deployment_plan,
        manifest_writer: ManifestWriter = write_deployment_manifest,
    ) -> None:
        self.repository = repository
        self.manifest_root = manifest_root
        self.plan_factory = plan_factory
        self.manifest_writer = manifest_writer

    def run_once(self, *, worker_id: str) -> DeploymentWorkerResult:
        intent = self.repository.claim_next(worker_id=worker_id)
        if intent is None:
            return DeploymentWorkerResult(
                status="idle",
                worker_id=worker_id,
                deployment_intent_id=None,
                detail="no pending deployment intent",
            )
        try:
            planned = self._execute_plan(intent)
        except Exception as exc:
            failed = self.repository.mark_failed(
                intent.deployment_intent_id,
                error={
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "phase": "plan",
                    "mutates_aws": False,
                },
                evidence={
                    "mode": "plan",
                    "mutates_aws": False,
                    "status": "failed",
                },
            )
            return DeploymentWorkerResult(
                status="failed",
                worker_id=worker_id,
                deployment_intent_id=intent.deployment_intent_id,
                detail=str(exc),
                intent=failed.as_dict(),
            )
        return DeploymentWorkerResult(
            status="planned",
            worker_id=worker_id,
            deployment_intent_id=planned.deployment_intent_id,
            detail="deployment plan recorded",
            intent=planned.as_dict(),
        )

    def _execute_plan(self, intent: DeploymentIntent) -> DeploymentIntent:
        build_policy = dict(intent.build_policy)
        surfaces = list(intent.requested_surfaces)
        resolved = self.plan_factory(
            intent.profile_path,
            surfaces=surfaces,
            skip_aws_read=True,
            skip_build=bool(build_policy.get("skip_build", False)),
            skip_push=bool(build_policy.get("skip_push", False)),
            force_rebuild=bool(build_policy.get("force_rebuild", False)),
            skip_migrate=bool(build_policy.get("skip_release_check", False)),
            skip_smoke=bool(build_policy.get("skip_smoke", False)),
            skip_service_stability=bool(build_policy.get("skip_service_stability", False)),
            fair_value_safe_disable=_fair_value_safe_disable(intent.schedule_policy),
        )
        manifest_path = self.manifest_writer(
            resolved,
            mode="plan",
            manifest_root=self.manifest_root,
        )
        plan = resolved.plan_dict()
        rollback_pointers = _rollback_pointers_from_plan(plan)
        evidence = {
            "mode": "plan",
            "status": "passed",
            "mutates_aws": False,
            "skip_aws_read": True,
            "manifest_path": str(manifest_path),
            "deployment_id": resolved.deployment_id,
            "selected_surfaces": list(resolved.selected_surfaces),
            "plan": plan,
        }
        return self.repository.mark_planned(
            intent.deployment_intent_id,
            evidence=evidence,
            rollback_pointers=rollback_pointers,
            image_identities=plan.get("images", {}),
        )


def _fair_value_safe_disable(schedule_policy: Mapping[str, Any]) -> bool:
    fair_value = schedule_policy.get("fair-value") or schedule_policy.get("fair_value")
    if isinstance(fair_value, Mapping):
        action = str(fair_value.get("action") or fair_value.get("schedule_state") or "")
        return action.lower() == "disable"
    return str(fair_value or "").lower() == "disable"


def _rollback_pointers_from_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    observed_stacks = plan.get("observed_stacks")
    if not isinstance(observed_stacks, Mapping):
        return {}
    pointers: dict[str, Any] = {}
    for surface, stack in observed_stacks.items():
        if isinstance(stack, Mapping):
            pointers[str(surface)] = {
                "previous_stack_outputs": stack.get("outputs") or {},
                "status": stack.get("status"),
            }
    return pointers
