# Safety Configuration

## safety.yaml — Human-Editable Only

This file exists outside the agent's ability to modify. The gate process reads it; the agent process cannot write to it.

```yaml
# config/safety.yaml

hard_limits:
  max_total_capital: 5000              # never risk more than this total
  max_single_position_pct: 0.05        # 5% of capital per position
  max_single_trade_risk_pct: 0.02      # 2% of capital at risk per trade
  max_total_exposure_pct: 0.50         # never more than 50% deployed
  max_daily_loss: 250                  # stop trading for the day
  max_weekly_loss: 500                 # stop trading for the week  
  max_drawdown_from_peak_pct: 0.15     # 15% drawdown = full stop
  
kill_switches:
  daily_loss_halt: true
  weekly_loss_halt: true
  drawdown_halt: true
  manual_halt: false                   # flip from dashboard for emergency stop
  
dead_man_switch:
  enabled: true
  timeout_minutes: 30                  # if gate loses agent contact
  action: liquidate_all                # or: close_new_only
  
agent_permissions:
  can_modify_safety_yaml: false        # NEVER
  can_modify_parameter_bounds: false   # requires human approval
  can_add_new_strategy: false          # requires human approval
  can_increase_capital_allocation: true # within hard limits only
  can_decrease_capital_allocation: true # always allowed
  can_tighten_risk: true               # always allowed
  can_loosen_risk: false               # requires human approval
  
notification_thresholds:
  notify_on_loss_pct: 0.02             # any 2%+ loss
  notify_on_rule_suspension: true      # always
  notify_on_evolution_applied: true    # always
  notify_on_new_proposal: true         # always
  notify_on_kill_switch: true          # always
```

## Permission Asymmetry

The core safety principle: **the agent can always protect itself but can never increase its own risk.**

| Action | Allowed? | Approval |
|--------|----------|----------|
| Tighten stop | ✅ | Auto |
| Cancel order | ✅ | Auto |
| Reduce position size | ✅ | Auto |
| Reduce capital allocation | ✅ | Auto |
| Tighten risk parameter | ✅ | Auto |
| Halt trading | ✅ | Auto |
| Loosen stop | ❌ | N/A (not in API) |
| Increase risk parameter | ❌ | Human approval |
| Loosen risk rule | ❌ | Human approval |
| Add new strategy | ❌ | Human approval |
| Modify safety.yaml | ❌ | N/A (not possible) |
| Modify parameter bounds | ❌ | Human approval |

## Strategy Configuration

```yaml
# config/strategies/mean-reversion-funding.yaml
name: mean-reversion-funding
status: active
capital_allocation: 0.20              # 20% of total agent capital
instruments: [BTC-PERP, ETH-PERP]
timeframe: 5m

parameters:
  funding_zscore_entry: 2.0           # Loop 2 optimizes this
  funding_zscore_exit: 0.5
  max_hold_candles: 60                # 5 hours at 5m candles
  stop_loss_pct: 0.015                # 1.5%
  take_profit_pct: 0.025              # 2.5%

parameter_bounds:                      # Loop 2 CANNOT optimize outside these
  funding_zscore_entry: [1.5, 3.5]
  funding_zscore_exit: [0.1, 1.0]
  max_hold_candles: [12, 120]
  stop_loss_pct: [0.005, 0.03]
  take_profit_pct: [0.01, 0.05]

created: 2026-02-18
version: 1
```

Parameter bounds are the search space for Loop 2. The bounds themselves can only be changed by Loop 3 with human approval. This prevents the optimization from finding degenerate solutions (e.g., setting stop loss to 30% because one backtest showed it worked).

## Trust Calibration Over Time

Start conservative, expand trust gradually as the system proves itself:

1. **Week 1-2**: Human approves everything. Agent proposes, you decide.
2. **Week 3-4**: Auto-approve tightening changes. Human approves loosening.
3. **Month 2**: Auto-approve parameter changes within bounds. Human approves bound changes.
4. **Month 3+**: Auto-approve small capital reallocations (< 10% shift). Human approves large shifts.
5. **Never**: Auto-approve risk loosening. Never auto-approve safety.yaml changes.
