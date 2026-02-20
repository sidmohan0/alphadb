# System Overview

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    TRADING AGENT RUNTIME                          │
│                                                                  │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌───────────┐ │
│  │  STRATEGY   │  │  EXECUTION │  │  RISK      │  │  DATA     │ │
│  │  ENGINE     │  │  ENGINE    │  │  ENGINE    │  │  ENGINE   │ │
│  │             │  │            │  │            │  │           │ │
│  │ Signal gen  │  │ Coinbase   │  │ Hard gates │  │ Market    │ │
│  │ Thesis gen  │  │ Order mgmt │  │ Position   │  │ Candles   │ │
│  │ Entry/exit  │  │ Fill track │  │ Portfolio  │  │ Order     │ │
│  │ rules       │  │            │  │ Greeks     │  │ book      │ │
│  └──────┬──────┘  └──────┬─────┘  └──────┬─────┘  └─────┬─────┘ │
│         │                │               │               │       │
│  ┌──────▼────────────────▼───────────────▼───────────────▼─────┐ │
│  │                    EVENT BUS / STATE STORE                   │ │
│  │  Every action, decision, and observation is a logged event  │ │
│  └──────┬────────────────────────────────────────────────┬─────┘ │
│         │                                                │       │
│  ┌──────▼──────────────┐                  ┌──────────────▼─────┐ │
│  │  LOOP 1: TRADE      │                  │  FEEDBACK          │ │
│  │  LEARNING           │                  │  STORE             │ │
│  │  (after every trade)│                  │  (append-only log) │ │
│  └──────┬──────────────┘                  └────────────────────┘ │
│         │                                                        │
│  ┌──────▼──────────────┐  ┌────────────────────┐                │
│  │  LOOP 2: STRATEGY   │  │  LOOP 3: META      │                │
│  │  EVOLUTION          │  │  LEARNING           │                │
│  │  (every N trades    │  │  (every M evolution │                │
│  │   or on schedule)   │  │   cycles)           │                │
│  └─────────────────────┘  └────────────────────┘                │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  HUMAN DASHBOARD                                             │ │
│  │  Live P&L │ Active rules │ Proposals │ Kill switch           │ │
│  └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

## Process-Level Separation

The system runs as two separate OS processes:

```
┌─────────────────────┐         ┌─────────────────────┐
│   AGENT PROCESS     │         │   GATE PROCESS      │
│   (trading-agent)   │         │   (trading-gate)     │
│                     │         │                     │
│  Strategy Engine    │         │  Rule Engine        │
│  Loop 1/2/3         │   IPC   │  Risk Calculator    │
│  Signal Generation  │────────►│  Safety Limits      │
│                     │         │  Order Validator    │
│  CANNOT hold a      │◄────────│                     │
│  Coinbase API key   │  result │  HOLDS the API key  │
│                     │         │  HOLDS safety.yaml  │
└─────────────────────┘         │         │           │
                                │         ▼           │
                                │  ┌─────────────┐   │
                                │  │ Coinbase API │   │
                                │  └─────────────┘   │
                                └─────────────────────┘
```

The agent process never gets the API key. It sends *intent* to the gate process, which decides whether to execute. This is the same pattern as a web frontend that can't talk directly to a database — it goes through an API server that enforces authorization.

## Core Runtime Loop

The agent runs on 1-5 minute candle intervals:

```
while True:
    1. OBSERVE   — market state, portfolio state, active rules
    2. EVALUATE  — check exit signals on existing positions
    3. GENERATE  — produce new entry signals
    4. VALIDATE  — every signal goes through risk gates (via gate process)
    5. EXECUTE   — gate process places orders for approved signals
    6. LEARN     — Loop 1 processes every completed trade immediately
    7. SLEEP     — wait for next candle
```

Every iteration produces logged events. Every blocked entry gets counterfactual tracking. Every fill gets timestamped. The feedback store grows continuously.

## Data Flow

```
Market Data ──► Strategy Engine ──► Signals ──► Gate Process ──► Coinbase
                                                    │
                                              Audit Log ──► Feedback Store
                                                                  │
                                                    ┌─────────────┘
                                                    ▼
                                              Loop 1 (per-trade)
                                                    │
                                                    ▼
                                              Loop 2 (evolution)
                                                    │
                                                    ▼
                                              Loop 3 (meta)
                                                    │
                                                    ▼
                                              Rule/Parameter Changes ──► Gate Process
```

## Failure Modes

| Failure | Behavior |
|---------|----------|
| Gate process dies | Agent cannot trade. Correct failure mode (fail closed). |
| Agent process dies | Gate manages existing positions (runs stops). No new orders accepted. Optional auto-liquidation after timeout. |
| Coinbase API down | Gate rejects all orders until connectivity restored. Existing stop orders live on exchange. |
| Market data stale | Agent detects stale candles, halts signal generation. |
| IPC socket broken | Agent retries connection. No orders during disconnection. |
