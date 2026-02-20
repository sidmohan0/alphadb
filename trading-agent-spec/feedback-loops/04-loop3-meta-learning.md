# Loop 3: Meta-Learning

## Trigger

Runs weekly for the autonomous agent (quarterly for human traders). Evaluates whether the process of generating rules and evolving thresholds is actually making the system better.

## te-meta-review Skill

### Quantitative Inputs

```python
context = {
    'rule_creation_rate': compute_rule_creation_rate(),
    'rule_validation_rate': compute_rule_validation_rate(),
    'rule_retirement_rate': compute_rule_retirement_rate(),
    'parameter_proposal_accuracy': compute_proposal_accuracy(),
    'sharpe_trajectory': get_sharpe_trajectory(),
    'regime_classification_accuracy': compute_regime_accuracy(),
    'strategy_performance_by_regime': get_performance_matrix(),
    'capital_allocation_history': get_allocation_history(),
    'blocked_trade_quality': get_block_quality_trend(),
    'evolution_cycle_outcomes': get_evolution_outcomes(),
}
```

### Five Analysis Dimensions

**1. Rule Generation Quality**
- What % of rules created by Loop 1 eventually validate?
- What % get retired as harmful?
- Is the validation rate improving over time?
- If <30% of rules validate → Loop 1 is producing bad hypotheses, needs adjustment

**2. Threshold Evolution Quality**
- Did threshold adjustments from Loop 2 improve subsequent performance?
- Compare: expected improvement (from proposal) vs actual improvement (realized)
- If proposals consistently over-promise → optimization methodology needs recalibration

**3. Regime Adaptability**
- Compute performance segmented by market regime
- Is the system degrading in specific regimes?
- Are rules created in one regime harmful in another?
- Feeds back to te-market-context to improve regime detection

**4. Learning Velocity**
- Time from "mistake made" to "guardrail active"
- Time from "rule proposed" to "rule validated/retired"
- Is the system getting faster at learning?
- Is the sample size needed for validation decreasing (better hypothesis quality)?

**5. Compounding Metric**
- Rolling Sharpe ratio annotated with every rule activation, threshold change, and rule retirement
- Is Sharpe trending up?
- Which rule changes had the biggest positive/negative impact?

### LLM Integration

Loop 3 is the **only place** where an LLM reasons qualitatively. Loops 1 and 2 are pure computation.

```python
meta_insights = llm.analyze(
    system_prompt=META_REVIEW_PROMPT,
    data=context,
    questions=[
        "Which strategies are improving vs degrading and why?",
        "Are evolution cycles improving parameters or adding noise?",
        "What regime shifts happened and did the system adapt?",
        "What structural changes would improve learning velocity?",
        "Should parameter bounds be widened or tightened?",
    ]
)
```

The LLM operates in an **advisory capacity** on structural questions. Core decision-making in Loops 1 and 2 remains deterministic and auditable.

### Proposal Types

```python
for insight in meta_insights.proposals:
    if insight.type == 'NEW_STRATEGY':
        # Agent noticed a pattern suggesting a new strategy
        create_strategy_proposal(insight)  # always human approved
    
    elif insight.type == 'SYSTEM_CHANGE':
        # Changes to Loop 1 or Loop 2 behavior
        notify_human(insight)  # always human approved
    
    elif insight.type == 'PARAMETER_BOUNDS_CHANGE':
        # Change the search space Loop 2 can optimize within
        notify_human(insight)  # always human approved
```

### Output

`docs/meta-reviews/<date>-meta-review.md` — feeds back into the design of the loops themselves.

### The Recursive Moment

If Loop 3 discovers that improving thesis quality upstream reduced rule churn downstream, that insight feeds back into tightening `te-thesis-lint` requirements. The system didn't just learn a trading lesson — it learned a lesson about how it learns. That insight improves all future trade quality, which improves all future rule quality. This is genuine recursion.
