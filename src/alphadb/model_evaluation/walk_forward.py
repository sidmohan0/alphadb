"""Walk-forward model evaluation reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from alphadb.model_evaluation.metrics import optional_float
from alphadb.model_evaluation.policy import (
    build_holdout_policy_selection_report,
    market_sort_keys,
)


@dataclass(frozen=True)
class WalkForwardWindow:
    window_index: int
    selection_markets: tuple[str, ...]
    holdout_markets: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_index": self.window_index,
            "selection_market_count": len(self.selection_markets),
            "holdout_market_count": len(self.holdout_markets),
            "selection_markets": list(self.selection_markets),
            "holdout_markets": list(self.holdout_markets),
        }


def build_walk_forward_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    selection_market_count: int,
    holdout_market_count: int,
    step_market_count: int | None = None,
    min_ev_values: Sequence[float] = (0.0,),
    min_confidence_values: Sequence[float] = (0.0,),
) -> dict[str, Any]:
    windows = build_walk_forward_windows(
        rows,
        selection_market_count=selection_market_count,
        holdout_market_count=holdout_market_count,
        step_market_count=step_market_count or holdout_market_count,
    )
    window_reports: list[dict[str, Any]] = []
    for window in windows:
        window_rows = [
            dict(row)
            for row in rows
            if str(row.get("ticker")) in set(window.selection_markets + window.holdout_markets)
        ]
        selection_fraction = len(window.selection_markets) / (
            len(window.selection_markets) + len(window.holdout_markets)
        )
        try:
            report = build_holdout_policy_selection_report(
                window_rows,
                selection_fraction=selection_fraction,
                min_ev_values=min_ev_values,
                min_confidence_values=min_confidence_values,
            )
            status = "complete"
            failure_reason = None
        except Exception as exc:
            report = {}
            status = "skipped"
            failure_reason = f"{exc.__class__.__name__}: {exc}"
        window_reports.append(
            {
                "window": window.as_dict(),
                "status": status,
                "failure_reason": failure_reason,
                "report": report,
            }
        )
    return {
        "schema_version": "kxbtc_model_walk_forward_report_v1",
        "window_count": len(windows),
        "complete_window_count": sum(1 for item in window_reports if item["status"] == "complete"),
        "aggregate": aggregate_walk_forward(window_reports),
        "model_family_instability": summarize_walk_forward_model_family_instability(window_reports),
        "windows": window_reports,
        "non_promotion_notice": (
            "Walk-forward model evaluation informs research only and does not authorize "
            "model promotion or live trading."
        ),
    }


def build_walk_forward_windows(
    rows: Sequence[Mapping[str, Any]],
    *,
    selection_market_count: int,
    holdout_market_count: int,
    step_market_count: int,
) -> list[WalkForwardWindow]:
    if selection_market_count < 1 or holdout_market_count < 1 or step_market_count < 1:
        raise ValueError("walk-forward market counts must all be positive")
    sort_keys = market_sort_keys(rows)
    ordered_markets = sorted(sort_keys, key=lambda ticker: sort_keys[ticker])
    windows: list[WalkForwardWindow] = []
    total = selection_market_count + holdout_market_count
    index = 0
    start = 0
    while start + total <= len(ordered_markets):
        selection = tuple(ordered_markets[start : start + selection_market_count])
        holdout = tuple(ordered_markets[start + selection_market_count : start + total])
        windows.append(
            WalkForwardWindow(
                window_index=index,
                selection_markets=selection,
                holdout_markets=holdout,
            )
        )
        index += 1
        start += step_market_count
    return windows


def aggregate_walk_forward(window_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pnl_values: list[float] = []
    drawdowns: list[float] = []
    expected_log_growth: list[float] = []
    selected_offsets: list[int] = []
    candidates: dict[str, int] = {}
    for item in window_reports:
        if item.get("status") != "complete":
            continue
        report = item.get("report", {})
        holdout = report.get("holdout", {}) if isinstance(report, Mapping) else {}
        metrics = holdout.get("policy_metrics", {}) if isinstance(holdout, Mapping) else {}
        pnl = optional_float(metrics.get("net_pnl"))
        drawdown = optional_float(metrics.get("max_drawdown"))
        growth = optional_float(metrics.get("expected_log_growth"))
        if pnl is not None:
            pnl_values.append(pnl)
        if drawdown is not None:
            drawdowns.append(drawdown)
        if growth is not None:
            expected_log_growth.append(growth)
        selected = report.get("selected_policy", {}) if isinstance(report, Mapping) else {}
        if isinstance(selected, Mapping):
            offset = optional_float(selected.get("decision_minute_offset"))
            if offset is not None:
                selected_offsets.append(int(offset))
            candidate = selected.get("candidate")
            if candidate:
                candidates[str(candidate)] = candidates.get(str(candidate), 0) + 1
    return {
        "net_pnl_total": sum(pnl_values),
        "net_pnl_mean": mean(pnl_values),
        "max_drawdown_worst": max(drawdowns) if drawdowns else None,
        "expected_log_growth_total": sum(expected_log_growth),
        "selected_offset_counts": count_values(selected_offsets),
        "selected_candidate_counts": candidates,
    }


def summarize_walk_forward_model_family_instability(
    window_reports: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    aggregate = aggregate_walk_forward(window_reports)
    counts = aggregate["selected_candidate_counts"]
    selected_count = sum(int(value) for value in counts.values())
    return {
        "selected_candidate_counts": counts,
        "selected_candidate_family_count": len(counts),
        "status": "unstable" if len(counts) > 1 else "stable_single_family",
        "note": (
            "Multiple selected model families across walk-forward windows indicate "
            "selection instability that should be considered before promotion."
            if len(counts) > 1
            else "Walk-forward selected one model family across completed windows."
        ),
        "window_count_with_selection": selected_count,
    }


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def count_values(values: Sequence[int]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts
