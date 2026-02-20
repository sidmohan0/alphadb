# Rule Lifecycle

## States

```
proposed → active → validated → graduated → retired
                  → inconclusive (extend review period)
                  → degrading → suspended → retired/revised
```

### State Definitions

- **Proposed**: Born from Loop 1 (te-learn) or Loop 2 (te-evolve). Hypothesis defined. Not yet applied to live trading.
- **Active**: Applied to live trading. Collecting data for evaluation.
- **Validated**: Enough data shows it works (improvement statistically significant, false positive rate acceptable).
- **Graduated**: Validated across multiple market regimes. Promoted to `config/rules/core/` as a core rule.
- **Inconclusive**: Insufficient sample or mixed signal. Review period extended.
- **Degrading**: Rule is blocking more winners than losers.
- **Suspended**: Temporarily disabled pending investigation.
- **Retired**: Proved ineffective or harmful. Archived with full evidence.

## Rule Creation (Loop 1)

Every rule created by te-learn includes a testable hypothesis:

```yaml
# config/rules/active/no-friday-afternoon-entries.yaml
---
id: no-friday-afternoon-entries
status: active
created: 2026-02-18
created_from: 2026-02-14-bearish-qqq-opex-pin

conditions:
  - field: time.day_of_week
    operator: eq
    value: 4  # Friday
  - field: time.hour_utc
    operator: gte
    value: 19  # 2pm EST

action: reject
message: "Friday afternoon entry blocked (rule: no-friday-afternoon-entries)"

hypothesis:
  description: "Friday afternoon entries have negative expectancy due to gamma compression and weekend risk"
  test_metric: win_rate
  test_population: "day_of_week=friday AND hour>=14"
  baseline_at_creation:
    sample_size: 12
    win_rate: 0.25
    avg_pnl: -340
  review_cadence: after_20_qualifying_trades
---
```

## Rule Evaluation (Loop 2)

After `review_cadence` qualifying trades:

```
1. Pull all trades matching test_population
2. Split: pre-rule vs post-rule
3. Compute: improvement in test_metric
4. Compute: counterfactual (blocked trades — would they have won?)
5. Score: VALIDATED / INCONCLUSIVE / DEGRADING / HARMFUL
```

## Rule Graduation

A rule graduates to core when:
- Validated across 2+ distinct market regimes
- Minimum total sample size threshold met
- Confidence counter exceeds graduation threshold
- No period of DEGRADING status in any regime

Graduated rules move to `config/rules/core/` which is human-editable only.

## Rule Retirement

Retirement produces a learning artifact:

```yaml
# docs/retired-rules/no-friday-afternoon-entries.yaml
---
status: retired
retired_date: 2026-08-15
retirement_reason: validated_harmful
evidence:
  sample_size: 34
  pre_rule_expectancy: -340
  post_rule_expectancy: -120  # improved BUT
  false_positive_rate: 0.62   # blocked 62% winners
  net_impact: -4200           # missed gains exceed prevented losses
lesson: "The real issue wasn't Friday timing — it was FOMO entries 
         regardless of day. Replaced with conviction-gate rule."
replaced_by: config/rules/active/no-speculative-without-research.yaml
---
```

This prevents oscillation — the system won't re-create the same rule later because the retirement artifact explains why it was wrong and what replaced it.

## The Regime Problem

Rules that work in one regime fail in another. Rather than global retirement, rules get regime restrictions:

```yaml
status: validated
regime_restriction:
  excluded: [volatile_crisis]
  reason: "Tail risk in crisis regimes overwhelms benefit"
  evidence_date: 2026-03-15
  sample_size_at_exclusion: 4
  recheck_after: 10_more_qualifying_trades_in_excluded_regime
```

If Loop 3 finds that rules keep failing in regimes where they should succeed, the problem might be regime detection, not the rule. This triggers improvements to te-market-context.

## After Six Months

A mature system might have:
- 40 rules created by Loop 1
- 25 validated, 8 retired (with evidence), 7 still collecting data
- 3 threshold adjustments proposed and applied by Loop 2
- 2 meta-insights from Loop 3 that changed upstream skill behavior
- A rolling Sharpe annotated with exactly which system changes drove improvement
- An evidence-backed edge inventory with confidence intervals

The system knows what it's good at and what it's tried and abandoned, with quantitative evidence for both.
