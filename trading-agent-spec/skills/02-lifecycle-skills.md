# Lifecycle Skills

## te-thesis — Trade Thesis Intake

**Purpose**: Convert a market observation or signal into a structured, falsifiable thesis.

**Workflow**:
- Phase 0: Load market context, current regime, active strategies
- Phase 1: Structured intake — direction, catalyst, time horizon, conviction
- Phase 2: Define invalidation conditions (structured YAML, not prose)
- Phase 3: Validate and generate thesis artifact

**Output**: `journal/theses/<slug>-thesis.md`

**Key Constraint**: Every thesis must define at least one concrete invalidation condition containing a falsifiable numeric value (price level, indicator value, or date). The `te-thesis-lint` script verifies this structurally.

**Autonomous mode**: Auto-generated from strategy signals as structured YAML. The thesis is the signal + its parameters + auto-computed invalidation levels from strategy config.

---

## te-research — Market Research

**Purpose**: Parallel investigation across market dimensions to build evidence for or against a thesis.

**Workflow**:
- Phase 0: Gather questions from thesis
- Phase 1: Fan out parallel research across 6 dimensions:
  1. **Macro context** — rate environment, geopolitical backdrop, calendar (FOMC, OpEx, earnings)
  2. **Technical levels** — key support/resistance, moving averages, volume profile
  3. **Flow/positioning** — options open interest, put/call ratios, dark pool prints, GEX
  4. **Fundamental** — earnings, valuation, sector rotation
  5. **Sentiment** — VIX term structure, skew, AAII, CNN Fear & Greed
  6. **Correlation** — how does this asset move with related instruments
- Phase 2: Update thesis with evidence-backed findings (confidence levels)

**Output**: Updated thesis with research findings embedded, or separate `journal/research/<slug>-research.md`

**Deterministic gate**: If any dimension returns `confidence: low` and thesis `conviction` is `high`, flag the mismatch. Calendar check: if known event within time horizon, `event_risk_acknowledged` must be `true`.

**Autonomous mode**: Typically skipped for scalp mode. Signal IS the research.

---

## te-spike — Paper Trade / Backtest

**Purpose**: De-risk a thesis via time-boxed backtesting or paper trading before committing real capital.

**Workflow**:
- Phase 0: Load thesis context
- Phase 1: Execute investigation (backtest across historical scenarios, paper trade for a session, Monte Carlo simulation on P&L distribution)
- Phase 2: Write findings
- Phase 3: Update upstream thesis with results

**Output**: `journal/spikes/<slug>-spike.md`

**Key Constraint**: Time-boxed (1 trading session or 1 backtest session). Throwaway analysis. Must update thesis with what was learned.

**Autonomous mode**: Skipped — live trading with small size IS the spike. Loop 2 handles validation.

---

## te-plan — Trade Plan

**Purpose**: Create a concrete execution plan — the PLANS.md-compliant execution contract.

**PLANS.md compliance requirements** (adapted from Harness):
- **Self-contained**: Another trader can execute without asking questions
- **Concrete**: Exact instruments, strikes, expirations, limit prices — not "buy some puts"
- **Living**: Updated as the trade develops
- **Has proof commands**: "Verify by checking current bid/ask on the specific contract"

**Output**: `journal/plans/active/<slug>-plan.md`

**Required frontmatter**:
```yaml
slug: <slug>
status: active
conviction: high|medium|speculative
plan_mode: scalp|swing|position|structural
max_risk: <hard dollar amount>
risk_reward_target: <ratio>
strategy: <strategy name>
```

**Required sections**: Thesis Summary, Instrument Selection, Entry Criteria, Position Sizing, Stop Loss, Profit Targets, Max Loss, Time Stop, Scenario Analysis, Correlation Risk, Decision Log, Progress.

**Autonomous mode**: Auto-generated from strategy config + signal parameters. The plan is structured data, not a prose document.

---

## te-risk-size — Position Sizing Gate

**Purpose**: Fully deterministic pre-execution validation. The mechanical enforcer.

**This skill is almost entirely Tier 1 (fully computable)**:

```
Deterministic checks:
  □ max_single_trade_risk: (entry - stop) × quantity ≤ X% of account
  □ max_portfolio_risk: sum of all position risks ≤ Y% of account  
  □ max_correlated_exposure: net delta in same sector/theme ≤ Z
  □ max_single_name_concentration: notional in one underlying ≤ W% of account
  □ liquidity_check: avg daily volume on contract > 10× position size
  □ spread_check: bid-ask spread < threshold % of contract price
  □ margin_check: sufficient margin after this trade
  □ event_overlap: if major event within expiration, event_risk_acknowledged = true
  □ daily_loss_halt: daily P&L > -max_daily_loss
  □ weekly_loss_halt: weekly P&L > -max_weekly_loss
  □ drawdown_halt: drawdown from peak < max_drawdown
  □ time_window: current time not in restricted window
```

**Default safe action**: NO-TRADE when uncertain. Any check failure = rejection.

**Enforcement**: Runs inside the gate process, not the agent. The agent cannot bypass these checks.

---

## te-execute — Order Execution

**Purpose**: Place orders and log fills with evidence.

**Workflow**:
- Phase 1: Verify entry criteria are met (price at level, catalyst occurred)
- Phase 2: Submit order to gate process via IPC
- Phase 3: Gate validates and places with Coinbase
- Phase 4: Log fills with timestamps, prices, commissions
- Phase 5: Verify stop order is placed on exchange (not mental)
- Phase 6: Update plan Progress section

**Deterministic gates**:
- `te-risk-size` returned PASS
- Entry price within tolerance of planned price
- Stop order confirmed on exchange
- Time-of-day and day-of-week restrictions respected

---

## te-manage — Position Management

**Purpose**: Continuous monitoring and adjustment of open positions. Runs every candle.

**This skill runs continuously, unlike all others which are event-triggered.**

**Deterministic checks per candle**:
- Stop loss order still active on exchange
- Current P&L vs plan's max_loss (alert threshold)
- Time stop: `current_date > thesis.time_stop` → trigger exit
- Thesis invalidation: price crossed invalidation level → flag THESIS_INVALIDATED
- Greeks drift: if exposure shifted beyond tolerance → flag for rebalancing

**Adjustment operations** (via gate process):
- Tighten stop (always allowed)
- Scale out partial position (if in plan)
- Add to position (requires full risk-size re-check)

---

## te-exit — Exit Execution

**Purpose**: Execute exits and log deviation tracking.

**Workflow**:
- Phase 1: Identify exit trigger (stop_hit, target_hit, time_stop, invalidation_triggered, plan_scale_out, or deviation)
- Phase 2: Submit exit order to gate process
- Phase 3: Log exit fills, compute P&L from fills (never self-reported)
- Phase 4: If `exit_reason: deviation`, require `deviation_justification`
- Phase 5: Compute actual vs planned metrics (slippage, capture ratio, hold duration)

**Deterministic checks**:
- `exit_reason` must be from valid enum
- P&L always computed: `(exit_price - entry_price) × quantity - commissions`
- If `exit_reason: stop_hit`, verify actual exit price within tolerance of planned stop
- Detect stop violations: `stop was set at X, actual exit at Y where |X-Y| > tolerance`
