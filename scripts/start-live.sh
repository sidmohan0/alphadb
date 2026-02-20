#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo "Missing .env. Create from .env.example and fill credentials first."
  exit 1
fi

# Load .env for this shell only
set -a
# shellcheck disable=SC1091
source .env
set +a

: "${TRADING_GATE_DRY_RUN:=true}"
: "${RUST_LOG:=info}"

mkdir -p logs

if [ "$TRADING_GATE_DRY_RUN" != "true" ]; then
  echo "WARNING: DRY_RUN is disabled. LIVE trading may be executed."
  echo "If you want paper mode, set TRADING_GATE_DRY_RUN=true"
fi

echo "Starting gate and agent (live mode: $([ \"$TRADING_GATE_DRY_RUN\" = true ] && echo disabled || echo enabled))"

echo "Gate log:    $ROOT_DIR/logs/gate.log"
echo "Agent log:   $ROOT_DIR/logs/agent.log"

autosleep=2

nohup sh -lc 'RUST_LOG=info cargo run -p trading-gate 2>&1 | tee -a logs/gate.log' >/dev/null 2>&1 < /dev/null &
GATE_PID=$!
printf 'Started gate PID=%s\n' "$GATE_PID"
sleep "$autosleep"
nohup sh -lc 'RUST_LOG=info cargo run -p trading-agent 2>&1 | tee -a logs/agent.log' >/dev/null 2>&1 < /dev/null &
AGENT_PID=$!
printf 'Started agent PID=%s\n' "$AGENT_PID"

echo "GATE_PID=$GATE_PID" > logs/pids.txt
echo "AGENT_PID=$AGENT_PID" >> logs/pids.txt

echo "Started. Use:"
echo "  tail -f logs/gate.log"
echo "  tail -f logs/agent.log"

echo "To stop:"
echo "  kill $GATE_PID $AGENT_PID"
echo "  or kill -9 with same pids"
