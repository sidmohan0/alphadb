# Infrastructure Skills

## te-bootstrap — Trading Workspace Setup

**Purpose**: Scaffolds the journal, docs, config, and data structure.

**Output structure**:

```
journal/
  theses/               ← Active trade theses
  plans/active/         ← Active trade plans
  plans/completed/      ← Archived trades
  research/             ← Market research
  spikes/               ← Backtests & paper trades
  scratchpad.md         ← Real-time observations
  
docs/
  strategies/           ← Strategy documentation
  runbooks/             ← Personal trading rules
  retired-rules/        ← Archived rules with retirement evidence
  risk-rules.md         ← Hard risk limits (non-negotiable)
  edge-inventory.md     ← Evidence-backed edge catalog
  anti-patterns.md      ← Documented mistakes (compounding from te-learn)
  market-regimes.md     ← Regime detection criteria
  
config/
  safety.yaml           ← Hard limits, kill switches (human-only)
  strategies/           ← Strategy configs with parameter bounds
  rules/
    core/               ← Graduated rules (human-editable only)
    active/             ← Dynamic rules (gate-mediated writes)
  
data/
  trades.db             ← SQLite feedback store
  audit.log             ← Append-only gate audit log
  events.log            ← Append-only agent event log
  proposals/            ← Pending evolution proposals
    pending/            ← Awaiting human approval
    applied/            ← Applied proposals (audit trail)
    rejected/           ← Rejected proposals (audit trail)
  portfolio/
    snapshots/          ← Daily portfolio state
    equity-curve.csv    ← Daily mark-to-market
  performance/
    by-strategy.csv     ← Aggregated metrics per strategy
    by-rule.csv         ← Aggregated metrics per rule
    by-regime.csv       ← Performance segmented by regime
    meta-metrics.csv    ← Loop 3 inputs
```

**Key Constraint**: Minimal impact — create if missing, never overwrite. File system permissions enforced (see enforcement/02-gate-process.md).

---

## te-screener — Opportunity Scanning

**Purpose**: Scan for trade setups matching defined strategy criteria. Interactive prioritization.

**Workflow**:
- Phase 0: Load active strategy configs
- Phase 1: Scan market data for setups matching each strategy's entry criteria
- Phase 2: Rank by signal strength and strategy allocation capacity
- Phase 3: Present candidates (autonomous: auto-proceed; manual: human scores/promotes/defers)

**Autonomous mode**: Integrated into the core runtime loop. Signal generation IS the screener.

---

## te-workflow — Orchestrator

**Purpose**: Enforce full lifecycle sequence and artifact contracts between phases.

**Phase sequence**: Thesis → [Research] → [Spike] → Plan → Risk-Size → Execute → Manage → Exit → Review → Learn

**Re-entry rules**: If risk-size fails, return to plan. If review finds critical issues, they become inputs to future thesis quality.

---

## te-market-context — Market Regime Detection

**Purpose**: Maintain current market regime classification with evidence. Updated continuously.

**Regime classifications**:
- `trending_bull` — sustained uptrend with healthy pullbacks
- `trending_bear` — sustained downtrend
- `ranging` — price oscillating within defined range
- `volatile_mean_reverting` — high volatility but reverting to levels
- `volatile_crisis` — high volatility with directional momentum (tail events)
- `low_volatility_compression` — tightening ranges, often precedes breakout

**Evidence sources**: Realized volatility, ATR, trend indicators (ADX, moving average slopes), volume patterns, correlation regime (risk-on vs risk-off), funding rates.

**Why this matters**: Rules and strategies have regime-conditional behavior. A rule validated in `ranging` may be harmful in `volatile_crisis`. The regime classification is a load-bearing dependency for the entire rule system.

**Accuracy tracking**: Loop 3 evaluates whether regime classifications were correct in hindsight, and can trigger improvements to regime detection methodology.
