"""Generate public-safe fair-value live hot-path latency summaries."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alphadb.model_evaluation.fair_value_live_report import as_mapping


LATENCY_SUMMARY_SCHEMA = "alphadb_aws_fair_value_live_hot_path_latency.v2"
DEFAULT_PRE_CHANGE_S3_AUTHORITY_MEAN_SECONDS = 0.808771
DEFAULT_PRE_CHANGE_S3_AUTHORITY_CONTRIBUTION = 0.71

COMPONENT_LABELS = {
    "runtime_config": "Runtime config",
    "postgres_authority_lease": "Postgres authority",
    "live_run_lock": "S3 live lock",
    "collection": "Market collection",
    "risk_state_read": "Risk state read",
    "risk_refresh": "Risk refresh",
    "risk_admission": "Risk admission",
    "submit_attempt_persist": "Attempt persist",
    "submit": "Submit",
    "status_materialization": "Status",
    "artifact_write": "Artifacts",
    "other": "Other",
}

COMPONENT_COLORS = {
    "runtime_config": "#4f7cac",
    "postgres_authority_lease": "#2e7d5b",
    "live_run_lock": "#b85c38",
    "collection": "#d6a84f",
    "risk_state_read": "#7a5ea8",
    "risk_refresh": "#8b8f50",
    "risk_admission": "#6b8f71",
    "submit_attempt_persist": "#8c6d62",
    "submit": "#b04a5a",
    "status_materialization": "#4f8f9f",
    "artifact_write": "#6d7b8d",
    "other": "#9aa0a6",
}

COMPONENT_ORDER = (
    "runtime_config",
    "postgres_authority_lease",
    "live_run_lock",
    "collection",
    "risk_state_read",
    "risk_refresh",
    "risk_admission",
    "submit_attempt_persist",
    "submit",
    "status_materialization",
    "artifact_write",
    "other",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-fair-value-live-latency-chart")
    parser.add_argument("--input", required=True, type=Path, help="Fair-value live report JSON")
    parser.add_argument("--summary-output", required=True, type=Path)
    parser.add_argument("--svg-output", required=True, type=Path)
    parser.add_argument(
        "--pre-change-authority-mean-seconds",
        type=float,
        default=DEFAULT_PRE_CHANGE_S3_AUTHORITY_MEAN_SECONDS,
    )
    parser.add_argument(
        "--pre-change-authority-contribution",
        type=float,
        default=DEFAULT_PRE_CHANGE_S3_AUTHORITY_CONTRIBUTION,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(report, Mapping):
        raise SystemExit("--input must be a JSON object")

    summary = build_latency_summary(
        report,
        source_report=args.input,
        pre_change_authority_mean_seconds=args.pre_change_authority_mean_seconds,
        pre_change_authority_contribution=args.pre_change_authority_contribution,
    )
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.svg_output.parent.mkdir(parents=True, exist_ok=True)
    args.svg_output.write_text(render_latency_svg(summary), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def build_latency_summary(
    report: Mapping[str, Any],
    *,
    source_report: Path,
    pre_change_authority_mean_seconds: float,
    pre_change_authority_contribution: float,
) -> dict[str, Any]:
    report_summary = as_mapping(report.get("summary"))
    latency = as_mapping(report_summary.get("latency"))
    authority = as_mapping(report_summary.get("live_authority"))
    orders = as_mapping(report_summary.get("orders"))
    total_elapsed = as_mapping(latency.get("total_elapsed_seconds"))
    authority_phase = as_mapping(latency.get("authority_phase"))
    component_means = ordered_component_means(
        as_mapping(latency.get("component_means_seconds"))
    )

    authority_mean = parse_float(authority_phase.get("mean_seconds"))
    post_change_contribution = parse_float(authority_phase.get("mean_hot_path_contribution"))
    improvement: dict[str, Any] = {
        "pre_change_authority_mean_seconds": round(pre_change_authority_mean_seconds, 6),
        "pre_change_authority_contribution": round(pre_change_authority_contribution, 6),
        "post_change_authority_mean_seconds": authority_mean,
        "post_change_authority_contribution": post_change_contribution,
    }
    if authority_mean is not None:
        improvement["authority_mean_delta_seconds"] = round(
            authority_mean - pre_change_authority_mean_seconds,
            6,
        )
        improvement["authority_mean_improvement_ratio"] = round(
            (pre_change_authority_mean_seconds - authority_mean)
            / pre_change_authority_mean_seconds,
            6,
        )
    if post_change_contribution is not None:
        improvement["authority_contribution_delta"] = round(
            post_change_contribution - pre_change_authority_contribution,
            6,
        )

    return {
        "schema_version": LATENCY_SUMMARY_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_report": str(source_report),
        "interval": report.get("interval"),
        "report_status": report.get("status"),
        "schedule_state": report_summary.get("schedule_state"),
        "legacy_structural_schedule_state": report_summary.get(
            "legacy_structural_schedule_state"
        ),
        "run_count": report_summary.get("run_count"),
        "runtime_config_source": as_mapping(report_summary.get("config")).get("source"),
        "runtime_guard": report_summary.get("runtime_guard"),
        "live_authority": authority,
        "orders": orders,
        "total_elapsed_seconds": total_elapsed,
        "authority_phase": authority_phase,
        "component_means_seconds": component_means,
        "comparison": improvement,
        "notes": [
            "Read-only summary from generated AWS report and S3 manifests; no task is triggered by this command.",
            "Segment widths use mean phase contribution to mean manifest total.",
            "S3 should remain artifact/audit storage; Postgres should be runtime authority after the rollout deploy.",
        ],
    }


def ordered_component_means(component_means: Mapping[str, Any]) -> dict[str, float]:
    output: dict[str, float] = {}
    for key in COMPONENT_ORDER:
        value = parse_float(component_means.get(key))
        if value is not None and value > 0:
            output[key] = round(value, 6)
    for key in sorted(component_means):
        if key in output:
            continue
        value = parse_float(component_means.get(key))
        if value is not None and value > 0:
            output[key] = round(value, 6)
    return output


def render_latency_svg(summary: Mapping[str, Any]) -> str:
    components = as_mapping(summary.get("component_means_seconds"))
    total = sum(float(value) for value in components.values())
    total_elapsed = parse_float(as_mapping(summary.get("total_elapsed_seconds")).get("mean"))
    denominator = total_elapsed or total or 1.0
    width = 1120
    height = 360
    margin_x = 56
    bar_width = width - (margin_x * 2)
    bar_y = 114
    bar_height = 42
    title = "Fair-value live AWS hot-path latency"
    subtitle = (
        f"runs={summary.get('run_count')} | authority="
        f"{as_mapping(summary.get('authority_phase')).get('name') or 'unknown'} | "
        f"backend={as_mapping(summary.get('live_authority')).get('backend_latest') or 'unknown'}"
    )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape_xml(title)}">',
        '<rect width="1120" height="360" fill="#f8faf7"/>',
        f'<text x="{margin_x}" y="48" font-family="Inter, Arial, sans-serif" font-size="24" font-weight="700" fill="#18211f">{escape_xml(title)}</text>',
        f'<text x="{margin_x}" y="78" font-family="Inter, Arial, sans-serif" font-size="14" fill="#4c5753">{escape_xml(subtitle)}</text>',
    ]

    cursor = margin_x
    for name, value in components.items():
        seconds = float(value)
        segment_width = max(seconds / denominator * bar_width, 1.0)
        color = COMPONENT_COLORS.get(name, "#9aa0a6")
        label = COMPONENT_LABELS.get(name, name.replace("_", " ").title())
        parts.append(
            f'<rect x="{cursor:.2f}" y="{bar_y}" width="{segment_width:.2f}" height="{bar_height}" fill="{color}"/>'
        )
        if segment_width >= 84:
            parts.append(
                f'<text x="{cursor + 10:.2f}" y="{bar_y + 26}" font-family="Inter, Arial, sans-serif" font-size="12" fill="#ffffff">{escape_xml(label)}</text>'
            )
        cursor += segment_width

    comparison = as_mapping(summary.get("comparison"))
    authority_phase = as_mapping(summary.get("authority_phase"))
    details = [
        f"mean total: {format_seconds(total_elapsed)}",
        f"authority mean: {format_seconds(authority_phase.get('mean_seconds'))}",
        f"authority p95: {format_seconds(authority_phase.get('p95_seconds'))}",
        f"vs S3 baseline: {format_delta(comparison.get('authority_mean_delta_seconds'))}",
        f"submitted orders: {as_mapping(summary.get('orders')).get('submitted', 0)}",
    ]
    for index, detail in enumerate(details):
        parts.append(
            f'<text x="{margin_x}" y="{205 + index * 24}" font-family="Inter, Arial, sans-serif" font-size="14" fill="#25302d">{escape_xml(detail)}</text>'
        )

    legend_x = 430
    legend_y = 198
    for index, (name, value) in enumerate(components.items()):
        x = legend_x + (index % 2) * 300
        y = legend_y + (index // 2) * 28
        label = COMPONENT_LABELS.get(name, name.replace("_", " ").title())
        parts.append(
            f'<rect x="{x}" y="{y - 12}" width="12" height="12" fill="{COMPONENT_COLORS.get(name, "#9aa0a6")}"/>'
        )
        parts.append(
            f'<text x="{x + 20}" y="{y}" font-family="Inter, Arial, sans-serif" font-size="13" fill="#25302d">{escape_xml(label)} {format_seconds(value)}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def format_seconds(value: Any) -> str:
    parsed = parse_float(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:.3f}s"


def format_delta(value: Any) -> str:
    parsed = parse_float(value)
    if parsed is None:
        return "n/a"
    sign = "+" if parsed >= 0 else ""
    return f"{sign}{parsed:.3f}s"


def parse_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed


def escape_xml(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
