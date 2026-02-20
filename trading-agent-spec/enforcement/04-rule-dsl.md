# Rule DSL

## Purpose

Active rules need to be evaluated dynamically — Loop 2 creates and modifies rules at runtime. The gate needs to load and execute rules without recompilation. Rules are expressed in a constrained DSL that the gate can interpret safely.

## Format

```yaml
# config/rules/active/no-entries-high-funding.yaml
---
id: no-entries-high-funding
status: active
strategy: mean-reversion-funding  
created: 2026-02-20T14:30:00Z
created_from: trade-slug-xyz

conditions:
  - field: market.funding_rate_zscore
    operator: gt
    value: 3.5
  - field: order.side
    operator: eq
    value: long

action: reject
message: "Funding z-score {market.funding_rate_zscore} exceeds limit 3.5"

hypothesis:
  metric: win_rate
  population: "strategy=mean-reversion-funding AND funding_zscore > 3.5 AND side=long"
  baseline_value: 0.22
  baseline_sample: 18
  review_after_n: 30
---
```

## Operators

| Operator | Meaning |
|----------|---------|
| `eq` | Equal |
| `neq` | Not equal |
| `gt` | Greater than |
| `gte` | Greater than or equal |
| `lt` | Less than |
| `lte` | Less than or equal |

## Available Fields (Whitelist)

The field resolver is a strict whitelist. Rules can only reference fields the gate explicitly exposes:

```rust
fn resolve_field(field: &str, order: &SubmitOrder, state: &GateState) -> Decimal {
    match field {
        // Market data
        "market.price"                  => state.market.price(&order.symbol),
        "market.funding_rate_zscore"    => state.market.funding_rate_zscore(&order.symbol),
        "market.volume_ratio"           => state.market.volume_ratio(&order.symbol),
        "market.volatility"             => state.market.realized_vol(&order.symbol),
        "market.regime"                 => state.market.regime_id(),
        "market.spread_pct"             => state.market.spread_pct(&order.symbol),
        
        // Order fields
        "order.side"                    => order.side.as_decimal(),
        "order.size"                    => order.size,
        "order.notional"               => order.size * order.effective_price(state),
        "order.risk_pct"               => order.compute_risk_pct(state),
        
        // Portfolio state
        "portfolio.total_exposure_pct"  => state.portfolio.total_exposure_pct(),
        "portfolio.strategy_exposure"   => state.portfolio.strategy_exposure(&order.strategy),
        "portfolio.open_position_count" => state.portfolio.open_count(),
        "portfolio.daily_pnl"           => state.portfolio.daily_pnl(),
        "portfolio.weekly_pnl"          => state.portfolio.weekly_pnl(),
        
        // Time fields
        "time.hour_utc"                 => Decimal::from(Utc::now().hour()),
        "time.day_of_week"              => Decimal::from(Utc::now().weekday().num_days_from_monday()),
        "time.minutes_since_open"       => state.market.minutes_since_open(),
        
        // Unknown field = fail closed
        _ => panic!("Unknown field: {field}"),
    }
}
```

## Safety Properties

1. **Whitelist-only**: Rules can only reference exposed fields. No arbitrary memory access.
2. **Fail closed**: Unknown field → panic → order rejected. Never fail open.
3. **No side effects**: Rule evaluation is a pure function. Cannot call external services.
4. **No code execution**: The DSL is data, not code. No scripting, no eval.
5. **Bounded complexity**: Conditions are flat (AND-only). No nested logic, no OR, no loops.

## Actions

| Action | Meaning |
|--------|---------|
| `reject` | Block the order if all conditions match |
| `warn` | Log warning but allow (for data collection before activation) |
| `reduce_size` | Cap position size to a specified fraction (future extension) |

## Why Not Arbitrary Code?

The agent (via Loop 2) creates rules at runtime. If rules could contain arbitrary code, the agent could effectively inject any behavior into the gate. The constrained DSL ensures the agent can express "block orders when X > Y" but cannot express "ignore all safety checks" or "send my API key to an external server."

This is the trading equivalent of Harness's "runbooks are additive-only." The DSL is expressive enough for useful rules, constrained enough to be safe.
