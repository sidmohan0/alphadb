# Gate Process (The Shim)

## Why Process-Level Separation

Three problems with in-process enforcement:

1. **Bypass risk.** If strategy engine and execution engine share a process, nothing prevents a code path that skips risk checks. Once Loop 2 is modifying parameters and Loop 3 is proposing structural changes, the agent is effectively writing its own behavior.

2. **Interpretation risk.** If the strategy engine parses the safety YAML and evaluates its own risk, it's self-policing.

3. **Mutation risk.** If the agent process has write access to safety.yaml, the config is one `fs::write` from being neutered.

## Architecture

Two separate OS processes, separate Rust binaries, separate Cargo.toml files:

```
trading-gate    ← enforcement shim (holds API key, safety config)
trading-agent   ← strategy + learning engine (holds nothing sensitive)
```

They communicate only through a Unix domain socket (IPC) and shared filesystem with enforced permissions.

## Startup Sequence

```bash
# Gate starts first, owns the API key, opens the IPC socket
COINBASE_API_KEY=xxx trading-gate --config config/safety.yaml &

# Agent starts second, connects to gate's socket
trading-agent --gate-socket /tmp/trading-gate.sock &
```

If gate dies → agent can't trade (fail closed).
If agent dies → gate manages existing positions (runs stops, no new orders).

## File System Permissions

```
config/
├── safety.yaml          # owner: human, mode: 644
│                        # agent process: READ-ONLY
│                        # gate process: READ-ONLY
├── strategies/          # owner: human, mode: 644
│   └── *.yaml           # agent process: READ-ONLY
└── rules/
    ├── core/            # owner: human, mode: 644 (graduated rules)
    │                    # agent: READ-ONLY
    └── active/          # owner: gate-process, mode: 644
                         # agent proposes via IPC, gate validates and writes

data/
├── audit.log            # owner: gate-process, append-only
├── trades.db            # owner: gate-process (writes fills)
│                        # agent: READ-ONLY
├── proposals/           # owner: agent-process
│                        # agent writes proposals here, gate reads
└── events.log           # owner: agent-process, append-only
```

The agent writes to two places: `proposals/` (wish list) and `events.log` (observations). It reads from `trades.db` and `audit.log` for learning. It can never write to `safety.yaml`, `strategies/`, or `rules/core/`.

## Order Validation Flow

When gate receives a SubmitOrder:

1. Parse and validate request structure
2. Run safety.yaml checks (immutable hard limits)
3. Run strategy-level checks (capital allocation)
4. Run active rule checks (dynamic, from rules/active/)
5. Run slippage check (entry within tolerance of plan)
6. ALL checks must pass — any failure = rejection
7. Log full check vector to audit.log (pass AND fail)
8. If passed: place order with Coinbase, return fill to agent
9. If failed: return rejection with all failed checks

## Dead Man's Switch

Optional: if gate loses contact with agent for > N minutes, auto-liquidate all positions. Configurable in safety.yaml:

```yaml
dead_man_switch:
  enabled: true
  timeout_minutes: 30
  action: liquidate_all  # or: close_new_only
```

## Gate Process Internals

The gate is intentionally simple. It:
- Reads config files at startup (and on SIGHUP for reload)
- Listens on IPC socket
- Validates every request against the rule stack
- Places/manages orders with Coinbase
- Writes to audit log

It does NOT:
- Generate signals
- Optimize parameters
- Run learning loops
- Make judgment calls

The gate is a pure function: `(request, state, rules) → accept | reject`. No creativity, no reasoning, no LLM. Just arithmetic and comparisons.
