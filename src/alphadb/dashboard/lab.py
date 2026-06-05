"""Lab entries, experiment notes, and heuristic insights."""

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


LAB_KINDS = {"research_idea", "experiment"}
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
    kind: str
    title: str
    hypothesis: str
    brief: str
    status: str
    verdict: str | None
    unsupported_reasons: Sequence[str]
    closest_templates: Sequence[str]
    missing_capabilities: Sequence[str]
    dataset_snapshot_id: str | None
    strategy_snapshot_id: str | None
    metrics: Mapping[str, Any]
    metadata: Mapping[str, Any]
    created_at: datetime
    updated_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "lab_entry_id": self.lab_entry_id,
            "kind": self.kind,
            "title": self.title,
            "hypothesis": self.hypothesis,
            "brief": self.brief,
            "status": self.status,
            "verdict": self.verdict,
            "unsupported_reasons": list(self.unsupported_reasons),
            "closest_templates": list(self.closest_templates),
            "missing_capabilities": list(self.missing_capabilities),
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "strategy_snapshot_id": self.strategy_snapshot_id,
            "metrics": dict(self.metrics),
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class LabNote:
    note_id: str
    lab_entry_id: str
    note_type: str
    body: str
    metadata: Mapping[str, Any]
    created_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id,
            "lab_entry_id": self.lab_entry_id,
            "note_type": self.note_type,
            "body": self.body,
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class LabRunSummary:
    run_summary_id: str
    lab_entry_id: str
    run_id: str | None
    run_mode: str
    metrics: Mapping[str, Any]
    summary: Mapping[str, Any]
    created_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_summary_id": self.run_summary_id,
            "lab_entry_id": self.lab_entry_id,
            "run_id": self.run_id,
            "run_mode": self.run_mode,
            "metrics": dict(self.metrics),
            "summary": dict(self.summary),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class LabInsight:
    insight_id: str
    insight_type: str
    text: str
    related_lab_entry_ids: Sequence[str]
    related_dataset_snapshot_ids: Sequence[str]
    related_strategy_snapshot_ids: Sequence[str]
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
            "related_dataset_snapshot_ids": list(self.related_dataset_snapshot_ids),
            "related_strategy_snapshot_ids": list(self.related_strategy_snapshot_ids),
            "confidence": self.confidence,
            "source": self.source,
            "status": self.status,
            "metadata": dict(self.metadata),
            "created_at": None if self.created_at is None else self.created_at.isoformat(),
        }


class DashboardLabRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def list_entries(self, *, kind: str | None = None, limit: int = 50) -> list[LabEntry]:
        OperationalStateRepository(self.database_url).apply_migrations()
        params: tuple[Any, ...]
        where = ""
        if kind:
            if kind not in LAB_KINDS:
                raise ValueError("lab entry kind must be research_idea or experiment")
            where = "where kind = %s"
            params = (kind, _bounded_limit(limit))
        else:
            params = (_bounded_limit(limit),)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select *
                    from lab_entries
                    {where}
                    order by updated_at desc, lab_entry_id
                    limit %s
                    """,
                    params,
                )
                rows = cursor.fetchall()
        return [_entry_from_row(row) for row in rows]

    def get_entry(self, lab_entry_id: str) -> dict[str, Any]:
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select * from lab_entries where lab_entry_id = %s", (lab_entry_id,))
                entry_row = cursor.fetchone()
                if entry_row is None:
                    raise KeyError(f"unknown lab entry: {lab_entry_id}")
                cursor.execute(
                    """
                    select *
                    from lab_entry_notes
                    where lab_entry_id = %s
                    order by created_at asc, note_id
                    """,
                    (lab_entry_id,),
                )
                notes = [_note_from_row(row).as_dict() for row in cursor.fetchall()]
                cursor.execute(
                    """
                    select *
                    from lab_entry_run_summaries
                    where lab_entry_id = %s
                    order by created_at asc, run_summary_id
                    """,
                    (lab_entry_id,),
                )
                runs = [_run_summary_from_row(row).as_dict() for row in cursor.fetchall()]
        return {"entry": _entry_from_row(entry_row).as_dict(), "notes": notes, "runs": runs}

    def save_entry(
        self,
        *,
        title: str,
        kind: str,
        hypothesis: str = "",
        brief: str = "",
        status: str = "active",
        verdict: str | None = None,
        unsupported_reasons: Sequence[str] | None = None,
        closest_templates: Sequence[str] | None = None,
        missing_capabilities: Sequence[str] | None = None,
        dataset_snapshot_id: str | None = None,
        strategy_snapshot_id: str | None = None,
        metrics: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        lab_entry_id: str | None = None,
    ) -> LabEntry:
        if kind not in LAB_KINDS:
            raise ValueError("lab entry kind must be research_idea or experiment")
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
                        kind,
                        title,
                        hypothesis,
                        brief,
                        status,
                        verdict,
                        unsupported_reasons,
                        closest_templates,
                        missing_capabilities,
                        dataset_snapshot_id,
                        strategy_snapshot_id,
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
                        unsupported_reasons = excluded.unsupported_reasons,
                        closest_templates = excluded.closest_templates,
                        missing_capabilities = excluded.missing_capabilities,
                        dataset_snapshot_id = excluded.dataset_snapshot_id,
                        strategy_snapshot_id = excluded.strategy_snapshot_id,
                        metrics = excluded.metrics,
                        metadata = excluded.metadata,
                        updated_at = now()
                    returning *
                    """,
                    (
                        lab_entry_id,
                        kind,
                        clean_title,
                        str(hypothesis or "")[:8_000],
                        str(brief or "")[:8_000],
                        str(status or "active")[:80],
                        verdict,
                        Jsonb(list(unsupported_reasons or [])),
                        Jsonb(list(closest_templates or [])),
                        Jsonb(list(missing_capabilities or [])),
                        dataset_snapshot_id,
                        strategy_snapshot_id,
                        Jsonb(dict(metrics or {})),
                        Jsonb(dict(metadata or {})),
                    ),
                )
                row = cursor.fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError("lab entry save returned no row")
        return _entry_from_row(row)

    def add_note(
        self,
        *,
        lab_entry_id: str,
        note_type: str,
        body: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> LabNote:
        if note_type not in {"human", "agent"}:
            raise ValueError("lab note_type must be human or agent")
        note_id = f"note_{uuid4().hex[:12]}"
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into lab_entry_notes (note_id, lab_entry_id, note_type, body, metadata)
                    values (%s, %s, %s, %s, %s)
                    returning *
                    """,
                    (
                        note_id,
                        lab_entry_id,
                        note_type,
                        str(body or "")[:8_000],
                        Jsonb(dict(metadata or {})),
                    ),
                )
                row = cursor.fetchone()
                cursor.execute("update lab_entries set updated_at = now() where lab_entry_id = %s", (lab_entry_id,))
            connection.commit()
        if row is None:
            raise RuntimeError("lab note insert returned no row")
        return _note_from_row(row)

    def add_run_summary(
        self,
        *,
        lab_entry_id: str,
        run_mode: str,
        run_id: str | None = None,
        metrics: Mapping[str, Any] | None = None,
        summary: Mapping[str, Any] | None = None,
    ) -> LabRunSummary:
        run_summary_id = f"runsum_{uuid4().hex[:12]}"
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into lab_entry_run_summaries (
                        run_summary_id, lab_entry_id, run_id, run_mode, metrics, summary
                    )
                    values (%s, %s, %s, %s, %s, %s)
                    returning *
                    """,
                    (
                        run_summary_id,
                        lab_entry_id,
                        run_id,
                        str(run_mode or "unknown")[:80],
                        Jsonb(dict(metrics or {})),
                        Jsonb(dict(summary or {})),
                    ),
                )
                row = cursor.fetchone()
                cursor.execute("update lab_entries set updated_at = now() where lab_entry_id = %s", (lab_entry_id,))
            connection.commit()
        if row is None:
            raise RuntimeError("lab run summary insert returned no row")
        return _run_summary_from_row(row)

    def set_verdict(self, *, lab_entry_id: str, verdict: str) -> LabEntry:
        if verdict not in LAB_VERDICTS:
            raise ValueError("lab verdict must be continue, revise, or kill")
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update lab_entries
                    set verdict = %s, status = %s, updated_at = now()
                    where lab_entry_id = %s
                    returning *
                    """,
                    (verdict, verdict, lab_entry_id),
                )
                row = cursor.fetchone()
            connection.commit()
        if row is None:
            raise KeyError(f"unknown lab entry: {lab_entry_id}")
        return _entry_from_row(row)

    def list_insights(self, *, limit: int = 20) -> list[LabInsight]:
        OperationalStateRepository(self.database_url).apply_migrations()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select *
                    from lab_semantic_insights
                    where status = 'active'
                    order by created_at desc, insight_id
                    limit %s
                    """,
                    (_bounded_limit(limit),),
                )
                rows = cursor.fetchall()
        return [_insight_from_row(row) for row in rows]

    def generate_and_save_insights(self) -> list[LabInsight]:
        entries = self.list_entries(limit=200)
        insights = generate_heuristic_insights(entries)
        if not insights:
            return []
        OperationalStateRepository(self.database_url).apply_migrations()
        saved: list[LabInsight] = []
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                for insight in insights:
                    cursor.execute(
                        """
                        insert into lab_semantic_insights (
                            insight_id,
                            insight_type,
                            text,
                            related_lab_entry_ids,
                            related_dataset_snapshot_ids,
                            related_strategy_snapshot_ids,
                            confidence,
                            source,
                            status,
                            metadata
                        )
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        returning *
                        """,
                        (
                            insight.insight_id,
                            insight.insight_type,
                            insight.text,
                            list(insight.related_lab_entry_ids),
                            list(insight.related_dataset_snapshot_ids),
                            list(insight.related_strategy_snapshot_ids),
                            insight.confidence,
                            insight.source,
                            insight.status,
                            Jsonb(dict(insight.metadata)),
                        ),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        saved.append(_insight_from_row(row))
            connection.commit()
        return saved


def research_idea_from_compile_result(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "research_idea",
        "title": str(result.get("title") or "Unsupported strategy brief")[:160],
        "hypothesis": str(result.get("brief") or "")[:8_000],
        "brief": str(result.get("brief") or "")[:8_000],
        "status": "active",
        "unsupported_reasons": list(result.get("unsupported_reasons") or []),
        "closest_templates": list(result.get("closest_templates") or []),
        "missing_capabilities": list(result.get("missing_capabilities") or []),
        "metadata": {
            "source": "spec_compiler",
            "compile_status": result.get("status"),
            "missing_fields": list(result.get("missing_fields") or []),
            "questions": list(result.get("questions") or []),
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
            ids = tuple(entry.lab_entry_id for entry in matches[:8])
            insights.append(
                LabInsight(
                    insight_id=f"ins_{uuid4().hex[:12]}",
                    insight_type="pattern",
                    text=f"{topic.title()} appears across {len(matches)} Lab entries. Review shared datasets and verdicts before starting a new branch.",
                    related_lab_entry_ids=ids,
                    related_dataset_snapshot_ids=tuple(
                        entry.dataset_snapshot_id
                        for entry in matches
                        if entry.dataset_snapshot_id is not None
                    ),
                    related_strategy_snapshot_ids=tuple(
                        entry.strategy_snapshot_id
                        for entry in matches
                        if entry.strategy_snapshot_id is not None
                    ),
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
                    text=f"{topic.title()} has multiple killed experiments. Treat the next test as a narrow falsification, not a broad retry.",
                    related_lab_entry_ids=tuple(related),
                    related_dataset_snapshot_ids=(),
                    related_strategy_snapshot_ids=(),
                    confidence=min(0.88, 0.5 + count * 0.1),
                    source="heuristic",
                    status="active",
                    metadata={"topic": topic, "killed_count": count},
                )
            )

    capability_counter = Counter(
        capability
        for entry in entries
        for capability in entry.missing_capabilities
        if isinstance(capability, str) and capability
    )
    for capability, count in capability_counter.most_common(3):
        if count >= 1:
            related = [
                entry.lab_entry_id
                for entry in entries
                if capability in set(entry.missing_capabilities)
            ][:8]
            insights.append(
                LabInsight(
                    insight_id=f"ins_{uuid4().hex[:12]}",
                    insight_type="suggestion",
                    text=f"{capability.replace('_', ' ')} blocks {count} Research Idea{'s' if count != 1 else ''}. Consider making it an explicit capability ticket.",
                    related_lab_entry_ids=tuple(related),
                    related_dataset_snapshot_ids=(),
                    related_strategy_snapshot_ids=(),
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


def _clean_text(value: Any, *, default: str, max_length: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return (text or default)[:max_length]


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit or 50), 200))


def _entry_from_row(row: Mapping[str, Any]) -> LabEntry:
    return LabEntry(
        lab_entry_id=str(row["lab_entry_id"]),
        kind=str(row["kind"]),
        title=str(row["title"]),
        hypothesis=str(row["hypothesis"]),
        brief=str(row["brief"]),
        status=str(row["status"]),
        verdict=None if row["verdict"] is None else str(row["verdict"]),
        unsupported_reasons=_json_strings(row["unsupported_reasons"]),
        closest_templates=_json_strings(row["closest_templates"]),
        missing_capabilities=_json_strings(row["missing_capabilities"]),
        dataset_snapshot_id=None if row["dataset_snapshot_id"] is None else str(row["dataset_snapshot_id"]),
        strategy_snapshot_id=None if row["strategy_snapshot_id"] is None else str(row["strategy_snapshot_id"]),
        metrics=_json_mapping(row["metrics"]),
        metadata=_json_mapping(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _note_from_row(row: Mapping[str, Any]) -> LabNote:
    return LabNote(
        note_id=str(row["note_id"]),
        lab_entry_id=str(row["lab_entry_id"]),
        note_type=str(row["note_type"]),
        body=str(row["body"]),
        metadata=_json_mapping(row["metadata"]),
        created_at=row["created_at"],
    )


def _run_summary_from_row(row: Mapping[str, Any]) -> LabRunSummary:
    return LabRunSummary(
        run_summary_id=str(row["run_summary_id"]),
        lab_entry_id=str(row["lab_entry_id"]),
        run_id=None if row["run_id"] is None else str(row["run_id"]),
        run_mode=str(row["run_mode"]),
        metrics=_json_mapping(row["metrics"]),
        summary=_json_mapping(row["summary"]),
        created_at=row["created_at"],
    )


def _insight_from_row(row: Mapping[str, Any]) -> LabInsight:
    return LabInsight(
        insight_id=str(row["insight_id"]),
        insight_type=str(row["insight_type"]),
        text=str(row["text"]),
        related_lab_entry_ids=_array_strings(row["related_lab_entry_ids"]),
        related_dataset_snapshot_ids=_array_strings(row["related_dataset_snapshot_ids"]),
        related_strategy_snapshot_ids=_array_strings(row["related_strategy_snapshot_ids"]),
        confidence=float(row["confidence"]),
        source=str(row["source"]),
        status=str(row["status"]),
        metadata=_json_mapping(row["metadata"]),
        created_at=row["created_at"],
    )


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


def _json_strings(value: Any) -> Sequence[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value]
    raise ValueError("expected JSON array from lab repository")


def _array_strings(value: Any) -> Sequence[str]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value]
    return _json_strings(value)


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
