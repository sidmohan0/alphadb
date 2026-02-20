# Recursive Self-Improving Crypto Trading Agent

## Specification & Architecture Document

> Designed as an adaptation of the Harness Engineering skill pack pattern — gate-driven, artifact-first, agent-native — applied to autonomous cryptocurrency trading.

---

## Origin

This specification emerged from analyzing the [Harness Engineering](https://github.com/harness-engineering) skill pack, a 17-skill, gate-driven software delivery lifecycle framework. The core insight: Harness solves a universal problem — turning fuzzy intent into disciplined, evidence-backed execution with compounding learning loops. Trading has the same pathologies (tribal knowledge, undisciplined execution, no learning loop, documentation entropy) and benefits from the same architectural solution.

## Core Design Properties

| Property | Description |
|----------|-------------|
| **Artifact-first** | Theses, plans, fills, reviews committed to structured records — not in memory or chat |
| **Gate-driven** | Each phase has explicit entry/exit criteria enforced by deterministic checks |
| **Agent-native** | Designed for autonomous execution with human oversight at defined approval boundaries |
| **Deterministic enforcement** | 13 of 15 invariants are fully computable from market data, fills, and portfolio state |
| **Three-loop recursion** | Per-trade learning → strategy evolution → meta-learning, each operating on different timescales |
| **Process-level safety** | Gate process (shim) sits between agent and exchange; agent never holds API keys |
| **Asymmetric permissions** | Agent can always tighten risk (safe); can never loosen risk without human approval |

## Key Differentiator

Most trading systems are single-loop: trade → review → maybe adjust. This system has three nested feedback loops where each loop improves the loop below it. The compressed timeframe of crypto scalping (50-200 trades/day) means the recursive flywheel spins 50x faster than a human swing trader's learning cycle, achieving meaningful self-improvement in weeks rather than months.

## Document Structure

```
trading-agent-spec/
│
├── README.md                          ← You are here
│
├── architecture/
│   ├── 01-system-overview.md          ← High-level architecture and data flow
│   ├── 02-workflow-phases.md          ← Canonical trade lifecycle (thesis → exit → learn)
│   └── 03-artifact-chain.md          ← What gets produced at each phase
│
├── skills/
│   ├── 01-skill-structure.md          ← Skill format and conventions
│   ├── 02-lifecycle-skills.md         ← 8 lifecycle skills (thesis through exit)
│   ├── 03-learning-skills.md          ← 3 quality & learning skills
│   └── 04-infrastructure-skills.md    ← 4 infrastructure skills
│
├── feedback-loops/
│   ├── 01-three-loop-overview.md      ← The recursive self-improvement model
│   ├── 02-loop1-trade-learning.md     ← Per-trade learning (after every trade)
│   ├── 03-loop2-strategy-evolution.md ← Rule efficacy, parameter optimization, counterfactuals
│   ├── 04-loop3-meta-learning.md      ← Process effectiveness audit
│   └── 05-rule-lifecycle.md           ← How rules are born, validated, graduated, and retired
│
├── enforcement/
│   ├── 01-deterministic-gates.md      ← The three tiers of determinism
│   ├── 02-gate-process.md             ← The shim architecture (process-level separation)
│   ├── 03-ipc-contract.md             ← The API between agent and gate
│   ├── 04-rule-dsl.md                 ← Constrained rule language for dynamic rules
│   └── 05-safety-config.md            ← Hard limits, kill switches, permissions
│
├── data/
│   ├── 01-data-architecture.md        ← Schema, storage, derived data
│   └── 02-trade-record-schema.md      ← Canonical trade record format
│
└── build-plan/
    ├── 01-tech-stack.md               ← Rust, SQLite, Coinbase API, Tauri, Claude API
    └── 02-build-sequence.md           ← 8-week build plan
```

## Non-Negotiable Invariants

| # | Invariant | Deterministic? | Enforced By |
|---|-----------|----------------|-------------|
| 1 | No entry without thesis that passes lint | Tier 2 | te-thesis-lint |
| 2 | Invalidation condition contains concrete falsifiable value | Tier 2 | te-thesis-lint (regex) |
| 3 | Risk sizing passes all mechanical checks | Tier 1 | te-risk-size-lint |
| 4 | Single trade risk ≤ defined % of account | Tier 1 | te-risk-size (computed) |
| 5 | Portfolio aggregate risk within limits | Tier 1 | te-risk-size (computed) |
| 6 | Hard stop order verified as placed (not mental) | Tier 1 | te-execute (broker API) |
| 7 | P&L always computed from fills, never self-reported | Tier 1 | te-exit (computed) |
| 8 | Plan deviations flagged automatically from fills vs. plan | Tier 1 | te-review (computed) |
| 9 | Stop violations detected from order history | Tier 1 | te-review (computed) |
| 10 | Critical/high findings produce durable guardrail (file diff exists) | Tier 1 | te-learn-lint |
| 11 | Risk rules additive-only (loosening requires full review) | Tier 2 | te-runbook-audit |
| 12 | 3+ consecutive strategy losses trigger mandatory strategy review | Tier 1 | te-learn (computed) |
| 13 | Time stop mechanically enforced | Tier 1 | te-manage (date comparison) |
| 14 | No entry during restricted windows (configurable) | Tier 1 | te-execute (timestamp) |
| 15 | Default safe action is NO-TRADE | Tier 1 | te-risk-size |
