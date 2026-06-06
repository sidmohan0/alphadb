#!/usr/bin/env python3
"""Validate one-cycle live-worker smoke evidence before schedule enablement."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping


MAX_P95_RUNTIME_SECONDS = 45.0
MAX_QUOTE_AGE_SECONDS = 15.0
REQUIRED_MIN_CONTRACT_PRICE = 0.25
REQUIRED_MIN_EDGE = 0.0


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if len(args) != 1:
        print("usage: validate-fair-value-live-smoke.py SMOKE_EVIDENCE_JSON", file=sys.stderr)
        return 2
    payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    failures = validate_smoke_evidence(payload)
    if failures:
        for failure in failures:
            print(f"smoke gate failed: {failure}", file=sys.stderr)
        return 1
    print("fair-value live smoke gate passed")
    return 0


def validate_smoke_evidence(payload: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if _float(payload.get("p95_runtime_seconds")) >= MAX_P95_RUNTIME_SECONDS:
        failures.append("p95_runtime_seconds must be < 45")
    if _int(payload.get("overlapping_task_count")) != 0:
        failures.append("overlapping_task_count must be 0")
    if _int(payload.get("stale_task_count")) != 0:
        failures.append("stale_task_count must be 0")

    quote_evidence = _quote_evidence(payload)
    if _quote_source(quote_evidence, payload) != "kalshi_orderbook":
        failures.append("executable quote source must be kalshi_orderbook")
    if _quote_age(quote_evidence, payload) > MAX_QUOTE_AGE_SECONDS:
        failures.append("executable quote age must be <= 15")

    runtime_guard = _runtime_guard(payload)
    if runtime_guard.get("credentials_present") is not True:
        failures.append("runtime_guard.credentials_present must be true")
    if runtime_guard.get("can_submit_live_orders") is not True:
        failures.append("runtime_guard.can_submit_live_orders must be true")
    if payload.get("live_order_guards_preserved") is not True:
        failures.append("live_order_guards_preserved must be true")

    risk_state = _risk_state(payload)
    risk_status = str(risk_state.get("status") or risk_state.get("risk_state_status") or "")
    risk_reason = risk_state.get("reason", risk_state.get("risk_state_reason"))
    if risk_status != "active":
        failures.append("live risk admission state must be active")
    if risk_reason not in (None, "", "fresh"):
        failures.append("live risk admission state must be fresh")

    if _float(_runtime_value(payload, "min_contract_price")) != REQUIRED_MIN_CONTRACT_PRICE:
        failures.append("min_contract_price must be 0.25")
    if _float(_runtime_value(payload, "min_edge")) != REQUIRED_MIN_EDGE:
        failures.append("min_edge must remain 0")
    if payload.get("task_definition_one_cycle") is not True:
        failures.append("task_definition_one_cycle must be true")
    if str(payload.get("schedule_state_before") or "").upper() != "DISABLED":
        failures.append("schedule_state_before must be DISABLED")
    return failures


def _quote_evidence(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("executable_quote", "quote_freshness"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _quote_source(quote_evidence: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    return str(
        quote_evidence.get("source")
        or quote_evidence.get("quote_source")
        or payload.get("quote_source")
        or ""
    )


def _quote_age(quote_evidence: Mapping[str, Any], payload: Mapping[str, Any]) -> float:
    freshness = quote_evidence.get("freshness")
    freshness_map = freshness if isinstance(freshness, Mapping) else {}
    for value in (
        quote_evidence.get("max_quote_age_seconds"),
        quote_evidence.get("quote_age_seconds"),
        freshness_map.get("quote_age_seconds"),
        payload.get("max_quote_age_seconds"),
    ):
        parsed = _float(value)
        if parsed != float("inf"):
            return parsed
    return float("inf")


def _runtime_guard(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    runtime_guard = payload.get("runtime_guard")
    if isinstance(runtime_guard, Mapping):
        return runtime_guard
    runtime_controls = payload.get("runtime_controls")
    if isinstance(runtime_controls, Mapping):
        nested = runtime_controls.get("runtime_guard")
        if isinstance(nested, Mapping):
            return nested
    return {}


def _risk_state(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("live_risk_admission_state", "risk_state", "admission_daily_loss_accounting"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    runtime_controls = payload.get("runtime_controls")
    if isinstance(runtime_controls, Mapping):
        for key in ("admission_daily_loss_accounting", "daily_loss_accounting"):
            value = runtime_controls.get(key)
            if isinstance(value, Mapping):
                return value
    return {}


def _runtime_value(payload: Mapping[str, Any], key: str) -> Any:
    if key in payload:
        return payload[key]
    runtime_controls = payload.get("runtime_controls")
    if isinstance(runtime_controls, Mapping) and key in runtime_controls:
        return runtime_controls[key]
    runtime_config = payload.get("runtime_config")
    if isinstance(runtime_config, Mapping):
        snapshot = runtime_config.get("snapshot")
        if isinstance(snapshot, Mapping) and key in snapshot:
            return snapshot[key]
    return None


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
