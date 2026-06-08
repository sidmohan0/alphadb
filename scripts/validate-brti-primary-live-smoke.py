#!/usr/bin/env python3
"""Validate BRTI-primary live smoke evidence before live flip completion."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


BRTI_PRIMARY = "brti_primary"
COINBASE_PRIMARY = "coinbase_primary"
DEFAULT_MAX_BRTI_CONTEXT_AGE_SECONDS = 5.0


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if len(args) != 1:
        print("usage: validate-brti-primary-live-smoke.py SMOKE_EVIDENCE_JSON", file=sys.stderr)
        return 2
    payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    failures = validate_smoke_evidence(payload)
    if failures:
        for failure in failures:
            print(f"brti smoke gate failed: {failure}", file=sys.stderr)
        return 1
    print("BRTI-primary live smoke gate passed")
    return 0


def validate_smoke_evidence(payload: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    collector = _mapping_path(payload, "collector", "brti_collector")
    service = _mapping_path(payload, "collector_service", "brti_collector.service")
    latest = _mapping_path(
        payload,
        "latest_context",
        "brti_latest_context",
        "collector.latest_context",
        "brti_collector.latest_context",
    )
    summary = _mapping_path(
        payload,
        "collector.summary",
        "brti_collector.summary",
        "collector.ingest",
        "collector",
    )
    fair_value = _mapping_path(payload, "fair_value_cycle")
    manifest = _mapping_path(
        payload,
        "fair_value_cycle.manifest",
        "manifest",
    )
    market_context = _mapping_path(
        payload,
        "fair_value_cycle.market_context",
        "fair_value_cycle.manifest.market_context",
        "market_context",
    )
    selected_row = _mapping_path(
        payload,
        "fair_value_cycle.selected_row",
        "fair_value_cycle.manifest.selected_row",
        "selected_row",
    )

    _validate_collector_service(service, collector, failures)
    _validate_collector_ingest(summary, failures)
    _validate_latest_context(latest, payload, failures)
    _validate_shared_database(payload, failures)
    _validate_fair_value_cycle(fair_value, manifest, market_context, selected_row, failures)
    _validate_live_guards(payload, fair_value, manifest, failures)
    _validate_schedule_state(payload, failures)
    _validate_evidence_locations(payload, fair_value, failures)
    _validate_expensive_yes_unchanged(payload, failures)
    _validate_rollback(payload, failures)
    return failures


def _validate_collector_service(
    service: Mapping[str, Any],
    collector: Mapping[str, Any],
    failures: list[str],
) -> None:
    desired = _int(service.get("desired_count", collector.get("desired_count")))
    running = _int(service.get("running_count", collector.get("running_count")))
    log_group = _text(service.get("log_group") or collector.get("log_group"))
    restart_behavior = _text(service.get("restart_behavior") or collector.get("restart_behavior"))
    if desired < 1:
        failures.append("collector service desired_count must be at least 1")
    if running < 1:
        failures.append("collector service running_count must be at least 1")
    if not log_group:
        failures.append("collector CloudWatch log_group must be recorded")
    if restart_behavior and restart_behavior != "ecs_service_desired_count":
        failures.append("collector restart_behavior must be ecs_service_desired_count")


def _validate_collector_ingest(summary: Mapping[str, Any], failures: list[str]) -> None:
    if _int(summary.get("accepted")) < 1:
        failures.append("collector accepted must be at least 1")
    if _int(summary.get("raw_events_inserted", summary.get("events_inserted"))) < 1:
        failures.append("collector raw_events_inserted must be at least 1")
    if _int(summary.get("latest_context_updates")) < 1:
        failures.append("collector latest_context_updates must be at least 1")


def _validate_latest_context(
    latest: Mapping[str, Any],
    payload: Mapping[str, Any],
    failures: list[str],
) -> None:
    status = _text(latest.get("status") or latest.get("context_status"))
    if status != "usable":
        failures.append("BRTI latest context status must be usable")
    age_seconds = _age_seconds(latest)
    freshness_limit = _float(
        latest.get("freshness_limit_seconds")
        or latest.get("brti_freshness_limit_seconds")
        or payload.get("brti_freshness_limit_seconds"),
        default=DEFAULT_MAX_BRTI_CONTEXT_AGE_SECONDS,
    )
    if age_seconds == float("inf"):
        failures.append("BRTI latest context age must be recorded")
    elif age_seconds > freshness_limit:
        failures.append("BRTI latest context age must be within freshness limit")


def _validate_shared_database(payload: Mapping[str, Any], failures: list[str]) -> None:
    if payload.get("database_url_secret_match") is True:
        return
    collector_secret = _text(
        payload.get("collector_database_url_secret_arn")
        or _value_path(payload, "collector.database_url_secret_arn")
    )
    fair_value_secret = _text(
        payload.get("fair_value_database_url_secret_arn")
        or _value_path(payload, "fair_value_cycle.database_url_secret_arn")
    )
    if not collector_secret or not fair_value_secret or collector_secret != fair_value_secret:
        failures.append("collector and fair-value worker must use the same DATABASE_URL secret")


def _validate_fair_value_cycle(
    fair_value: Mapping[str, Any],
    manifest: Mapping[str, Any],
    market_context: Mapping[str, Any],
    selected_row: Mapping[str, Any],
    failures: list[str],
) -> None:
    if _bool(
        fair_value.get("task_definition_one_cycle")
        if "task_definition_one_cycle" in fair_value
        else fair_value.get("one_cycle")
    ) is not True:
        failures.append("fair_value_cycle.task_definition_one_cycle must be true")

    sources = [
        _text(fair_value.get("market_context_source")),
        _text(market_context.get("market_context_source")),
        _text(selected_row.get("market_context_source")),
        _text(_value_path(manifest, "config.market_context_source")),
        _text(_value_path(manifest, "runtime_config.snapshot.market_context_source")),
        _text(_value_path(manifest, "runtime_controls.market_context_source")),
    ]
    present_sources = [source for source in sources if source]
    if not present_sources:
        failures.append("fair-value manifest must record market_context_source")
    elif any(source != BRTI_PRIMARY for source in present_sources):
        failures.append("fair-value market_context_source must be brti_primary")

    external_close_source = _text(
        fair_value.get("external_close_source")
        or market_context.get("external_close_source")
        or selected_row.get("external_close_source")
    )
    external_close_from_brti = _bool(
        fair_value.get("external_close_from_brti")
        if "external_close_from_brti" in fair_value
        else market_context.get("external_close_from_brti")
    )
    skip_reason = _text(
        fair_value.get("skip_reason")
        or selected_row.get("skip_reason")
        or selected_row.get("reason")
    )
    if external_close_source == "" and external_close_from_brti is None:
        failures.append("fair-value evidence must record whether external_close came from BRTI")
    if external_close_from_brti is True or external_close_source == "brti_latest_context":
        return
    if skip_reason.startswith("brti_context_"):
        return
    failures.append("fair-value cycle must materialize BRTI context or cleanly BRTI-skip")


def _validate_live_guards(
    payload: Mapping[str, Any],
    fair_value: Mapping[str, Any],
    manifest: Mapping[str, Any],
    failures: list[str],
) -> None:
    runtime_guard = _mapping_path(
        payload,
        "runtime_guard",
        "fair_value_cycle.runtime_guard",
        "fair_value_cycle.manifest.runtime_guard",
    )
    if runtime_guard.get("credentials_present") is not True:
        failures.append("runtime_guard.credentials_present must be true")
    if runtime_guard.get("can_submit_live_orders") is not True:
        failures.append("runtime_guard.can_submit_live_orders must be true")
    live_order_guards_preserved = _bool(
        payload.get("live_order_guards_preserved")
        if "live_order_guards_preserved" in payload
        else fair_value.get("live_order_guards_preserved", manifest.get("live_order_guards_preserved"))
    )
    if live_order_guards_preserved is not True:
        failures.append("live_order_guards_preserved must be true")


def _validate_schedule_state(payload: Mapping[str, Any], failures: list[str]) -> None:
    before = _text(
        payload.get("fair_value_schedule_state_before")
        or payload.get("schedule_state_before")
        or _value_path(payload, "fair_value_cycle.schedule_state_before")
    ).upper()
    after = _text(
        payload.get("fair_value_schedule_state_after")
        or payload.get("schedule_state_after")
        or _value_path(payload, "fair_value_cycle.schedule_state_after")
    ).upper()
    changed = _bool(payload.get("fair_value_schedule_state_changed"))
    if not before or not after:
        failures.append("fair-value schedule state before and after smoke must be recorded")
    elif before != after:
        failures.append("fair-value schedule state must remain unchanged during smoke")
    if changed is True:
        failures.append("fair_value_schedule_state_changed must be false")


def _validate_evidence_locations(
    payload: Mapping[str, Any],
    fair_value: Mapping[str, Any],
    failures: list[str],
) -> None:
    manifest_uri = _text(
        fair_value.get("manifest_uri")
        or payload.get("manifest_uri")
        or _value_path(payload, "evidence_locations.manifest_uri")
    )
    status_uri = _text(
        fair_value.get("status_evidence_uri")
        or payload.get("status_evidence_uri")
        or _value_path(payload, "evidence_locations.status_evidence_uri")
    )
    if not manifest_uri:
        failures.append("fair-value manifest_uri must be recorded")
    if not status_uri:
        failures.append("status_evidence_uri must be recorded")


def _validate_expensive_yes_unchanged(payload: Mapping[str, Any], failures: list[str]) -> None:
    if payload.get("expensive_yes_unchanged") is True:
        return
    before = _text(payload.get("expensive_yes_schedule_state_before")).upper()
    after = _text(payload.get("expensive_yes_schedule_state_after")).upper()
    if not before or not after or before != after:
        failures.append("expensive_yes_live schedule state must be recorded as unchanged")


def _validate_rollback(payload: Mapping[str, Any], failures: list[str]) -> None:
    rollback = _mapping_path(payload, "rollback")
    source = _text(
        rollback.get("market_context_source")
        or rollback.get("source")
        or payload.get("rollback_source")
    )
    command = _text(
        rollback.get("command")
        or rollback.get("runtime_config_command")
        or payload.get("rollback_command")
    )
    if source != COINBASE_PRIMARY:
        failures.append("rollback market_context_source must be coinbase_primary")
    if not command:
        failures.append("rollback command must be recorded")


def _mapping_path(payload: Mapping[str, Any], *paths: str) -> Mapping[str, Any]:
    for path in paths:
        value = _value_path(payload, path)
        if isinstance(value, Mapping):
            return value
    return {}


def _value_path(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _age_seconds(payload: Mapping[str, Any]) -> float:
    for key in (
        "age_seconds",
        "context_age_seconds",
        "brti_context_age_seconds",
        "latest_age_seconds",
    ):
        value = payload.get(key)
        parsed = _float(value, default=float("inf"))
        if parsed != float("inf"):
            return parsed
    for key in ("age_ms", "context_age_ms", "brti_context_age_ms"):
        value = payload.get(key)
        parsed = _float(value, default=float("inf"))
        if parsed != float("inf"):
            return parsed / 1000.0
    return float("inf")


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None


def _float(value: Any, *, default: float = float("inf")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
