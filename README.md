# Recursive Self-Improving Trading Agent (MVP)

This repository is a Rust bootstrap implementation of the spec found in `trading-agent-spec/`.

## What is included

- `crates/gate`: enforcement shim (no API keys), deterministic checks, rule DSL, audit log.
- `crates/agent`: strategy + loop scaffold + IPC client.
- `crates/common`: shared IPC/message/data contracts.
- Shared config in `config/` and runtime workspaces under `journal/`, `docs/`, `data/`.

## Quick start (simulation mode)

```bash
# 1) Build all crates
cargo build -q

# 2) Copy env template
cp .env.example .env
# Edit .env as needed
```

## Running processes / live view

I cannot open a UI window from this environment, so use one of the launchers below:

- `./scripts/start-live.sh` (background + log files)
- `./scripts/start-live-tmux.sh` (requires tmux, opens live 2-pane session)

Then watch output:

```bash
tail -f logs/gate.log
# and in another terminal:
tail -f logs/agent.log
```

To stop:

```bash
./scripts/stop-live.sh
```

## Configuration

- `TRADING_GATE_EXCHANGE` (defaults to `coinbase_advanced`)
- `TRADING_GATE_DRY_RUN` (defaults to `true`; set `false` for live execution)
- `COINBASE_API_KEY` (or legacy compatibility env names)
- `COINBASE_API_SECRET` (or legacy compatibility env names)
- `COINBASE_API_PASSPHRASE` (legacy mode only)

## Notes

- This scaffold intentionally keeps the gate responsible for deterministic checks.
- Gate and agent communicate over a newline-delimited JSON protocol on a Unix socket.
- `trading-agent-spec/` contains the original design document.
