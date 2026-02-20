# Deterministic Gates

## The Three Tiers of Determinism

### Tier 1 — Fully Deterministic

A script can compute the answer from market data, fill records, and portfolio state. No human judgment needed. These are CI lint equivalents.

**Examples**:
- `max_single_trade_risk`: `(entry - stop) × quantity ≤ X% of account`
- `daily_loss_halt`: `daily_pnl > -max_daily_loss`
- `P&L computation`: `(exit_price - entry_price) × quantity - commissions`
- `stop_violation_detection`: `|actual_exit - planned_stop| > tolerance`
- `time_window_restriction`: `current_hour NOT IN restricted_hours`
- `deviation_count`: `count(fills NOT IN plan)`

### Tier 2 — Structured-Deterministic

The check itself is deterministic, but it operates on human-authored input. Like Harness's `he-specs-lint.sh` which verifies a spec has required sections (deterministic) even though the content required judgment.

**Examples**:
- Thesis has all required frontmatter fields
- `invalidation_condition` contains at least one concrete number (regex-checkable)
- `time_stop` field is populated
- If `conviction: speculative`, then `max_risk ≤ half default limit`

### Tier 3 — Judgment-Required

Genuinely requires human/LLM reflection. Minimized and clearly labeled. Where possible, extract deterministic sub-checks.

**Examples**:
- Was the thesis "good"? (But we extract: was it structurally complete? Was direction correct? Did catalyst occur? — all computable)
- Should this rule be retired? (But we extract: is false_positive_rate > threshold? Is expectancy worse? — all computable)

## Gate Coverage by Skill

### te-thesis gates
| Check | Tier | Method |
|-------|------|--------|
| Required frontmatter present | 2 | YAML parse |
| Invalidation condition has numeric value | 2 | Regex |
| Time stop populated | 2 | Field check |
| Speculative conviction → reduced max_risk | 2 | Value comparison |
| Event catalyst → catalyst_date present | 2 | Conditional field check |

### te-research gates
| Check | Tier | Method |
|-------|------|--------|
| Each dimension has confidence level | 2 | Field check |
| Low-confidence + high-conviction mismatch | 1 | Value comparison |
| Calendar event within time horizon | 1 | Date comparison against calendar data |

### te-risk-size gates (almost entirely Tier 1)
| Check | Tier | Method |
|-------|------|--------|
| Single trade risk ≤ limit | 1 | Arithmetic |
| Portfolio aggregate risk ≤ limit | 1 | Arithmetic |
| Correlated exposure ≤ limit | 1 | Correlation computation |
| Single name concentration ≤ limit | 1 | Arithmetic |
| Liquidity check | 1 | Volume comparison |
| Spread check | 1 | Spread computation |
| Margin check | 1 | Arithmetic |
| Daily loss halt | 1 | Arithmetic |
| Weekly loss halt | 1 | Arithmetic |
| Drawdown halt | 1 | Arithmetic |
| Time window restriction | 1 | Timestamp comparison |
| Event overlap acknowledged | 1 | Boolean field + date check |

### te-execute gates
| Check | Tier | Method |
|-------|------|--------|
| te-risk-size returned PASS | 1 | Boolean |
| Entry price within tolerance | 1 | Arithmetic |
| Stop order confirmed on exchange | 1 | API verification |
| Time/day restrictions | 1 | Timestamp comparison |

### te-exit gates
| Check | Tier | Method |
|-------|------|--------|
| exit_reason from valid enum | 1 | Enum check |
| P&L computed from fills | 1 | Arithmetic |
| Stop violation detection | 1 | `|actual_exit - planned_stop|` |
| Deviation requires justification field | 2 | Field check |

### te-review gates (behavioral proxies)
| Check | Tier | Method |
|-------|------|--------|
| Deviation count | 1 | Count(fills NOT IN plan) |
| Stop moved count + direction | 1 | Order history analysis |
| Unplanned scale count | 1 | Count(adjustments NOT IN plan) |
| Hold duration vs plan | 1 | Timestamp arithmetic |
| MFE capture ratio | 1 | max_favorable_excursion / pnl |
| Regime classification match | 1 | Enum comparison |

### te-learn gates
| Check | Tier | Method |
|-------|------|--------|
| Critical/high findings → file diff exists | 1 | Git diff check |
| Stop violation → stop discipline runbook exists | 1 | File existence check |
| 3+ consecutive losses → strategy review triggered | 1 | Sequence detection |
| Performance stats computed from fills | 1 | Arithmetic |

## Summary

**13 of 15 invariants are Tier 1 (fully computable)**. The remaining 2 are Tier 2 (structural lints that verify presence of human-authored content, not quality). Zero invariants require honest self-assessment.
