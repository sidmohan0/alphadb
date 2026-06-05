#!/usr/bin/env bash
set -euo pipefail

COCKPIT_URL="${COCKPIT_URL:-http://localhost:${ALPHADB_COCKPIT_PORT:-3000}}"
ALPHADB_API_URL="${ALPHADB_API_URL:-http://localhost:${ALPHADB_DASHBOARD_PORT:-8501}}"
TIMEOUT_SECONDS="${ALPHADB_LOCAL_SMOKE_TIMEOUT_SECONDS:-120}"
PYTHON_BIN="${PYTHON_BIN:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python || true)"
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "error: python3 or python is required for JSON validation" >&2
  exit 1
fi

wait_for_url() {
  local label="$1"
  local url="$2"
  local deadline=$((SECONDS + TIMEOUT_SECONDS))

  while ((SECONDS < deadline)); do
    if curl -fsS -o /dev/null "$url" >/dev/null 2>&1; then
      echo "ok: ${label} reachable at ${url}"
      return 0
    fi
    sleep 2
  done

  echo "error: ${label} was not reachable at ${url} within ${TIMEOUT_SECONDS}s" >&2
  return 1
}

assert_alphadb_health() {
  local url="$1"
  local response
  response="$(curl -fsS "$url")"
  RESPONSE="$response" "$PYTHON_BIN" - <<'PY'
import json
import os
import sys

payload = json.loads(os.environ["RESPONSE"])
if payload.get("ok") is not True:
    raise SystemExit(f"health envelope was not ok: {payload!r}")

data = payload.get("data")
if not isinstance(data, dict) or data.get("ok") is not True:
    raise SystemExit(f"AlphaDB health payload was not ok: {payload!r}")

components = data.get("components") or []
postgres = next((item for item in components if item.get("component") == "postgres"), None)
if not postgres or postgres.get("status") != "ok":
    raise SystemExit(f"Postgres health was not ok: {payload!r}")

sys.stdout.write("ok: Cockpit /api/alphadb/health reached Python AlphaDB API\n")
PY
}

wait_for_url "Python AlphaDB API compatibility health" "${ALPHADB_API_URL}/healthz"
wait_for_url "Cockpit" "${COCKPIT_URL}"
assert_alphadb_health "${COCKPIT_URL}/api/alphadb/health"
