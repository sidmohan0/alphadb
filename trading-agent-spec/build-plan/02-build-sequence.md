# Build Sequence

## 8-Week Plan

### Week 1-2: Data & Execution Foundation

**Goal**: The gate process can observe the market and place/cancel orders. No strategy yet — just infrastructure.

**Deliverables**:
- [ ] Gate process skeleton with config loading (safety.yaml, strategies/)
- [ ] Coinbase API client (REST + websocket)
  - [ ] Authentication
  - [ ] Market data ingestion (candles, orderbook depth)
  - [ ] Order placement (limit, market, stop)
  - [ ] Fill tracking and history
  - [ ] Account/portfolio state
- [ ] IPC socket server (gate side)
- [ ] IPC socket client (agent side)
- [ ] GateRequest / GateResponse message types
- [ ] Basic audit logging (append-only)
- [ ] Manual test: place and cancel an order via IPC

**Risk**: Coinbase API rate limits and websocket reliability. Build retry logic early.

---

### Week 3: Risk Engine & Feedback Store

**Goal**: The deterministic risk gates work. Trade records are stored and queryable.

**Deliverables**:
- [ ] Order validator in gate process
  - [ ] All safety.yaml checks (capital, exposure, daily/weekly loss, drawdown)
  - [ ] Stop loss presence verification
  - [ ] Single trade risk calculation
  - [ ] Slippage tolerance check
- [ ] SQLite schema for trades, blocked_entries, trade_rule_events
- [ ] Trade record creation from fills (all computed fields)
- [ ] Kill switches (daily loss halt, weekly loss halt, drawdown halt)
- [ ] Dead man's switch (optional timeout-based liquidation)
- [ ] Test: submit orders that should pass and fail each gate, verify correct behavior

**Risk**: Getting the arithmetic right for margin, notional, risk calculations across different instruments. Unit test heavily.

---

### Week 4: First Strategy + Loop 1

**Goal**: The agent trades live with tiny size. Loop 1 runs after every trade.

**Deliverables**:
- [ ] Strategy trait / interface definition
- [ ] First strategy implementation: funding rate mean reversion
  - [ ] Signal generation from funding rate z-scores
  - [ ] Entry/exit criteria
  - [ ] Strategy config (parameters + bounds)
- [ ] Core agent loop (observe → evaluate → generate → validate → execute → sleep)
- [ ] Loop 1: per-trade learning
  - [ ] MAE/MFE computation
  - [ ] Behavioral metric computation (deviation count, stop moves)
  - [ ] Anomaly detection on rolling window
  - [ ] Rule proposal generation (with hypothesis + baseline)
- [ ] Thesis auto-generation from signals (structured YAML)
- [ ] Plan auto-generation from strategy config

**Milestone**: Agent is trading live with $50-100 positions, generating trade records, Loop 1 is proposing rules.

**Risk**: Overoptimizing the strategy before the infrastructure is solid. Resist. The strategy should be simple — Loop 2 will optimize it.

---

### Week 5-6: Loop 2 — Strategy Evolution

**Goal**: With a week of trade data, Loop 2 evaluates rules and optimizes parameters.

**Deliverables**:
- [ ] Rule DSL interpreter in gate process
- [ ] Rule file management (active/ directory, YAML parsing)
- [ ] Rule proposal mediation (agent proposes → gate validates → applies or queues)
- [ ] te-evolve: Rule Efficacy Audit
  - [ ] Pre/post rule expectancy comparison
  - [ ] Counterfactual computation for blocked entries
  - [ ] False positive rate calculation
  - [ ] Rule scoring (VALIDATED / INCONCLUSIVE / DEGRADING / HARMFUL)
- [ ] te-evolve: Threshold Optimization
  - [ ] Expectancy curve computation across parameter ranges
  - [ ] Proposal generation with statistical evidence
  - [ ] Asymmetric approval (tightening auto, loosening human)
- [ ] te-evolve: Capital Reallocation proposals
- [ ] Rule lifecycle state transitions (proposed → active → validated → graduated)
- [ ] Regime classification (basic: trending/ranging/volatile)
- [ ] Regime-conditional rule evaluation

**Milestone**: Loop 2 has proposed and applied at least one parameter change or rule based on data. You can see whether its proposals make sense.

---

### Week 7-8: Loop 3 + Second Strategy

**Goal**: Meta-learning runs. Two strategies competing for capital.

**Deliverables**:
- [ ] Second strategy implementation: momentum on volume breakouts
  - [ ] Independent signal generation
  - [ ] Isolated capital allocation
- [ ] Loop 3: Meta-review
  - [ ] Quantitative context gathering (rule validation rate, Sharpe trajectory, etc.)
  - [ ] Claude API integration for qualitative analysis
  - [ ] Proposal generation for structural changes
- [ ] Dashboard v1
  - [ ] Live P&L by strategy
  - [ ] Active positions with stops
  - [ ] Active rules with status
  - [ ] Pending proposals (approve/reject)
  - [ ] Kill switch button
  - [ ] Equity curve chart
- [ ] Rule retirement with evidence archiving
- [ ] Strategy performance comparison and reallocation

**Milestone**: Two strategies running, Loop 3 has produced at least one meta-insight, dashboard shows the full system state.

---

## Ongoing: Trust Calibration

After the 8-week build, gradually expand the agent's autonomous authority:

| Week | Trust Level |
|------|-------------|
| 1-4 | Human approves everything |
| 5-8 | Auto-approve tightening. Human approves loosening. |
| 9-12 | Auto-approve parameter changes within bounds. |
| 13+ | Auto-approve small capital reallocations (< 10% shift). |
| Never | Auto-approve risk loosening or safety.yaml changes. |

## Definition of Done (v1.0)

- [ ] Two strategies running live with real (small) capital
- [ ] All 15 non-negotiable invariants enforced by gate process
- [ ] Loop 1 producing rule proposals after every trade
- [ ] Loop 2 evaluating rules and proposing parameter changes daily
- [ ] Loop 3 running weekly meta-review
- [ ] Dashboard showing live state, proposals, and kill switch
- [ ] At least one rule has been created, evaluated, and either validated or retired
- [ ] System has been running for 2+ weeks without manual intervention beyond proposal approval
- [ ] Equity curve is visible and annotated with system changes

## Starting Capital Recommendation

Start with $1,000-2,000 total. At 5% max per position and 2% max risk per trade, that's $50-100 positions with $20-40 at risk per trade. Enough to generate real data, small enough that the "tuition" of early mistakes is affordable.

Scale capital only after Loop 2 has run at least 3 evolution cycles and the system has demonstrated positive expectancy across multiple strategies.
