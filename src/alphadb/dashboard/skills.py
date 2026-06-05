"""Agent Terminal skill registry for the dashboard API."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DashboardSkill:
    name: str
    description: str
    parameters: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": dict(self.parameters),
        }


SKILLS: tuple[DashboardSkill, ...] = (
    DashboardSkill(
        name="capabilities.list",
        description="List available dashboard skills and their parameters.",
        parameters={},
    ),
    DashboardSkill(
        name="live.summary",
        description="Return current live-operations status, runtime config, health, and recent runs.",
        parameters={},
    ),
    DashboardSkill(
        name="strategy.compile",
        description="Compile a Strategy Brief into a constrained Strategy Spec proposal.",
        parameters={"brief": "string", "title": "string?"},
    ),
    DashboardSkill(
        name="strategy.list",
        description="List saved Strategy Specs.",
        parameters={"limit": "integer?"},
    ),
    DashboardSkill(
        name="data.views.list",
        description="List curated Data Explorer views.",
        parameters={},
    ),
    DashboardSkill(
        name="data.view.query",
        description="Query a curated Data Explorer view with bounded filters.",
        parameters={"view_name": "string", "filters": "object?", "limit": "integer?"},
    ),
    DashboardSkill(
        name="data.snapshots.list",
        description="List saved dataset snapshots.",
        parameters={"limit": "integer?"},
    ),
    DashboardSkill(
        name="lab.entries.list",
        description="List Lab Research Ideas and Experiments.",
        parameters={"kind": "research_idea|experiment?", "limit": "integer?"},
    ),
    DashboardSkill(
        name="lab.insights.generate",
        description="Generate heuristic Lab insights from experiment history.",
        parameters={},
    ),
)

SKILL_MAP = {skill.name: skill for skill in SKILLS}


def capabilities_payload() -> dict[str, Any]:
    return {
        "service": "alphadb-dashboard",
        "version": "agent_first_mvp_v1",
        "skills": [skill.as_dict() for skill in SKILLS],
    }


def classify_terminal_request(payload: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    explicit_skill = str(payload.get("skill") or "").strip()
    if explicit_skill:
        if explicit_skill not in SKILL_MAP:
            raise KeyError(f"unknown skill: {explicit_skill}")
        params = payload.get("parameters")
        return explicit_skill, dict(params) if isinstance(params, Mapping) else {}

    message = str(payload.get("message") or payload.get("question") or "").strip()
    lowered = message.lower()
    if not message:
        raise ValueError("terminal request requires a message or skill")
    if lowered in {"help", "?", "capabilities"} or "what can you do" in lowered:
        return "capabilities.list", {}
    if any(term in lowered for term in ("live", "status", "runner", "health", "trading")):
        return "live.summary", {}
    if "compile" in lowered or "strategy brief" in lowered or "brief into" in lowered:
        return "strategy.compile", {"brief": message}
    if "strategy" in lowered:
        return "strategy.list", {}
    if "data view" in lowered or "views" in lowered:
        return "data.views.list", {}
    if "dataset" in lowered or "snapshot" in lowered:
        return "data.snapshots.list", {}
    if "insight" in lowered:
        return "lab.insights.generate", {}
    if "lab" in lowered or "experiment" in lowered or "research idea" in lowered:
        return "lab.entries.list", {}
    return "live.summary", {"note": "No exact skill match; returned live summary as default."}


def terminal_response(
    *,
    skill: str,
    result: Any,
    note: str | None = None,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    if note:
        messages.append({"role": "agent", "content": note})
    messages.append({"role": "agent", "content": _summary_for(skill, result)})
    return {"skill": skill, "messages": messages, "result": result}


def _summary_for(skill: str, result: Any) -> str:
    if skill == "live.summary" and isinstance(result, Mapping):
        status = result.get("live_status") if isinstance(result.get("live_status"), Mapping) else {}
        return (
            f"Live status: {status.get('decision_outcome', 'unknown')}. "
            f"Market: {status.get('current_market_ticker') or 'none'}."
        )
    if skill == "strategy.compile" and isinstance(result, Mapping):
        return (
            f"Compile status: {result.get('status', 'unknown')}. "
            f"Template: {result.get('selected_template') or 'none'}."
        )
    if isinstance(result, Sequence) and not isinstance(result, (str, bytes)):
        return f"{skill} returned {len(result)} item{'s' if len(result) != 1 else ''}."
    if isinstance(result, Mapping):
        if skill == "capabilities.list":
            skills = result.get("skills")
            if isinstance(skills, Sequence) and not isinstance(skills, (str, bytes)):
                return f"{len(skills)} dashboard skills are available."
        row_count = result.get("row_count")
        if row_count is not None:
            return f"{skill} returned {row_count} row{'s' if row_count != 1 else ''}."
    return f"{skill} completed."
