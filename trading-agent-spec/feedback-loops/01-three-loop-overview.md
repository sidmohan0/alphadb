# Three-Loop Recursive Self-Improvement Model

## The Problem With Single-Loop Learning

Most trading journals work like: Trade → Outcome → Human Reflection → New Rule → Applied Next Trade

This breaks in three ways:

1. **Rule bloat.** After 200 trades you have 60 rules, many contradictory. Nobody prunes because every rule was born from pain.

2. **Survivorship bias in rules.** You create a rule after a loss but never measure whether it actually improved outcomes. Rules persist on emotional weight, not evidence.

3. **Static thresholds.** Risk limits set when you were learning never evolve as skill and account size change. No mechanism to propose adjustments.

## Three Nested Loops

```
┌─────────────────────────────────────────────────────────────┐
│  LOOP 3: META-LEARNING (weekly for agent, quarterly human)  │
│  "Is my process of improving actually improving?"           │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  LOOP 2: STRATEGY EVOLUTION (daily for agent)         │  │
│  │  "Are my rules and thresholds still working?"         │  │
│  │                                                       │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │  LOOP 1: TRADE LEARNING (per-trade)             │  │  │
│  │  │  "What happened and what's the guardrail?"      │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Timescale Comparison

```
Human trader feedback cycle:
  Trade (days) → Learn (weekly) → Evolve (monthly) → Meta (quarterly)
  Time to meaningful self-improvement: ~6 months

Autonomous agent feedback cycle:
  Trade (minutes) → Learn (hourly) → Evolve (daily) → Meta (weekly)
  Time to meaningful self-improvement: ~2 weeks
```

The compressed crypto timeframe (50-200 trades/day) means the agent generates in one week more data than a human swing trader gets in a year. This is what makes genuine recursive improvement possible rather than aspirational.

## The Recursive Flywheel

```
TRADE HAPPENS
     │
     ▼
Loop 1 (te-learn): 
  "Lost money. Stop was moved twice in losing direction."
  → Creates rule: max-stop-adjustments-per-trade (limit: 1)
  → Rule has hypothesis, baseline, review cadence
     │
     ▼
20 MORE TRADES HAPPEN (rule is active, collecting data)
     │
     ▼
Loop 2 (te-evolve):
  "Rule has 20 qualifying trades. Let's evaluate."
  → Result: rule validated. Win rate with 0-1 stop moves: 58%. 
    With 2+ moves: 31%.
  → false_positive_rate: 0.15 (acceptable)
  → Rule promoted to status: validated
     │
     ▼
Loop 2 also finds:
  "Risk threshold of 2% was set at inception. Current data 
   suggests 1.5% improves Sharpe by 0.3."
  → Generates proposal: tighten single-trade risk to 1.5%
  → Tightening = auto-approved by gate
     │
     ▼
NEXT WEEK
     │
     ▼
Loop 3 (te-meta-review):
  "Rule validation rate: 45% (up from 30%)"
  "Threshold proposals: 2 applied, both improved Sharpe"
  "Meta-insight: Rule quality improved when thesis invalidation 
   conditions became more specific. The upstream fix (better theses) 
   reduced downstream rule churn."
  → This feeds back into te-thesis-lint requirements
     │
     ▼
THE SYSTEM ITSELF EVOLVES
```

The meta-insight in the last step is the recursive moment. The system learned a lesson about *how it learns*, not just a trading lesson. That insight feeds back into tightening upstream requirements, which improves all future trade quality.
