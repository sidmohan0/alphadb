# Artifact Chain

## Every Trade Produces a Traceable Chain

```
journal/theses/<slug>-thesis.md        ← Why (conviction + invalidation)
journal/research/<slug>-research.md    ← Evidence (optional)
journal/spikes/<slug>-spike.md         ← Backtest/paper results (optional)
journal/plans/active/<slug>-plan.md    ← How (exact instruments, levels, sizing)
  └─ ## Progress                       ← Timestamped fill log
  └─ ## Position Adjustments           ← Rolls, hedges, scale events
  └─ ## Review Findings                ← Post-trade analysis
  └─ ## P&L Summary                    ← Final numbers
journal/plans/completed/<slug>-plan.md ← Archived after learning
```

## Slug Convention

All artifacts for a single trade share one slug:

```
YYYY-MM-DD-<direction>-<instrument>-<catalyst>
```

Examples:
- `2026-02-18-bearish-spy-iran-escalation`
- `2026-02-20-long-eth-funding-reversion`
- `2026-03-01-neutral-btc-vol-crush`

One slug per trade — never create a second slug for the same position.

## Thesis Frontmatter

```yaml
slug: 2026-02-20-long-eth-funding-reversion
status: active
date: 2026-02-20T14:30:00Z
direction: long
conviction: medium
time_horizon: swing
catalyst_type: statistical
plan_mode: swing
strategy: mean-reversion-funding

invalidation_conditions:
  - type: price_below
    instrument: ETH-USD
    level: 2200
    note: "Breaks support structure"
  - type: indicator_above
    indicator: funding_rate_zscore
    level: 1.5
    note: "Funding normalizes before entry"
  - type: date_after
    date: 2026-02-25
    note: "Time stop - thesis expired"
```

The `invalidation_conditions` use a structured, parseable format so that monitoring scripts can check them mechanically against live data. Prose context lives in the `note` field; the gate operates on the structured fields.

## Plan Required Sections

```markdown
## Thesis Summary
## Instrument Selection (why these specific contracts)
## Entry Criteria (concrete, falsifiable conditions)
## Position Sizing (exact quantities, computed from risk rules)
## Stop Loss (hard stop, not mental — must be placed as order)
## Profit Targets (scaled exits with specific levels)
## Max Loss (hard dollar amount)
## Time Stop (expiration date)
## Scenario Analysis
  - Best case
  - Base case  
  - Worst case
  - Black swan
## Correlation Risk (how this interacts with existing positions)
## Decision Log (append-only)
## Progress (timestamped fill log, append-only)
```

## Canonical Trade Record (Computed, Not Self-Reported)

```yaml
# data/trades/2026-02-20-long-eth-funding-reversion.yaml
slug: 2026-02-20-long-eth-funding-reversion
thesis_ref: journal/theses/2026-02-20-long-eth-funding-reversion.md
plan_ref: journal/plans/completed/2026-02-20-long-eth-funding-reversion.md

entry:
  timestamp: 2026-02-20T14:42:00Z
  instrument: ETH-USD
  side: buy
  quantity: 0.5
  price: 2405.00
  planned_price: 2400.00
  slippage: 5.00
  
adjustments:
  - timestamp: 2026-02-21T10:15:00Z
    action: stop_tightened
    from: 2350.00
    to: 2380.00
    reason: plan_scale_out
    planned: true

exit:
  timestamp: 2026-02-22T11:30:00Z
  price: 2520.00
  planned_target: 2550.00
  reason: target_near_hit
  deviation: false

pnl:
  gross: 57.50
  commissions: 1.20
  net: 56.30
  
computed_metrics:
  max_adverse_excursion: -35.00   # worst drawdown during hold
  max_favorable_excursion: 125.00 # best unrealized gain
  mfe_capture_ratio: 0.46        # captured 46% of available move
  hold_duration_minutes: 2688
  planned_hold_minutes: 7200
  
rules_active_during_trade:
  - max-single-trade-2pct (passed)
  - vix-above-25-half-size (did not fire)

rules_that_blocked_entry: []

thesis_outcome:
  direction_correct: true
  catalyst_occurred: true
  invalidation_triggered: false
  target_reached: false

tags: [mean-reversion, funding, eth, swing]
regime_at_entry: ranging
regime_at_exit: ranging
```

Every field is either populated automatically from broker fill data or computed from plan/thesis artifacts. Nothing is self-reported.
