"""Read-only execution/fill-speed attribution from compact live artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from alphadb.model_evaluation.io import load_json

SCHEMA_VERSION = "alphadb_execution_attribution.v1"
CSV_FILENAME = "execution_attribution.csv"
REPORT_FILENAME = "execution_attribution_report.md"

BottleneckVerdict = Literal[
    "execution_ok",
    "quote_staleness_problem",
    "coinbase_staleness_problem",
    "hot_path_too_slow",
    "adverse_fill_selection",
    "risk_state_latency_problem",
    "insufficient_data",
]

BOTTLENECK_VERDICTS: tuple[BottleneckVerdict, ...] = (
    "execution_ok",
    "quote_staleness_problem",
    "coinbase_staleness_problem",
    "hot_path_too_slow",
    "adverse_fill_selection",
    "risk_state_latency_problem",
    "insufficient_data",
)

PHASE_ALIASES: Mapping[str, tuple[str, ...]] = {
    "lock": ("live_run_lock", "lock"),
    "config": ("runtime_config", "config"),
    "collection": ("collection",),
    "decision": ("decision",),
    "freshness": ("freshness",),
    "risk_state_read": ("risk_state_read",),
    "risk_admission": ("risk_admission",),
    "submit": ("submit",),
    "status_materialization": ("status_materialization",),
    "artifact_write": ("artifact_write",),
}

CSV_COLUMNS: tuple[str, ...] = (
    "run_id",
    "evidence_type",
    "strategy",
    "market_ticker",
    "decision_ts",
    "quote_seen_at",
    "quote_age_seconds",
    "quote_age_at_submit_seconds",
    "coinbase_source_ts",
    "coinbase_age_seconds",
    "active_context_source",
    "active_context_status",
    "active_context_age_seconds",
    "active_context_stale_seconds",
    "side",
    "decision",
    "skip_reason",
    "intended_price",
    "intended_contracts",
    "decision_edge",
    "min_edge",
    "edge_shortfall",
    "diagnostic_class",
    "fresh_quote_counterfactual_status",
    "fresh_quote_counterfactual_basis",
    "time_to_expiry_seconds",
    "risk_admission_status",
    "risk_admission_reason",
    "order_submit_at",
    "submit_response_at",
    "submit_roundtrip_ms",
    "decision_to_submit_latency_seconds",
    "order_status",
    "fill_count",
    "remaining_count",
    "realized_pnl",
    "counterfactual_pnl_if_available",
    "phase_lock_seconds",
    "phase_config_seconds",
    "phase_collection_seconds",
    "phase_decision_seconds",
    "phase_freshness_seconds",
    "phase_risk_state_read_seconds",
    "phase_risk_admission_seconds",
    "phase_submit_seconds",
    "phase_status_materialization_seconds",
    "phase_artifact_write_seconds",
    "phase_total_seconds",
)

AGE_BUCKETS: tuple[tuple[str, float | None, float | None], ...] = (
    ("0_5s", 0.0, 5.0),
    ("5_15s", 5.0, 15.0),
    ("15_60s", 15.0, 60.0),
    ("60s_plus", 60.0, None),
)
LATENCY_BUCKETS: tuple[tuple[str, float | None, float | None], ...] = (
    ("0_1s", 0.0, 1.0),
    ("1_3s", 1.0, 3.0),
    ("3_10s", 3.0, 10.0),
    ("10s_plus", 10.0, None),
)
PRICE_BUCKETS: tuple[tuple[str, float | None, float | None], ...] = (
    ("0_25", 0.0, 0.25),
    ("25_50", 0.25, 0.50),
    ("50_75", 0.50, 0.75),
    ("75_100", 0.75, 1.01),
)
EDGE_BUCKETS: tuple[tuple[str, float | None, float | None], ...] = (
    ("negative", None, 0.0),
    ("0_2pct", 0.0, 0.02),
    ("2_5pct", 0.02, 0.05),
    ("5_10pct", 0.05, 0.10),
    ("10pct_plus", 0.10, None),
)


@dataclass(frozen=True)
class LiveRunArtifacts:
    run_id: str
    run_dir: Path
    manifest: Mapping[str, Any]
    decision_rows_payload: Mapping[str, Any]
    attempts_payload: Mapping[str, Any]
    reconciliation: Mapping[str, Any]

    def generated_at_sort_key(self) -> str:
        generated_at = (
            self.attempts_payload.get("generated_at")
            or self.decision_rows_payload.get("generated_at")
            or self.manifest.get("generated_at")
        )
        return str(generated_at or "")


@dataclass(frozen=True)
class ExecutionAttributionResult:
    input_path: str
    output_dir: str
    csv_path: str
    report_path: str
    run_count: int
    row_count: int
    bottleneck_verdict: BottleneckVerdict
    data_limitations: tuple[str, ...]
    summaries: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "input_path": self.input_path,
            "output_dir": self.output_dir,
            "csv_path": self.csv_path,
            "report_path": self.report_path,
            "run_count": self.run_count,
            "row_count": self.row_count,
            "bottleneck_verdict": self.bottleneck_verdict,
            "data_limitations": list(self.data_limitations),
            "summaries": dict(self.summaries),
        }


def generate_execution_attribution(
    input_path: str | Path,
    output_dir: str | Path,
) -> ExecutionAttributionResult:
    """Generate CSV and Markdown execution attribution from local live artifacts."""

    input_root = Path(input_path).expanduser().resolve()
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    runs = discover_live_run_artifacts(input_root)
    rows = build_execution_rows(runs)
    summaries = build_summary_tables(rows=rows, runs=runs)
    limitations = tuple(data_limitations(rows, summaries))
    verdict = bottleneck_verdict(rows, summaries)

    csv_path = output_root / CSV_FILENAME
    report_path = output_root / REPORT_FILENAME
    write_execution_csv(csv_path, rows)
    report_path.write_text(
        render_markdown_report(
            input_path=input_root,
            rows=rows,
            run_count=len(runs),
            summaries=summaries,
            verdict=verdict,
            limitations=limitations,
        ),
        encoding="utf-8",
    )

    return ExecutionAttributionResult(
        input_path=str(input_root),
        output_dir=str(output_root),
        csv_path=str(csv_path),
        report_path=str(report_path),
        run_count=len(runs),
        row_count=len(rows),
        bottleneck_verdict=verdict,
        data_limitations=limitations,
        summaries=summaries,
    )


def discover_live_run_artifacts(input_path: Path) -> list[LiveRunArtifacts]:
    """Find local run directories that contain compact live-attempt artifacts."""

    candidate_dirs: list[Path] = []
    if input_path.is_file():
        candidate_dirs.append(input_path.parent)
    elif input_path.is_dir():
        if (input_path / "live_order_attempts.json").exists() or (
            input_path / "manifest.json"
        ).exists():
            candidate_dirs.append(input_path)
        candidate_dirs.extend(path.parent for path in input_path.rglob("live_order_attempts.json"))
    else:
        raise FileNotFoundError(f"input path does not exist: {input_path}")

    unique_dirs: list[Path] = []
    seen: set[Path] = set()
    for candidate in sorted(candidate_dirs):
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_dirs.append(resolved)

    runs = [load_live_run_artifacts(path) for path in unique_dirs]
    return sorted(runs, key=lambda run: (run.generated_at_sort_key(), run.run_id))


def load_live_run_artifacts(run_dir: Path) -> LiveRunArtifacts:
    manifest = load_optional_json(run_dir / "manifest.json")
    decision_rows_payload = load_optional_json(run_dir / "decision_rows.json")
    attempts_payload = load_optional_json(run_dir / "live_order_attempts.json")
    reconciliation = load_optional_json(run_dir / "live_reconciliation_report.json")
    run_id = str(
        attempts_payload.get("run_id")
        or decision_rows_payload.get("run_id")
        or manifest.get("run_id")
        or reconciliation.get("run_id")
        or run_dir.name
    )
    return LiveRunArtifacts(
        run_id=run_id,
        run_dir=run_dir,
        manifest=manifest,
        decision_rows_payload=decision_rows_payload,
        attempts_payload=attempts_payload,
        reconciliation=reconciliation,
    )


def load_optional_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    return load_json(path)


def build_execution_rows(runs: Sequence[LiveRunArtifacts]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        for candidate_value in as_sequence(run.decision_rows_payload.get("rows")):
            candidate = as_mapping(candidate_value)
            if candidate.get("row_type") != "decision":
                continue
            rows.append(normalize_candidate_row(run=run, candidate=candidate))
        attempts = as_sequence(run.attempts_payload.get("attempts"))
        reconciliation_by_attempt = reconciliation_index(run.reconciliation)
        for attempt_value in attempts:
            attempt = as_mapping(attempt_value)
            rows.append(
                normalize_attempt_row(
                    run=run,
                    attempt=attempt,
                    reconciliation_row=reconciliation_by_attempt.get(attempt_key(attempt), {}),
                )
            )
    return rows


def normalize_attempt_row(
    *,
    run: LiveRunArtifacts,
    attempt: Mapping[str, Any],
    reconciliation_row: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = run.manifest
    decision = as_mapping(attempt.get("decision"))
    original_decision = as_mapping(attempt.get("original_decision"))
    decision_for_context = original_decision or decision
    source_row = as_mapping(attempt.get("source_row")) or as_mapping(manifest.get("selected_row"))
    freshness = as_mapping(attempt.get("freshness"))
    attribution = as_mapping(attempt.get("live_edge_attribution"))
    attribution_freshness = as_mapping(attribution.get("freshness"))
    active_context = active_context_from(
        attribution=attribution,
        freshness=freshness,
        source_row=source_row,
    )
    fresh_quote = as_mapping(attribution.get("fresh_quote_counterfactual"))
    risk_admission = as_mapping(attempt.get("risk_admission"))
    response = as_mapping(attempt.get("response_payload"))
    timing = timing_for_attempt(run=run, attempt=attempt)
    phase_seconds = as_mapping(timing.get("phase_seconds"))

    generated_at = parse_datetime(
        run.attempts_payload.get("generated_at") or manifest.get("generated_at")
    )
    decision_ts = parse_datetime(
        decision_for_context.get("decision_timestamp")
        or source_row.get("decision_timestamp")
        or attempt.get("submitted_at")
        or generated_at
    )
    quote_seen_at = parse_datetime(
        attempt.get("quote_seen_at")
        or freshness.get("quote_seen_at")
        or source_row.get("quote_observed_at")
        or source_row.get("kalshi_received_at")
        or source_row.get("decision_timestamp")
    )
    order_submit_at = parse_datetime(
        attempt.get("order_submit_at")
        or timing.get("order_submit_at")
        or response.get("order_submit_at")
    )
    submit_response_at = parse_datetime(
        attempt.get("submit_response_at")
        or response.get("submit_response_at")
        or response.get("response_at")
        or response.get("created_time")
    )
    coinbase_source_ts = parse_datetime(
        freshness.get("coinbase_max_source_event_timestamp")
        or source_row.get("coinbase_max_source_event_timestamp")
    )
    quote_age = first_float(
        attempt.get("quote_age_seconds"),
        freshness.get("quote_age_seconds"),
    )
    if quote_age is None and quote_seen_at is not None and generated_at is not None:
        quote_age = seconds_between(generated_at, quote_seen_at)
    quote_age_at_submit = seconds_between(order_submit_at, quote_seen_at)
    coinbase_age = first_float(
        attribution_freshness.get("coinbase_feature_age_seconds"),
        freshness.get("coinbase_feature_age_seconds"),
        source_row.get("coinbase_feature_age_seconds"),
    )
    if coinbase_age is None and coinbase_source_ts is not None and generated_at is not None:
        coinbase_age = seconds_between(generated_at, coinbase_source_ts)
    decision_to_submit = seconds_between(order_submit_at, decision_ts)
    submit_roundtrip_ms = first_float(
        attempt.get("submit_roundtrip_ms"),
        response.get("submit_roundtrip_ms"),
    )
    if submit_roundtrip_ms is None:
        roundtrip_seconds = seconds_between(submit_response_at, order_submit_at)
        submit_roundtrip_ms = None if roundtrip_seconds is None else round(roundtrip_seconds * 1000, 3)

    fill_count = first_int(
        attempt.get("fill_count"),
        nested_value(response, ("fill_count",)),
        nested_value(response, ("fill_count_fp",)),
        nested_value(response, ("filled_quantity",)),
        nested_value(response, ("order", "fill_count")),
        nested_value(response, ("order", "fill_count_fp")),
        nested_value(response, ("order", "filled_quantity")),
        reconciliation_row.get("filled_contracts"),
    )
    remaining_count = first_int(
        attempt.get("remaining_count"),
        nested_value(response, ("remaining_count",)),
        nested_value(response, ("remaining_count_fp",)),
        nested_value(response, ("order", "remaining_count")),
        nested_value(response, ("order", "remaining_count_fp")),
    )
    market_exposure = as_mapping(attempt.get("market_exposure"))
    intended_contracts = first_int(
        market_exposure.get("sized_contracts"),
        decision_for_context.get("intended_contracts"),
        decision_for_context.get("contracts"),
    )
    intended_price = first_float(
        decision_for_context.get("price"),
        decision_for_context.get("yes_ask"),
        decision_for_context.get("no_ask"),
        source_row.get("yes_ask"),
        source_row.get("no_ask"),
    )
    decision_edge = first_float(
        decision_for_context.get("edge"),
        attribution.get("edge"),
    )
    realized_pnl = realized_pnl_from_reconciliation(reconciliation_row)
    counterfactual_pnl = first_float(
        attempt.get("counterfactual_pnl_if_available"),
        reconciliation_row.get("counterfactual_pnl_if_available"),
    )
    order_status = text(attempt.get("status")) or "unknown"
    final_decision = text(decision.get("decision")) or text(decision_for_context.get("decision"))
    skip_reason = None
    if order_status != "submitted" or final_decision != "trade":
        skip_reason = text(attempt.get("reason")) or text(decision.get("reason"))

    row = {
        "run_id": text(attempt.get("run_id")) or run.run_id,
        "evidence_type": "attempt",
        "strategy": text(attempt.get("strategy"))
        or text(run.attempts_payload.get("strategy"))
        or text(manifest.get("strategy")),
        "market_ticker": text(
            attempt.get("market_ticker")
            or decision_for_context.get("market_ticker")
            or decision_for_context.get("ticker")
            or source_row.get("market_ticker")
            or source_row.get("ticker")
        ),
        "decision_ts": format_datetime(decision_ts),
        "quote_seen_at": format_datetime(quote_seen_at),
        "quote_age_seconds": rounded(quote_age),
        "quote_age_at_submit_seconds": rounded(quote_age_at_submit),
        "coinbase_source_ts": format_datetime(coinbase_source_ts),
        "coinbase_age_seconds": rounded(coinbase_age),
        "active_context_source": text(active_context.get("evidence_source")),
        "active_context_status": text(active_context.get("status")),
        "active_context_age_seconds": rounded(
            optional_float(active_context.get("age_seconds"))
        ),
        "active_context_stale_seconds": rounded(
            optional_float(active_context.get("stale_seconds"))
        ),
        "side": text(attempt.get("side")) or text(decision_for_context.get("side")),
        "decision": final_decision,
        "skip_reason": skip_reason,
        "intended_price": rounded(intended_price),
        "intended_contracts": intended_contracts,
        "decision_edge": rounded(decision_edge),
        "min_edge": rounded(optional_float(attribution.get("min_edge"))),
        "edge_shortfall": rounded(optional_float(attribution.get("edge_shortfall"))),
        "diagnostic_class": text(attribution.get("attribution_class")),
        "fresh_quote_counterfactual_status": text(fresh_quote.get("status")),
        "fresh_quote_counterfactual_basis": text(fresh_quote.get("basis")),
        "time_to_expiry_seconds": rounded(time_to_expiry_seconds(source_row, decision_ts)),
        "risk_admission_status": text(risk_admission.get("status")),
        "risk_admission_reason": text(risk_admission.get("reason")),
        "order_submit_at": format_datetime(order_submit_at),
        "submit_response_at": format_datetime(submit_response_at),
        "submit_roundtrip_ms": rounded(submit_roundtrip_ms),
        "decision_to_submit_latency_seconds": rounded(decision_to_submit),
        "order_status": order_status,
        "fill_count": fill_count,
        "remaining_count": remaining_count,
        "realized_pnl": rounded(realized_pnl),
        "counterfactual_pnl_if_available": rounded(counterfactual_pnl),
        "phase_total_seconds": rounded(first_float(timing.get("total_elapsed_seconds"))),
    }
    for phase_name, aliases in PHASE_ALIASES.items():
        row[f"phase_{phase_name}_seconds"] = rounded(
            first_float(*(phase_seconds.get(alias) for alias in aliases))
        )
    return {column: row.get(column) for column in CSV_COLUMNS}


def normalize_candidate_row(
    *,
    run: LiveRunArtifacts,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = run.manifest
    attribution = as_mapping(candidate.get("live_edge_attribution"))
    freshness = as_mapping(attribution.get("freshness"))
    active_context = active_context_from(
        attribution=attribution,
        freshness=freshness,
        source_row=candidate,
    )
    fresh_quote = as_mapping(attribution.get("fresh_quote_counterfactual"))
    timing = as_mapping(attribution.get("timing")) or as_mapping(manifest.get("timing"))
    phase_seconds = as_mapping(timing.get("phase_seconds"))
    generated_at = parse_datetime(
        run.decision_rows_payload.get("generated_at")
        or manifest.get("generated_at")
    )
    decision_ts = parse_datetime(candidate.get("decision_timestamp") or generated_at)
    quote_seen_at = parse_datetime(
        freshness.get("quote_seen_at")
        or candidate.get("quote_observed_at")
        or candidate.get("kalshi_received_at")
        or candidate.get("decision_timestamp")
    )
    coinbase_source_ts = parse_datetime(
        freshness.get("coinbase_max_source_event_timestamp")
        or candidate.get("coinbase_max_source_event_timestamp")
    )
    quote_age = first_float(freshness.get("quote_age_seconds"))
    if quote_age is None and quote_seen_at is not None and generated_at is not None:
        quote_age = seconds_between(generated_at, quote_seen_at)
    coinbase_age = first_float(
        freshness.get("coinbase_feature_age_seconds"),
        candidate.get("coinbase_feature_age_seconds"),
    )
    if coinbase_age is None and coinbase_source_ts is not None and generated_at is not None:
        coinbase_age = seconds_between(generated_at, coinbase_source_ts)

    decision = text(attribution.get("decision"))
    row = {
        "run_id": text(run.decision_rows_payload.get("run_id")) or run.run_id,
        "evidence_type": "candidate",
        "strategy": text(manifest.get("strategy"))
        or text(run.attempts_payload.get("strategy")),
        "market_ticker": text(candidate.get("market_ticker") or candidate.get("ticker")),
        "decision_ts": format_datetime(decision_ts),
        "quote_seen_at": format_datetime(quote_seen_at),
        "quote_age_seconds": rounded(quote_age),
        "quote_age_at_submit_seconds": None,
        "coinbase_source_ts": format_datetime(coinbase_source_ts),
        "coinbase_age_seconds": rounded(coinbase_age),
        "active_context_source": text(active_context.get("evidence_source")),
        "active_context_status": text(active_context.get("status")),
        "active_context_age_seconds": rounded(
            optional_float(active_context.get("age_seconds"))
        ),
        "active_context_stale_seconds": rounded(
            optional_float(active_context.get("stale_seconds"))
        ),
        "side": text(attribution.get("side")),
        "decision": decision,
        "skip_reason": text(attribution.get("reason")) if decision != "trade" else None,
        "intended_price": rounded(optional_float(attribution.get("price"))),
        "intended_contracts": None,
        "decision_edge": rounded(optional_float(attribution.get("edge"))),
        "min_edge": rounded(optional_float(attribution.get("min_edge"))),
        "edge_shortfall": rounded(optional_float(attribution.get("edge_shortfall"))),
        "diagnostic_class": text(attribution.get("attribution_class")),
        "fresh_quote_counterfactual_status": text(fresh_quote.get("status")),
        "fresh_quote_counterfactual_basis": text(fresh_quote.get("basis")),
        "time_to_expiry_seconds": rounded(time_to_expiry_seconds(candidate, decision_ts)),
        "risk_admission_status": None,
        "risk_admission_reason": None,
        "order_submit_at": None,
        "submit_response_at": None,
        "submit_roundtrip_ms": None,
        "decision_to_submit_latency_seconds": None,
        "order_status": "candidate",
        "fill_count": None,
        "remaining_count": None,
        "realized_pnl": None,
        "counterfactual_pnl_if_available": rounded(
            optional_float(fresh_quote.get("counterfactual_pnl_if_available"))
        ),
        "phase_total_seconds": rounded(first_float(timing.get("total_elapsed_seconds"))),
    }
    for phase_name, aliases in PHASE_ALIASES.items():
        row[f"phase_{phase_name}_seconds"] = rounded(
            first_float(*(phase_seconds.get(alias) for alias in aliases))
        )
    return {column: row.get(column) for column in CSV_COLUMNS}


def timing_for_attempt(
    *,
    run: LiveRunArtifacts,
    attempt: Mapping[str, Any],
) -> Mapping[str, Any]:
    manifest_timing = as_mapping(run.manifest.get("timing"))
    if manifest_timing:
        return manifest_timing
    attribution_timing = as_mapping(as_mapping(attempt.get("live_edge_attribution")).get("timing"))
    if attribution_timing:
        return attribution_timing
    return {}


def active_context_from(
    *,
    attribution: Mapping[str, Any],
    freshness: Mapping[str, Any],
    source_row: Mapping[str, Any],
) -> Mapping[str, Any]:
    attribution_freshness = as_mapping(attribution.get("freshness"))
    active_context = as_mapping(attribution_freshness.get("active_context"))
    if active_context:
        return active_context

    source = text(
        freshness.get("market_context_source")
        or source_row.get("market_context_source")
    )
    if source == "brti_primary":
        age = first_float(
            freshness.get("brti_context_age_seconds"),
            source_row.get("brti_context_age_seconds"),
        )
        stale_seconds = first_float(
            freshness.get("brti_freshness_limit_seconds"),
            source_row.get("brti_freshness_limit_seconds"),
        )
        return {
            "market_context_source": source,
            "evidence_source": "brti_latest_context",
            "status": context_status(
                raw_status=text(
                    freshness.get("brti_context_status")
                    or source_row.get("brti_context_status")
                    or source_row.get("market_context_status")
                ),
                age_seconds=age,
                stale_seconds=stale_seconds,
            ),
            "age_seconds": rounded(age),
            "stale_seconds": rounded(stale_seconds),
        }
    if source == "fixture":
        return {
            "market_context_source": source,
            "evidence_source": "fixture",
            "status": "not_applicable",
            "age_seconds": None,
            "stale_seconds": None,
        }
    age = first_float(
        freshness.get("coinbase_feature_age_seconds"),
        source_row.get("coinbase_feature_age_seconds"),
    )
    return {
        "market_context_source": source or "coinbase_primary",
        "evidence_source": "coinbase_features",
        "status": context_status(
            raw_status=text(source_row.get("market_context_status")),
            age_seconds=age,
            stale_seconds=None,
        ),
        "age_seconds": rounded(age),
        "stale_seconds": None,
    }


def context_status(
    *,
    raw_status: str | None,
    age_seconds: float | None,
    stale_seconds: float | None,
) -> str:
    if raw_status in {"missing", "unavailable", "unusable"}:
        return raw_status
    if age_seconds is None:
        return "missing"
    if stale_seconds is not None and age_seconds > stale_seconds:
        return "stale"
    return "fresh"


def reconciliation_index(reconciliation: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    index: dict[str, Mapping[str, Any]] = {}
    for row_value in as_sequence(reconciliation.get("rows")):
        row = as_mapping(row_value)
        for key in (
            row.get("attempt_id"),
            row.get("order_id"),
            row.get("client_order_id"),
        ):
            if key:
                index[str(key)] = row
    return index


def attempt_key(attempt: Mapping[str, Any]) -> str:
    for key in (
        attempt.get("attempt_id"),
        attempt.get("order_id"),
        attempt.get("client_order_id"),
    ):
        if key:
            return str(key)
    return ""


def build_summary_tables(
    *,
    rows: Sequence[Mapping[str, Any]],
    runs: Sequence[LiveRunArtifacts],
) -> dict[str, Any]:
    hot_path = hot_path_phase_summary(rows)
    summaries = {
        "data_coverage": data_coverage_summary(rows=rows, runs=runs),
        "hot_path_timing": hot_path,
        "dominant_hot_path_area": dominant_hot_path_area(rows),
        "quote_age_bucket_summary": bucket_summary(rows, "quote_age_seconds", AGE_BUCKETS),
        "coinbase_age_bucket_summary": bucket_summary(rows, "coinbase_age_seconds", AGE_BUCKETS),
        "active_context_age_bucket_summary": bucket_summary(
            rows,
            "active_context_age_seconds",
            AGE_BUCKETS,
        ),
        "decision_to_submit_latency_bucket_summary": bucket_summary(
            rows,
            "decision_to_submit_latency_seconds",
            LATENCY_BUCKETS,
        ),
        "hot_path_total_latency_bucket_summary": bucket_summary(
            rows,
            "phase_total_seconds",
            LATENCY_BUCKETS,
        ),
        "fill_vs_no_fill_summary": fill_vs_no_fill_summary(rows),
        "side_bucket_summary": categorical_summary(rows, "side"),
        "price_bucket_summary": bucket_summary(rows, "intended_price", PRICE_BUCKETS),
        "edge_bucket_summary": bucket_summary(rows, "decision_edge", EDGE_BUCKETS),
        "diagnostic_class_summary": categorical_summary(rows, "diagnostic_class"),
        "fresh_quote_counterfactual": fresh_quote_counterfactual_summary(rows),
        "skip_reject_error_reason_summary": reason_summary(rows),
        "adverse_selection": adverse_selection_summary(rows),
        "implementation_drag": implementation_drag_summary(rows),
    }
    return summaries


def data_coverage_summary(
    *,
    rows: Sequence[Mapping[str, Any]],
    runs: Sequence[LiveRunArtifacts],
) -> dict[str, Any]:
    row_count = len(rows)
    fields = (
        "decision_ts",
        "quote_seen_at",
        "quote_age_seconds",
        "quote_age_at_submit_seconds",
        "coinbase_source_ts",
        "coinbase_age_seconds",
        "active_context_source",
        "active_context_status",
        "active_context_age_seconds",
        "diagnostic_class",
        "fresh_quote_counterfactual_status",
        "order_submit_at",
        "submit_response_at",
        "submit_roundtrip_ms",
        "realized_pnl",
        "counterfactual_pnl_if_available",
    )
    return {
        "run_count": len(runs),
        "row_count": row_count,
        "attempt_status_counts": dict(Counter(text(row.get("order_status")) for row in rows)),
        "filled_attempt_count": sum(1 for row in rows if (optional_float(row.get("fill_count")) or 0) > 0),
        "field_coverage": [
            {
                "field": field,
                "available": count_present(rows, field),
                "total": row_count,
                "coverage_pct": percent(count_present(rows, field), row_count),
            }
            for field in fields
        ],
    }


def hot_path_phase_summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for phase_name in (
        "lock",
        "config",
        "collection",
        "decision",
        "freshness",
        "risk_state_read",
        "risk_admission",
        "submit",
        "status_materialization",
        "artifact_write",
        "total",
    ):
        column = f"phase_{phase_name}_seconds"
        values = numeric_values(row.get(column) for row in rows)
        output.append(
            {
                "phase": phase_name,
                "sample_size": len(values),
                "p50_seconds": percentile(values, 0.50),
                "p95_seconds": percentile(values, 0.95),
                "max_seconds": rounded(max(values)) if values else None,
                "status": "available" if values else "insufficient_data",
            }
        )
    return output


def dominant_hot_path_area(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    groups: Mapping[str, tuple[str, ...]] = {
        "collection": ("phase_collection_seconds",),
        "decision": ("phase_decision_seconds", "phase_freshness_seconds"),
        "risk_state": ("phase_risk_state_read_seconds", "phase_risk_admission_seconds"),
        "submit": ("phase_submit_seconds",),
        "artifact_status": (
            "phase_status_materialization_seconds",
            "phase_artifact_write_seconds",
        ),
        "lock_config": ("phase_lock_seconds", "phase_config_seconds"),
    }
    summaries: list[dict[str, Any]] = []
    for area, columns in groups.items():
        values = [
            sum(parts)
            for row in rows
            if (parts := numeric_values(row.get(column) for column in columns))
        ]
        summaries.append(
            {
                "area": area,
                "sample_size": len(values),
                "p95_seconds": percentile(values, 0.95),
                "max_seconds": rounded(max(values)) if values else None,
                "status": "available" if values else "insufficient_data",
            }
        )
    available = [row for row in summaries if optional_float(row.get("p95_seconds")) is not None]
    dominant = (
        max(available, key=lambda row: optional_float(row.get("p95_seconds")) or 0.0)
        if available
        else None
    )
    return {
        "dominant_area": dominant.get("area") if dominant else "insufficient_data",
        "basis": "highest_p95_seconds_by_hot_path_area" if dominant else "insufficient_data",
        "areas": summaries,
    }


def bucket_summary(
    rows: Sequence[Mapping[str, Any]],
    field: str,
    buckets: Sequence[tuple[str, float | None, float | None]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {bucket[0]: [] for bucket in buckets}
    grouped["missing"] = []
    for row in rows:
        value = optional_float(row.get(field))
        grouped[bucket_name(value, buckets)].append(row)
    return [
        summary_row(bucket, bucket_rows)
        for bucket, bucket_rows in grouped.items()
        if bucket_rows or bucket == "missing"
    ]


def categorical_summary(rows: Sequence[Mapping[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        bucket = text(row.get(field)) or "missing"
        grouped.setdefault(bucket, []).append(row)
    return [
        summary_row(bucket, bucket_rows)
        for bucket, bucket_rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def fill_vs_no_fill_summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {
        "candidate_only": [],
        "filled": [],
        "submitted_no_fill": [],
        "skipped": [],
        "rejected_or_error": [],
    }
    for row in rows:
        status = text(row.get("order_status"))
        fill_count = optional_float(row.get("fill_count")) or 0.0
        if text(row.get("evidence_type")) == "candidate":
            grouped["candidate_only"].append(row)
        elif status == "submitted" and fill_count > 0:
            grouped["filled"].append(row)
        elif status == "submitted":
            grouped["submitted_no_fill"].append(row)
        elif status == "skipped":
            grouped["skipped"].append(row)
        else:
            grouped["rejected_or_error"].append(row)
    return [summary_row(bucket, bucket_rows) for bucket, bucket_rows in grouped.items()]


def reason_summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        status = text(row.get("order_status")) or "unknown"
        if status == "submitted":
            continue
        reason = text(row.get("skip_reason")) or text(row.get("risk_admission_reason")) or status
        key = f"{status}:{reason}"
        grouped.setdefault(key, []).append(row)
    return [
        summary_row(reason, reason_rows)
        for reason, reason_rows in sorted(
            grouped.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )
    ]


def summary_row(bucket: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    submitted = [
        row
        for row in rows
        if text(row.get("order_status")) == "submitted"
    ]
    filled = [
        row
        for row in submitted
        if (optional_float(row.get("fill_count")) or 0.0) > 0
    ]
    return {
        "bucket": bucket,
        "count": len(rows),
        "submitted_count": len(submitted),
        "filled_count": len(filled),
        "fill_rate": percent(len(filled), len(submitted)) if submitted else None,
        "avg_decision_edge": mean(numeric_values(row.get("decision_edge") for row in rows)),
        "avg_realized_pnl": mean(numeric_values(row.get("realized_pnl") for row in rows)),
        "avg_quote_age_seconds": mean(numeric_values(row.get("quote_age_seconds") for row in rows)),
    }


def adverse_selection_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    filled = [
        row
        for row in rows
        if text(row.get("order_status")) == "submitted"
        and (optional_float(row.get("fill_count")) or 0.0) > 0
    ]
    no_fill_or_skipped = [
        row
        for row in rows
        if (text(row.get("order_status")) == "submitted" and (optional_float(row.get("fill_count")) or 0.0) == 0)
        or text(row.get("order_status")) == "skipped"
    ]
    filled_pnl = numeric_values(row.get("realized_pnl") for row in filled)
    comparison_pnl = numeric_values(row.get("realized_pnl") for row in no_fill_or_skipped)
    if not filled_pnl or not comparison_pnl:
        return {
            "status": "insufficient_data",
            "basis": (
                "Need realized PnL for both filled IOC attempts and no-fill/skipped comparison "
                "rows before claiming adverse fill selection."
            ),
            "filled_sample_size": len(filled_pnl),
            "comparison_sample_size": len(comparison_pnl),
            "filled_avg_realized_pnl": mean(filled_pnl),
            "comparison_avg_realized_pnl": mean(comparison_pnl),
        }
    filled_avg = mean(filled_pnl)
    comparison_avg = mean(comparison_pnl)
    if len(filled_pnl) < 5 or len(comparison_pnl) < 5:
        status = "insufficient_data"
        basis = "Sample is too small for an adverse-selection conclusion."
    elif filled_avg is not None and comparison_avg is not None and filled_avg < comparison_avg:
        status = "possible_adverse_fill_selection"
        basis = "Filled attempts have worse realized PnL than no-fill/skipped comparison rows."
    else:
        status = "no_evidence"
        basis = "Filled attempts do not underperform the comparison rows in available data."
    return {
        "status": status,
        "basis": basis,
        "filled_sample_size": len(filled_pnl),
        "comparison_sample_size": len(comparison_pnl),
        "filled_avg_realized_pnl": filled_avg,
        "comparison_avg_realized_pnl": comparison_avg,
    }


def fresh_quote_counterfactual_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    statuses = Counter(
        text(row.get("fresh_quote_counterfactual_status")) or "missing"
        for row in rows
    )
    available = statuses.get("available", 0)
    if not rows:
        status = "insufficient_data"
    elif available:
        status = "available" if available == len(rows) else "mixed"
    else:
        status = "unavailable"
    return {
        "status": status,
        "status_counts": [
            {"status": name, "count": count}
            for name, count in sorted(
                statuses.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
        "basis": (
            "Fresh-quote counterfactuals require independent quote evidence at or "
            "after submit time; exchange responses alone are not used."
        ),
    }


def implementation_drag_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counterfactual_rows = [
        row
        for row in rows
        if optional_float(row.get("counterfactual_pnl_if_available")) is not None
    ]
    if not counterfactual_rows:
        return {
            "status": "unavailable",
            "estimated_drag_dollars": None,
            "basis": (
                "No independent fresh-quote counterfactual or counterfactual PnL "
                "fields were present in the input artifacts."
            ),
        }
    drag_values: list[float] = []
    for row in counterfactual_rows:
        counterfactual = optional_float(row.get("counterfactual_pnl_if_available"))
        realized = optional_float(row.get("realized_pnl")) or 0.0
        if counterfactual is not None:
            drag_values.append(max(0.0, counterfactual - realized))
    return {
        "status": "proxy",
        "estimated_drag_dollars": rounded(sum(drag_values)),
        "basis": (
            "Proxy uses counterfactual_pnl_if_available minus realized_pnl where artifacts "
            "already provide those fields."
        ),
        "sample_size": len(drag_values),
    }


def bottleneck_verdict(
    rows: Sequence[Mapping[str, Any]],
    summaries: Mapping[str, Any],
) -> BottleneckVerdict:
    if not rows:
        return "insufficient_data"
    reason_counts = {
        str(row.get("skip_reason") or "")
        for row in rows
        if row.get("skip_reason")
    }
    diagnostic_classes = {
        text(row.get("diagnostic_class"))
        for row in rows
        if text(row.get("diagnostic_class"))
    }
    if "quote_stale" in reason_counts:
        return "quote_staleness_problem"
    if "quote_freshness_suspect" in diagnostic_classes:
        return "quote_staleness_problem"
    if "coinbase_context_stale" in reason_counts:
        return "coinbase_staleness_problem"
    if "coinbase_freshness_suspect" in diagnostic_classes:
        return "coinbase_staleness_problem"
    phase_p95 = {
        str(row.get("phase")): optional_float(row.get("p95_seconds"))
        for row in as_sequence(summaries.get("hot_path_timing"))
    }
    if (phase_p95.get("risk_state_read") or 0.0) > 5.0 or (
        phase_p95.get("risk_admission") or 0.0
    ) > 5.0:
        return "risk_state_latency_problem"
    if (phase_p95.get("total") or 0.0) > 60.0 or (phase_p95.get("submit") or 0.0) > 10.0:
        return "hot_path_too_slow"
    adverse = as_mapping(summaries.get("adverse_selection"))
    if adverse.get("status") == "possible_adverse_fill_selection":
        return "adverse_fill_selection"
    if count_present(rows, "fill_count") == 0 or count_present(rows, "quote_age_seconds") == 0:
        return "insufficient_data"
    return "execution_ok"


def data_limitations(
    rows: Sequence[Mapping[str, Any]],
    summaries: Mapping[str, Any],
) -> list[str]:
    if not rows:
        return ["insufficient_data:no_attempt_rows_found"]
    limitations: list[str] = []
    if count_present(rows, "submit_response_at") == 0:
        limitations.append("insufficient_data:submit_response_at_missing")
    if count_present(rows, "submit_roundtrip_ms") == 0:
        limitations.append("insufficient_data:submit_roundtrip_ms_not_derivable")
    if count_present(rows, "coinbase_source_ts") == 0:
        limitations.append("insufficient_data:coinbase_source_ts_missing")
    if count_present(rows, "active_context_source") == 0:
        limitations.append("insufficient_data:active_context_evidence_missing")
    if count_present(rows, "counterfactual_pnl_if_available") == 0:
        limitations.append("insufficient_data:implementation_drag_counterfactual_missing")
    if count_present(rows, "realized_pnl") == 0:
        limitations.append("insufficient_data:realized_pnl_missing")
    adverse = as_mapping(summaries.get("adverse_selection"))
    if adverse.get("status") == "insufficient_data":
        limitations.append("insufficient_data:adverse_selection_sample_or_pnl_missing")
    return list(dict.fromkeys(limitations))


def write_execution_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: csv_value(row.get(column)) for column in CSV_COLUMNS})


def render_markdown_report(
    *,
    input_path: Path,
    rows: Sequence[Mapping[str, Any]],
    run_count: int,
    summaries: Mapping[str, Any],
    verdict: BottleneckVerdict,
    limitations: Sequence[str],
) -> str:
    coverage = as_mapping(summaries.get("data_coverage"))
    implementation_drag = as_mapping(summaries.get("implementation_drag"))
    fresh_quote_counterfactual = as_mapping(
        summaries.get("fresh_quote_counterfactual")
    )
    adverse = as_mapping(summaries.get("adverse_selection"))
    dominant_area = as_mapping(summaries.get("dominant_hot_path_area"))
    lines: list[str] = [
        "# Execution Attribution Report",
        "",
        "## Summary",
        "",
        f"- Schema: `{SCHEMA_VERSION}`",
        f"- Input: `{input_path}`",
        f"- Runs: {run_count}",
        f"- Rows: {len(rows)}",
        f"- Bottleneck verdict: `{verdict}`",
        f"- Dominant hot-path area: `{dominant_area.get('dominant_area', 'insufficient_data')}`",
        "",
        "This report is read-only research evidence. It does not authorize live trading, "
        "strategy changes, model promotion, or risk-policy changes.",
        "",
        "## Data coverage",
        "",
        markdown_table(
            ("field", "available", "total", "coverage_pct"),
            as_sequence(coverage.get("field_coverage")),
        ),
        "",
        "## Hot-path timing",
        "",
        "Hot-path area rollup:",
        "",
        markdown_table(
            ("area", "sample_size", "p95_seconds", "max_seconds", "status"),
            as_sequence(dominant_area.get("areas")),
        ),
        "",
        "Raw phase timers:",
        "",
        markdown_table(
            ("phase", "sample_size", "p50_seconds", "p95_seconds", "max_seconds", "status"),
            as_sequence(summaries.get("hot_path_timing")),
        ),
        "",
        "## Freshness at submit / decision",
        "",
        "Quote age buckets:",
        "",
        markdown_table(
            SUMMARY_TABLE_COLUMNS,
            as_sequence(summaries.get("quote_age_bucket_summary")),
        ),
        "",
        "Coinbase age buckets:",
        "",
        markdown_table(
            SUMMARY_TABLE_COLUMNS,
            as_sequence(summaries.get("coinbase_age_bucket_summary")),
        ),
        "",
        "Active context age buckets:",
        "",
        markdown_table(
            SUMMARY_TABLE_COLUMNS,
            as_sequence(summaries.get("active_context_age_bucket_summary")),
        ),
        "",
        "Decision-to-submit latency buckets:",
        "",
        markdown_table(
            SUMMARY_TABLE_COLUMNS,
            as_sequence(summaries.get("decision_to_submit_latency_bucket_summary")),
        ),
        "",
        "Hot-path total latency buckets:",
        "",
        markdown_table(
            SUMMARY_TABLE_COLUMNS,
            as_sequence(summaries.get("hot_path_total_latency_bucket_summary")),
        ),
        "",
        "## Fillability and adverse-selection checks",
        "",
        "Fill vs no-fill/skipped:",
        "",
        markdown_table(
            SUMMARY_TABLE_COLUMNS,
            as_sequence(summaries.get("fill_vs_no_fill_summary")),
        ),
        "",
        "Side buckets:",
        "",
        markdown_table(SUMMARY_TABLE_COLUMNS, as_sequence(summaries.get("side_bucket_summary"))),
        "",
        "Price buckets:",
        "",
        markdown_table(SUMMARY_TABLE_COLUMNS, as_sequence(summaries.get("price_bucket_summary"))),
        "",
        "Decision-edge buckets:",
        "",
        markdown_table(SUMMARY_TABLE_COLUMNS, as_sequence(summaries.get("edge_bucket_summary"))),
        "",
        "Diagnostic class buckets:",
        "",
        markdown_table(
            SUMMARY_TABLE_COLUMNS,
            as_sequence(summaries.get("diagnostic_class_summary")),
        ),
        "",
        "Skip/reject/error reasons:",
        "",
        markdown_table(
            SUMMARY_TABLE_COLUMNS,
            as_sequence(summaries.get("skip_reject_error_reason_summary")),
        ),
        "",
        f"- Adverse-selection status: `{adverse.get('status', 'insufficient_data')}`",
        f"- Basis: {adverse.get('basis', 'insufficient_data')}",
        "",
        "## PnL / implementation-drag estimate",
        "",
        f"- Fresh-quote counterfactual status: `{fresh_quote_counterfactual.get('status', 'unavailable')}`",
        f"- Fresh-quote counterfactual basis: {fresh_quote_counterfactual.get('basis', 'insufficient_data')}",
        "",
        markdown_table(
            ("status", "count"),
            as_sequence(fresh_quote_counterfactual.get("status_counts")),
        ),
        "",
        f"- Status: `{implementation_drag.get('status', 'insufficient_data')}`",
        f"- Estimated drag dollars: {md_value(implementation_drag.get('estimated_drag_dollars'))}",
        f"- Basis: {implementation_drag.get('basis', 'insufficient_data')}",
        "",
        "## Bottleneck verdict",
        "",
        f"`{verdict}`",
        "",
        bottleneck_reason(verdict),
        "",
        "Allowed verdicts: "
        + ", ".join(f"`{value}`" for value in BOTTLENECK_VERDICTS)
        + ".",
        "",
        "## Data limitations",
        "",
    ]
    if limitations:
        lines.extend(f"- `{limitation}`" for limitation in limitations)
    else:
        lines.append("- none_identified")
    lines.extend(
        [
            "",
            "## Recommended next instrumentation or runtime change",
            "",
            "- Record `submit_response_at` in compact attempt artifacts so submit round-trip "
            "latency is directly measurable.",
            "- Record an edge-at-submit or fresh-quote counterfactual before estimating dollars "
            "left on the table.",
            "- Attach settlement/reconciliation PnL once available before drawing adverse-fill "
            "selection conclusions.",
        ]
    )
    return "\n".join(lines) + "\n"


SUMMARY_TABLE_COLUMNS: tuple[str, ...] = (
    "bucket",
    "count",
    "submitted_count",
    "filled_count",
    "fill_rate",
    "avg_decision_edge",
    "avg_realized_pnl",
    "avg_quote_age_seconds",
)


def bottleneck_reason(verdict: BottleneckVerdict) -> str:
    reasons = {
        "execution_ok": "Available sparse evidence does not identify a fill-speed bottleneck.",
        "quote_staleness_problem": "At least one attempt/skip was explicitly gated by stale quotes.",
        "coinbase_staleness_problem": "At least one attempt/skip was gated by stale Coinbase context.",
        "hot_path_too_slow": "Hot-path timing exceeds the conservative MVP thresholds.",
        "adverse_fill_selection": "Available realized PnL suggests filled attempts underperform.",
        "risk_state_latency_problem": "Risk-state read/admission timing dominates the hot path.",
        "insufficient_data": "The input artifacts are too sparse for a bottleneck conclusion.",
    }
    return reasons[verdict]


def markdown_table(columns: Sequence[str], rows: Sequence[Any]) -> str:
    row_maps = [as_mapping(row) for row in rows]
    if not row_maps:
        row_maps = [{column: "insufficient_data" for column in columns}]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _column in columns) + " |",
    ]
    for row in row_maps:
        lines.append("| " + " | ".join(md_value(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def data_status(value: Any) -> str:
    return "insufficient_data" if value is None or value == "" else str(value)


def md_value(value: Any) -> str:
    value = data_status(value)
    return value.replace("|", "\\|")


def numeric_values(values: Sequence[Any] | Any) -> list[float]:
    output: list[float] = []
    for value in values:
        numeric = optional_float(value)
        if numeric is not None:
            output.append(numeric)
    return output


def percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return rounded(ordered[0])
    index = (len(ordered) - 1) * quantile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    value = ordered[lower] * (1 - weight) + ordered[upper] * weight
    return rounded(value)


def mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return rounded(sum(values) / len(values))


def percent(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return rounded(numerator / denominator)


def bucket_name(
    value: float | None,
    buckets: Sequence[tuple[str, float | None, float | None]],
) -> str:
    if value is None:
        return "missing"
    for name, lower, upper in buckets:
        if lower is not None and value < lower:
            continue
        if upper is not None and value >= upper:
            continue
        return name
    return "missing"


def count_present(rows: Sequence[Mapping[str, Any]], field: str) -> int:
    return sum(1 for row in rows if row.get(field) not in (None, ""))


def time_to_expiry_seconds(
    source_row: Mapping[str, Any],
    decision_ts: datetime | None,
) -> float | None:
    existing = first_float(
        source_row.get("time_to_expiry_seconds"),
        source_row.get("seconds_to_expiry"),
    )
    if existing is not None:
        return existing
    close_time = parse_datetime(
        source_row.get("close_time")
        or source_row.get("market_close_time")
        or source_row.get("expiration_time")
    )
    return seconds_between(close_time, decision_ts)


def realized_pnl_from_reconciliation(row: Mapping[str, Any]) -> float | None:
    if not row:
        return None
    settlement_status = text(row.get("settlement_status"))
    if settlement_status == "unsettled":
        return None
    return first_float(row.get("pnl_dollars"), row.get("realized_pnl"))


def seconds_between(later: datetime | None, earlier: datetime | None) -> float | None:
    if later is None or earlier is None:
        return None
    return max(0.0, (later - earlier).total_seconds())


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    try:
        return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return ensure_utc(value).isoformat()


def rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def first_float(*values: Any) -> float | None:
    for value in values:
        numeric = optional_float(value)
        if numeric is not None:
            return numeric
    return None


def optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_int(*values: Any) -> int | None:
    for value in values:
        numeric = optional_float(value)
        if numeric is not None:
            return int(numeric)
    return None


def nested_value(payload: Mapping[str, Any], path: Sequence[str]) -> Any:
    value: Any = payload
    for key in path:
        mapping = as_mapping(value)
        if key not in mapping:
            return None
        value = mapping[key]
    return value


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    return value


def text(value: Any) -> str | None:
    if value is None:
        return None
    output = str(value).strip()
    return output or None


def as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def as_sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-execution-attribution")
    parser.add_argument(
        "--input",
        required=True,
        help="Live run artifact root, run directory, or copied postmortem directory.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for execution_attribution.csv and execution_attribution_report.md.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = generate_execution_attribution(args.input, args.output_dir)
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
