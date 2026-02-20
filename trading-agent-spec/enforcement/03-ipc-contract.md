# IPC Contract

## Surface Area

The gate process exposes a narrow, typed API. This is the ENTIRE surface area the agent has for interacting with money.

```rust
enum GateRequest {
    // === QUERY OPERATIONS (always allowed) ===
    GetPortfolio,
    GetOpenOrders,
    GetFillHistory { since: DateTime },
    GetMarketData { symbol: String },
    
    // === ORDER OPERATIONS (always validated) ===
    SubmitOrder {
        strategy: String,
        symbol: String,
        side: Side,
        size: Decimal,
        order_type: OrderType,       // limit, market, stop
        price: Option<Decimal>,
        stop_price: Option<Decimal>, // required for entries
        thesis_slug: String,         // must reference valid thesis
        planned_entry: Decimal,
        planned_stop: Decimal,
    },
    
    CancelOrder { order_id: String },
    
    // Asymmetric: can tighten, never loosen
    TightenStop { 
        order_id: String, 
        new_stop: Decimal,  // gate verifies this is actually tighter
    },
    
    // === RULE PROPOSALS (mediated by gate) ===
    ProposeRule(RuleProposal),
}

enum GateResponse {
    Accepted { order_id: String, checks_passed: Vec<CheckResult> },
    Rejected { checks_failed: Vec<CheckResult> },
    Portfolio(PortfolioState),
    Orders(Vec<Order>),
    Fills(Vec<Fill>),
    MarketData(MarketState),
    ProposalAcknowledged { proposal_id: String, auto_approved: bool },
}

struct CheckResult {
    check_name: String,      // "max_single_position"
    passed: bool,
    value: Decimal,          // actual computed value
    limit: Decimal,          // threshold from rules
    source: String,          // "safety.yaml" or "rules/no-friday.yaml"
}
```

## What's NOT in the API

There is no:
- `ModifySafetyConfig`
- `LoosenStop`
- `OverrideRiskCheck`
- `WriteToSafetyYaml`
- `WriteToRulesCore`

The agent physically cannot express these operations. It's not a matter of choosing to respect rules — the rules are the walls of the room it operates in.

## Asymmetric Operations

The agent can always make things safer:
- Tighten a stop
- Cancel an order
- Reduce position size

It can never make things riskier through this API:
- `TightenStop` where new stop is further from entry → **rejected**
- `SubmitOrder` that exceeds any limit → **rejected**

## Rule Proposals via IPC

```rust
enum RuleProposal {
    Activate { rule: Rule, evidence: Evidence },
    Suspend { rule_id: String, reason: String, evidence: Evidence },
    ModifyParameter { 
        rule_id: String, 
        parameter: String, 
        old_value: Decimal, 
        new_value: Decimal,
        evidence: Evidence,
        is_tightening: bool,  // gate verifies this claim
    },
}
```

Gate receives proposal → verifies claims → if tightening, auto-applies → if loosening, writes to `proposals/pending/` and notifies human → agent never touches rule files directly.

## Audit Trail

Every interaction logged to `data/audit.log`:

```
{
  "timestamp": "2026-02-20T14:42:00.123Z",
  "request_type": "SubmitOrder",
  "strategy": "mean-reversion-funding",
  "symbol": "ETH-USD",
  "side": "buy",
  "size": 0.5,
  "checks": [
    {"name": "max_single_position", "passed": true, "value": 0.024, "limit": 0.05},
    {"name": "daily_loss_halt", "passed": true, "value": -120, "limit": -250},
    {"name": "no-entries-high-funding", "passed": true, "value": 1.2, "limit": 3.5},
    ...
  ],
  "decision": "ACCEPTED",
  "order_id": "abc123"
}
```

Every order, accepted or rejected, gets the full check vector. This is what Loop 2 reads to compute rule efficacy.
