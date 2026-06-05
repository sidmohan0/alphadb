"""Lab memory entries and heuristic insights."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from alphadb.state.repository import OperationalStateRepository


LAB_VERDICTS = {"continue", "revise", "kill"}
INSIGHT_TYPES = {"pattern", "warning", "similarity", "suggestion"}
TOPIC_TERMS = (
    "funding",
    "whale",
    "volatility",
    "momentum",
    "reversal",
    "fair value",
    "model",
    "threshold",
    "weather",
    "sentiment",
    "coinbase",
)


@dataclass(frozen=True)
class LabEntry:
    lab_entry_id: str
    title: str
    hypothesis: str
    brief: str
    status: str
    verdict: str | None
    blockers: Sequence[Mapping[str, Any]]
    evidence: Sequence[Mapping[str, Any]]
    strategy: Mapping[str, Any]
    runs: Sequence[Mapping[str, Any]]
    notes: Sequence[Mapping[str, Any]]
    insights: Sequence[Mapping[str, Any]]
    metrics: Mapping[str, Any]
    metadata: Mapping[str, Any]
    created_at: datetime
    updated_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "lab_entry_id": self.lab_entry_id,
            "title": self.title,
            "hypothesis": self.hypothesis,
            "brief": self.brief,
            "status": self.status,
            "verdict": self.verdict,
            "blockers": [dict(item) for item in self.blockers],
            "evidence": [dict(item) for item in self.evidence],
            "strategy": dict(self.strategy),
            "runs": [dict(item) for item in self.runs],
            "notes": [dict(item) for item in self.notes],
            "insights": [dict(item) for item in self.insights],
            "metrics": dict(self.metrics),
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class LabInsight:
    insight_id: str
    insight_type: str
    text: str
    related_lab_entry_ids: Sequence[str]
    confidence: float
    source: str
    status: str
    metadata: Mapping[str, Any]
    created_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "insight_id": self.insight_id,
            "insight_type": self.insight_type,
            "text": self.text,
            "related_lab_entry_ids": list(self.related_lab_entry_ids),
            "confidence": self.confidence,
            "source": self.source,
            "status": self.status,
            "metadata": dict(self.metadata),
            "created_at": None if self.created_at is None else self.created_at.isoformat(),
        }


class DashboardLabRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def list_entries(self, *, limit: int = 50) -> list[LabEntry]:
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from lab_entries
                    order by updated_at desc, lab_entry_id
                    limit %s
                    """,
                    (_bounded_limit(limit),),
                )
                rows = cursor.fetchall()
        return [_entry_from_row(row) for row in rows]

    def get_entry(self, lab_entry_id: str) -> LabEntry:
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select * from lab_entries where lab_entry_id = %s", (lab_entry_id,))
                row = cursor.fetchone()
        if row is None:
            raise KeyError(f"unknown lab entry: {lab_entry_id}")
        return _entry_from_row(row)

    def save_entry(
        self,
        *,
        title: str,
        hypothesis: str = "",
        brief: str = "",
        status: str = "active",
        verdict: str | None = None,
        blockers: Sequence[Mapping[str, Any]] | None = None,
        evidence: Sequence[Mapping[str, Any]] | None = None,
        strategy: Mapping[str, Any] | None = None,
        runs: Sequence[Mapping[str, Any]] | None = None,
        notes: Sequence[Mapping[str, Any]] | None = None,
        insights: Sequence[Mapping[str, Any]] | None = None,
        metrics: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        lab_entry_id: str | None = None,
    ) -> LabEntry:
        if verdict is not None and verdict not in LAB_VERDICTS:
            raise ValueError("lab verdict must be continue, revise, or kill")
        clean_title = _clean_text(title, default="Untitled lab entry", max_length=160)
        lab_entry_id = lab_entry_id or f"lab_{uuid4().hex[:12]}"
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into lab_entries (
                        lab_entry_id,
                        title,
                        hypothesis,
                        brief,
                        status,
                        verdict,
                        blockers,
                        evidence,
                        strategy,
                        runs,
                        notes,
                        insights,
                        metrics,
                        metadata
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (lab_entry_id) do update set
                        title = excluded.title,
                        hypothesis = excluded.hypothesis,
                        brief = excluded.brief,
                        status = excluded.status,
                        verdict = excluded.verdict,
                        blockers = excluded.blockers,
                        evidence = excluded.evidence,
                        strategy = excluded.strategy,
                        runs = excluded.runs,
                        notes = excluded.notes,
                        insights = excluded.insights,
                        metrics = excluded.metrics,
                        metadata = excluded.metadata,
                        updated_at = now()
                    returning *
                    """,
                    (
                        lab_entry_id,
                        clean_title,
                        str(hypothesis or "")[:8_000],
                        str(brief or "")[:8_000],
                        str(status or "active")[:80],
                        verdict,
                        Jsonb([dict(item) for item in blockers or []]),
                        Jsonb([dict(item) for item in evidence or []]),
                        Jsonb(dict(strategy or {})),
                        Jsonb([dict(item) for item in runs or []]),
                        Jsonb([dict(item) for item in notes or []]),
                        Jsonb([dict(item) for item in insights or []]),
                        Jsonb(dict(metrics or {})),
                        Jsonb(dict(metadata or {})),
                    ),
                )
                row = cursor.fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError("lab entry save returned no row")
        return _entry_from_row(row)

    def list_insights(self, *, limit: int = 20) -> list[LabInsight]:
        return generate_heuristic_insights(self.list_entries(limit=200))[:_bounded_limit(limit)]


def lab_entry_from_compile_result(result: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    for reason in _strings(result.get("unsupported_reasons")):
        blockers.append({"type": "unsupported_reason", "text": reason})
    for capability in _strings(result.get("missing_capabilities")):
        blockers.append({"type": "missing_capability", "name": capability})
    for field in _strings(result.get("missing_fields")):
        blockers.append({"type": "missing_field", "name": field})
    for question in _strings(result.get("questions")):
        blockers.append({"type": "question", "text": question})

    return {
        "title": str(result.get("title") or "Blocked strategy brief")[:160],
        "hypothesis": str(result.get("brief") or "")[:8_000],
        "brief": str(result.get("brief") or "")[:8_000],
        "status": "active",
        "blockers": blockers,
        "strategy": {"compile_result": dict(result)},
        "metadata": {
            "source": "spec_compiler",
            "compile_status": result.get("status"),
            "closest_templates": _strings(result.get("closest_templates")),
        },
    }


def generate_heuristic_insights(entries: Sequence[LabEntry]) -> list[LabInsight]:
    insights: list[LabInsight] = []
    by_topic: dict[str, list[LabEntry]] = {topic: [] for topic in TOPIC_TERMS}
    for entry in entries:
        text = f"{entry.title} {entry.hypothesis} {entry.brief}".lower()
        for topic in TOPIC_TERMS:
            if topic in text:
                by_topic[topic].append(entry)

    for topic, matches in by_topic.items():
        if len(matches) >= 2:
            insights.append(
                LabInsight(
                    insight_id=f"ins_{uuid4().hex[:12]}",
                    insight_type="pattern",
                    text=f"{topic.title()} appears across {len(matches)} Lab entries. Review shared evidence and verdicts before starting a new branch.",
                    related_lab_entry_ids=tuple(entry.lab_entry_id for entry in matches[:8]),
                    confidence=min(0.9, 0.45 + len(matches) * 0.1),
                    source="heuristic",
                    status="active",
                    metadata={"topic": topic, "match_count": len(matches)},
                )
            )

    killed_topics = _topic_verdict_counts(entries, verdict="kill")
    for topic, count in killed_topics.items():
        if count >= 2:
            related = [entry.lab_entry_id for entry in entries if _contains_topic(entry, topic)][:8]
            insights.append(
                LabInsight(
                    insight_id=f"ins_{uuid4().hex[:12]}",
                    insight_type="warning",
                    text=f"{topic.title()} has multiple killed Lab entries. Treat the next test as a narrow falsification, not a broad retry.",
                    related_lab_entry_ids=tuple(related),
                    confidence=min(0.88, 0.5 + count * 0.1),
                    source="heuristic",
                    status="active",
                    metadata={"topic": topic, "killed_count": count},
                )
            )

    capability_counter = Counter(
        str(blocker.get("name") or blocker.get("text") or "")
        for entry in entries
        for blocker in entry.blockers
        if blocker.get("type") == "missing_capability"
    )
    for capability, count in capability_counter.most_common(3):
        if count >= 1 and capability:
            related = [
                entry.lab_entry_id
                for entry in entries
                if capability in _entry_missing_capabilities(entry)
            ][:8]
            insights.append(
                LabInsight(
                    insight_id=f"ins_{uuid4().hex[:12]}",
                    insight_type="suggestion",
                    text=f"{capability.replace('_', ' ')} blocks {count} Lab entr{'y' if count == 1 else 'ies'}. Consider making it explicit next work.",
                    related_lab_entry_ids=tuple(related),
                    confidence=0.62,
                    source="heuristic",
                    status="active",
                    metadata={"capability": capability, "blocked_entries": count},
                )
            )

    return insights[:12]


def _topic_verdict_counts(entries: Sequence[LabEntry], *, verdict: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for entry in entries:
        if entry.verdict != verdict and entry.status != verdict:
            continue
        for topic in TOPIC_TERMS:
            if _contains_topic(entry, topic):
                counter[topic] += 1
    return counter


def _contains_topic(entry: LabEntry, topic: str) -> bool:
    return topic in f"{entry.title} {entry.hypothesis} {entry.brief}".lower()


def _entry_missing_capabilities(entry: LabEntry) -> set[str]:
    return {
        str(blocker.get("name") or blocker.get("text") or "")
        for blocker in entry.blockers
        if blocker.get("type") == "missing_capability"
    }


def _clean_text(value: Any, *, default: str, max_length: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return (text or default)[:max_length]


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit or 50), 200))


def _entry_from_row(row: Mapping[str, Any]) -> LabEntry:
    blockers = _json_objects(row.get("blockers"))
    if not blockers:
        blockers = _legacy_blockers(row)
    evidence = _json_objects(row.get("evidence"))
    legacy_dataset_id = row.get("dataset_snapshot_id")
    if legacy_dataset_id is not None and not evidence:
        evidence = [{"source": "dataset_snapshot", "id": str(legacy_dataset_id)}]
    strategy = _json_mapping(row.get("strategy"))
    legacy_strategy_id = row.get("strategy_snapshot_id")
    if legacy_strategy_id is not None and not strategy:
        strategy = {"strategy_snapshot_id": str(legacy_strategy_id)}
    return LabEntry(
        lab_entry_id=str(row["lab_entry_id"]),
        title=str(row["title"]),
        hypothesis=str(row["hypothesis"]),
        brief=str(row["brief"]),
        status=str(row["status"]),
        verdict=None if row["verdict"] is None else str(row["verdict"]),
        blockers=blockers,
        evidence=evidence,
        strategy=strategy,
        runs=_json_objects(row.get("runs")),
        notes=_json_objects(row.get("notes")),
        insights=_json_objects(row.get("insights")),
        metrics=_json_mapping(row.get("metrics")),
        metadata=_json_mapping(row.get("metadata")),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _legacy_blockers(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for reason in _json_strings(row.get("unsupported_reasons")):
        blockers.append({"type": "unsupported_reason", "text": reason})
    for template in _json_strings(row.get("closest_templates")):
        blockers.append({"type": "closest_template", "name": template})
    for capability in _json_strings(row.get("missing_capabilities")):
        blockers.append({"type": "missing_capability", "name": capability})
    return blockers


def _json_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value is None:
        return {}
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, Mapping):
            return dict(parsed)
    raise ValueError("expected JSON object from lab repository")


def _json_objects(value: Any) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items: list[Mapping[str, Any]] = []
        for item in value:
            if isinstance(item, Mapping):
                items.append(dict(item))
            elif item is not None:
                items.append({"text": str(item)})
        return items
    raise ValueError("expected JSON array from lab repository")


def _json_strings(value: Any) -> Sequence[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value]
    raise ValueError("expected JSON array from lab repository")


def _strings(value: Any) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value if str(item).strip()]
    return []


def json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [json_ready(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
