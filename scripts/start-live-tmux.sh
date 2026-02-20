#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo "Missing .env. Create from .env.example and fill credentials first."
  exit 1
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is not installed. Use scripts/start-live.sh instead."
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

SESSION="trading-agent"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Session $SESSION already exists. Recreating with updated layout."
  tmux kill-session -t "$SESSION"
fi

mkdir -p logs
: "${RUST_LOG:=info}"

# Layout:
#  - Top-left: gate
#  - Top-right: agent
#  - Bottom: combined log tail window (about one-third)

tmux new-session -d -s "$SESSION" "bash -lc 'RUST_LOG=info cargo run -p trading-gate 2>&1 | tee -a logs/gate.log'"

# Calculate a rough 1/3 height for logs in the current terminal.
WINDOW_H=$(tmux display-message -p -t "$SESSION:0" '#{window_height}')
LOG_H=$((WINDOW_H / 3))
if [ "$LOG_H" -lt 8 ]; then
  LOG_H=8
fi

# Create full-width bottom log pane first, then split the top pane for agent.
tmux split-window -v -l "$LOG_H" -t "$SESSION:0" "bash -lc '(tail -F logs/gate.log | sed -u "s/^/[GATE] /") & (tail -F logs/agent.log | sed -u "s/^/[AGENT] /")'"
tmux split-window -h -t "$SESSION:0.0" "bash -lc 'RUST_LOG=info cargo run -p trading-agent 2>&1 | tee -a logs/agent.log'"

tmux rename-window -t "$SESSION:0" "live"

# Label panes by command for stability.
GATE_PANE=$(tmux list-panes -t "$SESSION:0" -F '#{pane_id}@@#{pane_start_command}' | awk -F'@@' '$2 ~ /cargo run -p trading-gate/ {print $1; exit}')
AGENT_PANE=$(tmux list-panes -t "$SESSION:0" -F '#{pane_id}@@#{pane_start_command}' | awk -F'@@' '$2 ~ /cargo run -p trading-agent/ {print $1; exit}')
LOG_PANE=$(tmux list-panes -t "$SESSION:0" -F '#{pane_id}@@#{pane_start_command}' | awk -F'@@' '$2 ~ /tail -f logs\/gate\.log logs\/agent\.log/ {print $1; exit}')

[ -n "$GATE_PANE" ] && tmux select-pane -t "$GATE_PANE" -T "gate"
[ -n "$AGENT_PANE" ] && tmux select-pane -t "$AGENT_PANE" -T "agent"
[ -n "$LOG_PANE" ] && tmux select-pane -t "$LOG_PANE" -T "logs"

# Make pane titles visible in-window.
tmux set -w -t "$SESSION:0" pane-border-status top
# Use each pane's name as a label at top border.
tmux set -w -t "$SESSION:0" pane-border-format '#{pane_title}'

tmux select-pane -t "$GATE_PANE"

echo "Session started. Attach with: tmux attach -t $SESSION"
