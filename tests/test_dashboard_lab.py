from __future__ import annotations

from datetime import UTC, datetime

from alphadb.dashboard.lab import LabEntry, generate_heuristic_insights, research_idea_from_compile_result


def entry(
    lab_entry_id: str,
    title: str,
    *,
    verdict: str | None = None,
    missing_capabilities: tuple[str, ...] = (),
) -> LabEntry:
    now = datetime(2026, 6, 5, 12, tzinfo=UTC)
    return LabEntry(
        lab_entry_id=lab_entry_id,
        kind="experiment",
        title=title,
        hypothesis=title,
        brief=title,
        status=verdict or "active",
        verdict=verdict,
        unsupported_reasons=(),
        closest_templates=(),
        missing_capabilities=missing_capabilities,
        dataset_snapshot_id=None,
        strategy_snapshot_id=None,
        metrics={},
        metadata={},
        created_at=now,
        updated_at=now,
    )


def test_research_idea_from_compile_result_preserves_blockers() -> None:
    idea = research_idea_from_compile_result(
        {
            "title": "Portfolio branch",
            "brief": "Try a portfolio optimizer",
            "status": "unsupported",
            "unsupported_reasons": ["Portfolio-level allocation is not an MVP template."],
            "closest_templates": ["fair_value"],
            "missing_capabilities": ["portfolio_optimizer"],
            "missing_fields": [],
            "questions": [],
        }
    )

    assert idea["kind"] == "research_idea"
    assert idea["title"] == "Portfolio branch"
    assert idea["missing_capabilities"] == ["portfolio_optimizer"]
    assert idea["metadata"]["source"] == "spec_compiler"


def test_heuristic_insights_find_repeated_topics_and_capability_blocks() -> None:
    insights = generate_heuristic_insights(
        (
            entry("lab_1", "Funding reversal signal", missing_capabilities=("external_signal",)),
            entry("lab_2", "Funding plus volatility filter"),
            entry("lab_3", "Funding retry", verdict="kill"),
            entry("lab_4", "Funding late retry", verdict="kill"),
        )
    )

    types = {insight.insight_type for insight in insights}
    assert "pattern" in types
    assert "warning" in types
    assert "suggestion" in types
    assert any("Funding" in insight.text for insight in insights)
    assert any("external signal" in insight.text for insight in insights)
