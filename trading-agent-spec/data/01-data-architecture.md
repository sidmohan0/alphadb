# Data Architecture

## Single Source of Truth

All feedback loops query a single source of truth for trade data. The canonical trade record is the atomic unit. Everything else is derived.

## Storage Layout

```
data/
  trades.db              ← SQLite: canonical trade records, derived analytics
  audit.log              ← Append-only: every gate decision (pass + fail)
  events.log             ← Append-only: agent observations and decisions
  proposals/
    pending/             ← Awaiting human approval
    applied/             ← Applied proposals (audit trail)
    rejected/            ← Rejected proposals (audit trail)
  portfolio/
    snapshots/           ← Daily portfolio state (positions, Greeks, account value)
    equity-curve.csv     ← Daily mark-to-market
  performance/
    by-strategy.csv      ← Aggregated metrics per strategy
    by-rule.csv          ← Aggregated metrics per rule (key Loop 2 input)
    by-regime.csv        ← Performance segmented by market regime
    meta-metrics.csv     ← Loop 3 inputs (learning velocity, rule validation rate)
  regime/
    classifications.csv  ← Daily regime classification with evidence
  rules/
    rule-events.log      ← Timestamped log of every rule fire
    counterfactuals.log  ← For blocked trades: what would have happened
```

## SQLite Schema (trades.db)

```sql
-- Canonical trade records (source of truth)
CREATE TABLE trades (
    slug TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,
    instrument TEXT NOT NULL,
    side TEXT NOT NULL,
    
    entry_time TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_planned_price REAL NOT NULL,
    entry_slippage REAL NOT NULL,
    
    exit_time TEXT,
    exit_price REAL,
    exit_planned_price REAL,
    exit_reason TEXT,       -- stop_hit|target_hit|time_stop|invalidation|deviation
    exit_deviation_justified BOOLEAN,
    
    quantity REAL NOT NULL,
    pnl_gross REAL,
    pnl_net REAL,           -- after commissions
    commissions REAL,
    
    max_adverse_excursion REAL,
    max_favorable_excursion REAL,
    mfe_capture_ratio REAL,
    
    hold_duration_minutes INTEGER,
    planned_hold_minutes INTEGER,
    
    stop_price REAL NOT NULL,
    stop_moved_count INTEGER DEFAULT 0,
    stop_moved_direction TEXT,  -- tightened|loosened|both
    
    regime_at_entry TEXT,
    regime_at_exit TEXT,
    
    thesis_ref TEXT,
    plan_ref TEXT,
    
    deviation_count INTEGER DEFAULT 0,
    unplanned_scale_count INTEGER DEFAULT 0,
    
    status TEXT DEFAULT 'open',  -- open|closed|archived
    created_at TEXT NOT NULL,
    closed_at TEXT
);

-- Rule fire events (which rules were active, which fired)
CREATE TABLE trade_rule_events (
    id INTEGER PRIMARY KEY,
    trade_slug TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    fired BOOLEAN NOT NULL,
    check_value REAL,
    check_limit REAL,
    FOREIGN KEY (trade_slug) REFERENCES trades(slug)
);

-- Blocked entries (counterfactual tracking)
CREATE TABLE blocked_entries (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    strategy TEXT NOT NULL,
    instrument TEXT NOT NULL,
    side TEXT NOT NULL,
    planned_entry REAL NOT NULL,
    planned_stop REAL NOT NULL,
    planned_size REAL NOT NULL,
    blocking_rule TEXT NOT NULL,
    blocking_reason TEXT NOT NULL,
    
    -- Filled in later by counterfactual analysis
    counterfactual_exit_price REAL,
    counterfactual_pnl REAL,
    counterfactual_computed_at TEXT
);

-- Rule efficacy (materialized by Loop 2)
CREATE TABLE rule_efficacy (
    id INTEGER PRIMARY KEY,
    rule_id TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    regime TEXT,
    
    pre_rule_expectancy REAL,
    pre_rule_sample INTEGER,
    post_rule_expectancy REAL,
    post_rule_sample INTEGER,
    
    false_positive_rate REAL,
    false_positive_sample INTEGER,
    
    net_impact REAL,
    status TEXT,  -- VALIDATED|INCONCLUSIVE|DEGRADING|HARMFUL
    
    UNIQUE(rule_id, computed_at, regime)
);

-- Strategy performance (materialized periodically)
CREATE TABLE strategy_performance (
    id INTEGER PRIMARY KEY,
    strategy TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    regime TEXT,
    
    trade_count INTEGER,
    win_rate REAL,
    avg_winner REAL,
    avg_loser REAL,
    expectancy REAL,
    sharpe REAL,
    max_drawdown REAL,
    
    UNIQUE(strategy, period_start, period_end, regime)
);
```

## Ownership Model

| Data | Written By | Read By |
|------|-----------|---------|
| trades.db (fills) | Gate process | Agent (read-only) |
| audit.log | Gate process | Agent (read-only) |
| events.log | Agent process | Dashboard |
| proposals/ | Agent process | Gate process, Human |
| rule-events.log | Gate process | Agent (Loop 2) |
| counterfactuals.log | Agent (Loop 2) | Agent (Loop 2, Loop 3) |
| performance/ | Agent (Loop 2) | Agent (Loop 3), Dashboard |
| equity-curve.csv | Agent (te-journal) | Dashboard |

## Derived Data Refresh

A `te-sync` infrastructure task keeps derived data current:

- **After every trade close**: Update trades.db computed fields, strategy_performance for current period
- **Hourly**: Compute counterfactuals for recent blocked entries
- **Daily**: Full rule_efficacy recomputation, regime classification
- **Weekly**: Meta-metrics aggregation for Loop 3
