# Loop 2: Strategy Evolution

## Trigger

Runs every N trades (configurable per strategy) or on a daily schedule. With high-frequency crypto trading, this typically runs nightly.

## te-evolve Skill — Three Phases

### Phase 1: Rule Efficacy Audit

For every active rule, compute whether it's actually working:

```
For each rule with status: active AND qualifying_trades >= review_cadence:

  1. Pull all trades affected by this rule
  2. Split into:
     - pre_rule:  trades before rule creation date
     - post_rule: trades after rule creation that triggered the rule
     - counterfactual: trades prevented by rule (blocked entries)
  
  3. Compute:
     - pre_rule expectancy vs post_rule expectancy
     - estimated savings from counterfactual (prevented losses)
     - false_positive_rate: how many prevented trades would have 
       actually been winners?
  
  4. Score the rule:
     - VALIDATED:    post_rule expectancy improved AND 
                     false_positive_rate < threshold
     - INCONCLUSIVE: insufficient sample OR mixed signal
     - DEGRADING:    rule is blocking more winners than losers
     - HARMFUL:      post_rule expectancy worse than pre_rule
```

**Computing counterfactuals**: For most deterministic rules (time windows, price levels, indicator thresholds), the system can look at what the price did after a blocked entry and compute hypothetical P&L. The rule produces data even when it fires negatively.

### Phase 2: Threshold Optimization

For rules with continuous thresholds (risk limits, sizing parameters, time windows):

```
For each threshold in config:

  1. Segment trade history by the threshold variable
  2. Compute expectancy curves across segments
  3. Identify optimal range vs current threshold
  4. If optimal differs significantly from current:
     - Generate PROPOSAL (not auto-applied)
     - Include confidence interval and sample size
     - Flag whether shift tightens or loosens risk
     
  Output: data/proposals/pending/<date>-threshold-adjustment.md
```

**Asymmetric approval**: Tightening proposals can auto-apply. Loosening proposals require human approval and a higher evidence bar (lower p-value, larger sample).

### Phase 3: Capital Reallocation

```python
strategy_sharpes = {
    s.name: compute_rolling_sharpe(s, window=100)
    for s in get_all_strategies()
}

proposed_allocation = optimize_allocation(strategy_sharpes)
if proposed_allocation != current_allocation:
    create_proposal(
        type='REALLOCATION',
        from_allocation=current_allocation,
        to_allocation=proposed_allocation,
        evidence=strategy_sharpes,
        requires_human_approval=(max_change > 0.10)  
    )
```

Strategies that work get more capital. Strategies that don't get starved. Small rebalances auto-approve; large shifts require human confirmation. This is natural selection applied to trading strategies in real-time.

## Counterfactual Analysis

The system tracks every blocked entry:

```python
blocked_trades = feedback_store.get_blocked(strategy=strategy.name)

for blocked in blocked_trades:
    actual_outcome = compute_hypothetical_pnl(blocked)
    blocked.counterfactual_pnl = actual_outcome

block_quality = compute_block_quality(blocked_trades)
if block_quality.false_positive_rate > 0.5:
    # Blocking more winners than losers
    create_proposal(
        type='LOOSEN_RULE',
        rule=block_quality.worst_rule,
        evidence=block_quality,
        requires_human_approval=True  # loosening always needs human
    )
```

## Regime-Conditional Evaluation

Rules are evaluated per-regime:

```
Rule: sell-premium-high-vix
  trending_bull:              expectancy +$420, n=15, VALIDATED
  ranging:                    expectancy +$280, n=22, VALIDATED  
  volatile_mean_reverting:    expectancy +$650, n=8,  VALIDATED
  volatile_crisis:            expectancy -$1800, n=4, DEGRADING
```

A rule that works in one regime but fails in another gets regime-restricted, not globally retired:

```yaml
status: validated
regime_restriction: 
  excluded: [volatile_crisis]
  reason: "Tail risk in crisis overwhelms premium"
  recheck_after: 10_more_qualifying_trades_in_excluded_regime
```
