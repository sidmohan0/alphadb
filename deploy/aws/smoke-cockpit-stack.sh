#!/usr/bin/env bash
set -euo pipefail

PROFILE="${AWS_PROFILE:-alphadb}"
REGION="${AWS_REGION:-us-east-2}"
STACK_NAME="${STACK_NAME:-alphadb-cockpit}"
COCKPIT_URL="${COCKPIT_URL:-}"
COCKPIT_PIN_SECRET_ARN="${COCKPIT_PIN_SECRET_ARN:-}"

aws_cli() {
  aws --profile "$PROFILE" --region "$REGION" "$@"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 1
  fi
}

stack_output() {
  aws_cli cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" \
    --output text
}

require_command aws
require_command curl
require_command python3

if [[ -z "$COCKPIT_URL" ]]; then
  COCKPIT_URL="$(stack_output DashboardUrl)"
fi

if [[ -z "$COCKPIT_URL" || "$COCKPIT_URL" == "None" ]]; then
  echo "missing COCKPIT_URL or DashboardUrl stack output" >&2
  exit 1
fi

if [[ -z "$COCKPIT_PIN_SECRET_ARN" ]]; then
  echo "missing COCKPIT_PIN_SECRET_ARN" >&2
  exit 1
fi

PIN="$(aws_cli secretsmanager get-secret-value \
  --secret-id "$COCKPIT_PIN_SECRET_ARN" \
  --query SecretString \
  --output text)"

if [[ -z "$PIN" || "$PIN" == "None" ]]; then
  echo "Cockpit PIN secret did not return a SecretString value" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
COOKIE_JAR="$TMP_DIR/cookies.txt"
BODY="$TMP_DIR/body.txt"
HEADERS="$TMP_DIR/headers.txt"

echo "smoke: Cockpit healthz"
curl -fsS "$COCKPIT_URL/healthz" >/dev/null

echo "smoke: unauthenticated AlphaDB API proxy is rejected"
STATUS="$(curl -sS -o "$BODY" -w "%{http_code}" "$COCKPIT_URL/api/alphadb/health" || true)"
if [[ "$STATUS" != "401" ]]; then
  echo "expected unauthenticated /api/alphadb/health to return 401, got $STATUS" >&2
  cat "$BODY" >&2 || true
  exit 1
fi

echo "smoke: Cockpit PIN login sets signed cookie"
STATUS="$(curl -sS -o "$BODY" -D "$HEADERS" -c "$COOKIE_JAR" -w "%{http_code}" \
  -X POST "$COCKPIT_URL/api/auth/login" \
  --data-urlencode "pin=$PIN" \
  --data-urlencode "next=/" || true)"
if [[ "$STATUS" != "302" && "$STATUS" != "303" ]]; then
  echo "expected PIN login redirect, got $STATUS" >&2
  cat "$BODY" >&2 || true
  exit 1
fi
if ! grep -iq "set-cookie:" "$HEADERS"; then
  echo "PIN login did not set a cookie" >&2
  exit 1
fi

echo "smoke: signed cookie opens Cockpit"
curl -fsS -b "$COOKIE_JAR" "$COCKPIT_URL/" >/dev/null

echo "smoke: signed cookie reaches proxied AlphaDB API health"
curl -fsS -b "$COOKIE_JAR" "$COCKPIT_URL/api/alphadb/health" -o "$BODY"
python3 - "$BODY" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)

components = {
    component.get("component"): component.get("status")
    for component in payload.get("components", [])
}

if payload.get("ok") is not True:
    raise SystemExit("proxied health did not report ok=true")
if components.get("postgres") != "ok":
    raise SystemExit("proxied health did not report postgres ok")
PY

echo "smoke: ok"
