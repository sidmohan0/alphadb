#!/usr/bin/env bash
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"

if [ -f logs/pids.txt ]; then
  source logs/pids.txt
fi

a=()
[ -n "${GATE_PID:-}" ] && a+=("$GATE_PID")
[ -n "${AGENT_PID:-}" ] && a+=("$AGENT_PID")

if [ ${#a[@]} -gt 0 ]; then
  kill "${a[@]}" 2>/dev/null || true
fi

if command -v tmux >/dev/null 2>&1 && tmux has-session -t trading-agent 2>/dev/null; then
  tmux kill-session -t trading-agent
fi

echo "Stopped live processes if running."
