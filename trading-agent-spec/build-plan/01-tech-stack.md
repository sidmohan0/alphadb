# Tech Stack

## Language: Rust

**Why**: Deterministic latency (no GC pauses when hitting a stop), strong type system for the IPC contract and rule DSL, process isolation is natural, and maps to existing ThreadFork/Tauri skillset.

**Two separate crates**:
- `trading-gate` — enforcement shim binary
- `trading-agent` — strategy + learning binary

Separate `Cargo.toml` files. Gate never imports agent code. Agent never imports gate internals.

## Data: SQLite / DuckDB

**Why**: Analytical queries across thousands of trades (aggregations, window functions) without needing a server process. Append-only event log as source of truth with materialized views for Loop 2 analytics. Single file, zero ops.

SQLite for the primary feedback store. DuckDB considered for heavier analytical queries if needed (compatible with SQLite files).

## Exchange: Coinbase Advanced Trade API

**Why**: REST API that replaced Coinbase Pro. Supports limit/market/stop orders, websocket feeds for real-time data, portfolio management endpoints. Well-documented, reliable for the target volume.

Key endpoints:
- Websocket: real-time candles, orderbook, trades
- REST: order placement, fill history, account state
- Auth: API key + secret (held only by gate process)

## Market Data

- **Primary**: Coinbase websocket for real-time candles and orderbook
- **Supplementary**: Coinglass or similar for funding rates, open interest, liquidation data
- **Historical**: Stored locally for backtesting and counterfactual analysis

## LLM: Claude API (Loop 3 Only)

**Why**: Meta-review analysis requires qualitative reasoning about patterns across quantitative data. Structured input (JSON), structured output (JSON with proposals). Used sparingly — Loop 1 and Loop 2 are pure computation.

Model: Claude Sonnet (cost-effective for structured analysis tasks)

## Dashboard: Tauri

**Why**: Existing expertise from ThreadFork. Local-first (no cloud dependency). Displays live P&L, active positions, rule state, pending proposals, kill switch.

Alternatively: simple web UI served locally, or even a terminal-based dashboard (tui-rs) for v1.

## Project Structure

```
trading-agent/
├── crates/
│   ├── gate/
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── main.rs            # Gate process entry
│   │       ├── config.rs          # Safety YAML + strategy config loader
│   │       ├── validator.rs       # Order validation (all checks)
│   │       ├── rule_engine.rs     # DSL interpreter
│   │       ├── coinbase.rs        # Exchange client
│   │       ├── orders.rs          # Order lifecycle management
│   │       ├── ipc.rs             # Unix socket server
│   │       ├── audit.rs           # Audit log writer
│   │       └── dead_man.rs        # Dead man's switch
│   │
│   └── agent/
│       ├── Cargo.toml
│       └── src/
│           ├── main.rs            # Agent process entry
│           ├── engine.rs          # Core trading loop
│           ├── state.rs           # Portfolio & market state
│           ├── ipc_client.rs      # Gate IPC client
│           ├── strategy/
│           │   ├── mod.rs         # Strategy trait
│           │   ├── mean_reversion.rs
│           │   ├── momentum.rs
│           │   └── signals.rs
│           ├── feedback/
│           │   ├── store.rs       # Trade record database (read + write events)
│           │   ├── loop1.rs       # Per-trade learning
│           │   ├── loop2.rs       # Strategy evolution
│           │   ├── loop3.rs       # Meta-learning (Claude API)
│           │   ├── anomaly.rs     # Pattern detection
│           │   ├── counterfactual.rs
│           │   └── rules.rs       # Rule lifecycle proposals
│           └── data/
│               ├── candles.rs     # Market data ingestion
│               ├── orderbook.rs   # Depth data
│               └── regime.rs      # Regime classification
│
├── config/
│   ├── safety.yaml
│   ├── strategies/
│   └── rules/
│       ├── core/
│       └── active/
│
├── data/                          # Created at runtime
│
├── journal/                       # Created by te-bootstrap
│
├── docs/                          # Created by te-bootstrap
│
└── dashboard/
    └── src/                       # Tauri or TUI
```

## Dependencies (Key Crates)

### Gate
- `tokio` — async runtime for IPC + exchange websocket
- `serde` / `serde_yaml` — config parsing
- `rusqlite` — trade database writes
- `hmac` / `sha2` — Coinbase API auth
- `reqwest` — HTTP client for REST API
- `tungstenite` — websocket client

### Agent
- `tokio` — async runtime
- `rusqlite` — trade database reads
- `serde` / `serde_json` — structured data
- `reqwest` — Claude API client (Loop 3 only)
- Statistical: `statrs` or custom (mean, std, z-score, p-value)
