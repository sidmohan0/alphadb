#!/usr/bin/env bash
set -euo pipefail

COCKPIT_URL="${COCKPIT_URL:-http://localhost:3000}"
PIN="${ALPHADB_COCKPIT_PIN:-}"
CHECK_PROXY="${CHECK_PROXY:-0}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 1
  fi
}

require_command curl

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
COOKIE_JAR="$TMP_DIR/cookies.txt"
BODY="$TMP_DIR/body.txt"
HEADERS="$TMP_DIR/headers.txt"

if [[ -z "$PIN" ]]; then
  echo "smoke: auth-disabled Cockpit opens"
  curl -fsS "$COCKPIT_URL/" >/dev/null
  STATUS="$(curl -sS -o "$BODY" -w "%{http_code}" "$COCKPIT_URL/api/alphadb/health" || true)"
  if [[ "$STATUS" == "401" ]]; then
    echo "expected auth-disabled /api/alphadb/health not to return 401" >&2
    exit 1
  fi
  echo "smoke: ok"
  exit 0
fi

echo "smoke: unauthenticated AlphaDB API proxy is rejected"
STATUS="$(curl -sS -o "$BODY" -w "%{http_code}" "$COCKPIT_URL/api/alphadb/health" || true)"
if [[ "$STATUS" != "401" ]]; then
  echo "expected unauthenticated /api/alphadb/health to return 401, got $STATUS" >&2
  exit 1
fi

echo "smoke: wrong PIN is rejected"
WRONG_PIN=0000
if [[ "$PIN" == "$WRONG_PIN" ]]; then
  WRONG_PIN=9999
fi
STATUS="$(curl -sS -o "$BODY" -D "$HEADERS" -c "$COOKIE_JAR" -w "%{http_code}" \
  -X POST "$COCKPIT_URL/api/auth/login" \
  --data-urlencode "pin=$WRONG_PIN" \
  --data-urlencode "next=/" || true)"
if [[ "$STATUS" != "302" && "$STATUS" != "303" ]]; then
  echo "expected wrong PIN redirect, got $STATUS" >&2
  exit 1
fi
if grep -iq "set-cookie:" "$HEADERS"; then
  echo "wrong PIN unexpectedly set a cookie" >&2
  exit 1
fi

echo "smoke: correct PIN sets signed cookie"
STATUS="$(curl -sS -o "$BODY" -D "$HEADERS" -c "$COOKIE_JAR" -w "%{http_code}" \
  -X POST "$COCKPIT_URL/api/auth/login" \
  --data-urlencode "pin=$PIN" \
  --data-urlencode "next=/" || true)"
if [[ "$STATUS" != "302" && "$STATUS" != "303" ]]; then
  echo "expected correct PIN redirect, got $STATUS" >&2
  exit 1
fi
if ! grep -iq "set-cookie:" "$HEADERS"; then
  echo "correct PIN did not set a cookie" >&2
  exit 1
fi

echo "smoke: signed cookie opens Cockpit"
curl -fsS -b "$COOKIE_JAR" "$COCKPIT_URL/" >/dev/null

if [[ "$CHECK_PROXY" == "1" ]]; then
  require_command python3
  echo "smoke: signed cookie reaches proxied AlphaDB API health"
  curl -fsS -b "$COOKIE_JAR" "$COCKPIT_URL/api/alphadb/health" -o "$BODY"
  python3 - "$BODY" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)

payload = payload.get("data", payload)
components = {
    component.get("component"): component.get("status")
    for component in payload.get("components", [])
}

if payload.get("ok") is not True:
    raise SystemExit("proxied health did not report ok=true")
if components.get("postgres") != "ok":
    raise SystemExit("proxied health did not report postgres ok")
PY
fi

echo "smoke: ok"
