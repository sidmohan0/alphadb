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
    if _float(payload.get("max_quote_age_seconds")) > MAX_QUOTE_AGE_SECONDS:
        failures.append("max_quote_age_seconds must be <= 15")
    if _float(payload.get("min_contract_price")) != REQUIRED_MIN_CONTRACT_PRICE:
        failures.append("min_contract_price must be 0.25")
    if _float(payload.get("min_edge")) != REQUIRED_MIN_EDGE:
        failures.append("min_edge must remain 0")
    if payload.get("task_definition_one_cycle") is not True:
        failures.append("task_definition_one_cycle must be true")
    if payload.get("live_order_guards_preserved") is not True:
        failures.append("live_order_guards_preserved must be true")
    if str(payload.get("schedule_state_before") or "").upper() != "DISABLED":
        failures.append("schedule_state_before must be DISABLED")
    return failures


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
