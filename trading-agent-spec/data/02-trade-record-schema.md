# Canonical Trade Record Schema

## Design Principle

Every field is either populated automatically from broker fill data or computed from plan/thesis artifacts. Nothing is self-reported. P&L is always arithmetic, never judgment.

## Full Record

```yaml
# data/trades/2026-02-20-long-eth-funding-reversion.yaml

# === IDENTITY ===
slug: 2026-02-20-long-eth-funding-reversion
strategy: mean-reversion-funding
thesis_ref: journal/theses/2026-02-20-long-eth-funding-reversion.md
plan_ref: journal/plans/completed/2026-02-20-long-eth-funding-reversion.md

# === ENTRY (from broker fill data) ===
entry:
  timestamp: 2026-02-20T14:42:00.123Z
  instrument: ETH-USD
  side: buy
  quantity: 0.5
  price: 2405.00                    # actual fill
  planned_price: 2400.00            # from plan
  slippage: 5.00                    # computed: actual - planned
  order_type: limit
  order_id: cb-order-abc123

# === STOP (from broker order data) ===
stop:
  initial_price: 2350.00
  initial_order_id: cb-order-def456
  current_price: 2380.00            # after tightening
  moved_count: 1
  moved_direction: tightened
  moves:
    - timestamp: 2026-02-21T10:15:00Z
      from: 2350.00
      to: 2380.00
      reason: plan_scale_out
      planned: true

# === ADJUSTMENTS (from broker fill data) ===
adjustments:
  - timestamp: 2026-02-21T10:15:00Z
    action: stop_tightened
    from: 2350.00
    to: 2380.00
    reason: plan_scale_out
    planned: true                   # was this in the plan?

# === EXIT (from broker fill data) ===
exit:
  timestamp: 2026-02-22T11:30:00.456Z
  price: 2520.00                    # actual fill
  planned_target: 2550.00           # from plan
  slippage: -30.00                  # exited below target
  reason: target_near_hit           # from enum
  deviation: false
  deviation_justification: null     # required if deviation=true
  order_id: cb-order-ghi789

# === P&L (always computed, never self-reported) ===
pnl:
  gross: 57.50                      # (2520 - 2405) × 0.5
  commissions: 1.20
  net: 56.30                        # gross - commissions
  return_pct: 0.0478                # net / entry_notional
  risk_reward_actual: 2.30          # net / (entry - stop) × quantity

# === COMPUTED METRICS ===
computed_metrics:
  max_adverse_excursion: -35.00     # worst drawdown during hold
  max_favorable_excursion: 125.00   # best unrealized gain
  mfe_capture_ratio: 0.46           # pnl / mfe — captured 46% of move
  hold_duration_minutes: 2688
  planned_hold_minutes: 7200
  hold_ratio: 0.37                  # held 37% of planned duration

# === BEHAVIORAL METRICS (computed from fills vs plan) ===
behavioral:
  deviation_count: 0                # fills not in plan
  unplanned_scale_count: 0          # adds/trims not in plan
  stop_violation: false             # did actual exit breach stop?
  stop_violation_amount: 0.00

# === CONTEXT ===
regime_at_entry: ranging
regime_at_exit: ranging
market_conditions_at_entry:
  funding_rate_zscore: -2.3
  volume_ratio: 1.1
  realized_vol_24h: 0.45

# === RULE TRACKING ===
rules_active_during_trade:
  - rule_id: max-single-trade-2pct
    fired: false
    check_value: 0.018
    check_limit: 0.020
  - rule_id: vix-above-25-half-size
    fired: false
    note: "Rule not applicable (crypto)"

rules_that_blocked_entry: []

# === THESIS OUTCOME (computed) ===
thesis_outcome:
  direction_correct: true           # entry side matches pnl sign
  catalyst_occurred: true           # from plan (manually confirmed or auto)
  invalidation_triggered: false     # price never hit invalidation level
  target_reached: false             # exit before target
  time_stop_triggered: false

# === CLASSIFICATION ===
tags: [mean-reversion, funding, eth, swing]
status: closed                      # open | closed | archived
```

## What Gets Computed vs Stored

| Field | Source | When |
|-------|--------|------|
| Entry price, quantity, timestamp | Broker fill API | At fill |
| Exit price, timestamp | Broker fill API | At fill |
| P&L (gross, net, return) | Computed from fills | At exit |
| Slippage | Computed: actual - planned | At fill |
| MAE, MFE | Computed from price history during hold | At exit |
| MFE capture ratio | Computed: pnl / mfe | At exit |
| Hold duration | Computed: exit_time - entry_time | At exit |
| Deviation count | Computed: count(fills NOT IN plan) | At exit |
| Stop violation | Computed: did exit breach stop? | At exit |
| Regime | From te-market-context | At entry and exit |
| Thesis outcome | Computed from price vs thesis levels | At exit |
| Rule tracking | From gate audit log | At entry |
