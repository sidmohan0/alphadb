#!/usr/bin/env python3
"""Validate redacted Cockpit portfolio smoke output."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


MISSING_CREDENTIALS_DETAIL = "missing_kalshi_credentials"
MISSING_CREDENTIALS_TEXT = "Kalshi credentials unavailable"


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if len(args) != 1:
        print("usage: validate-cockpit-portfolio-smoke.py <json-body-path>", file=sys.stderr)
        return 2

    try:
        payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"portfolio smoke response was not valid JSON: {exc}", file=sys.stderr)
        return 1

    try:
        report = validate_payload(payload)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(report)
    return 0


def validate_payload(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        raise ValueError("portfolio smoke response was not a JSON object")
    if payload.get("ok") is False:
        raise ValueError("portfolio smoke upstream API returned ok=false")

    live_payload = payload.get("data", payload)
    if not isinstance(live_payload, Mapping):
        raise ValueError("portfolio smoke data was not a JSON object")

    encoded = json.dumps(live_payload, sort_keys=True)
    if MISSING_CREDENTIALS_TEXT in encoded:
        raise ValueError("portfolio smoke still reports Kalshi credentials unavailable")

    balance = live_payload.get("portfolio_balance")
    if not isinstance(balance, Mapping):
        raise ValueError("portfolio smoke response did not include portfolio_balance")

    status = _clean_value(balance.get("status") or "unknown")
    source = _clean_value(balance.get("source") or "unknown")
    stale = _clean_value(balance.get("stale"))
    detail = _clean_value(balance.get("detail"))

    if detail == MISSING_CREDENTIALS_DETAIL:
        raise ValueError("portfolio smoke still reports missing_kalshi_credentials")

    if status == "ok":
        return f"smoke: portfolio credentials accepted (status={status} source={source} stale={stale})"

    if detail:
        return f"smoke: portfolio unavailable after credential check (status={status} detail={detail})"
    return f"smoke: portfolio unavailable after credential check (status={status})"


def _clean_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return text[:160]


if __name__ == "__main__":
    raise SystemExit(main())
