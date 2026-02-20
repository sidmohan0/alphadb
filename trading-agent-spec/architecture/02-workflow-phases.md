# Workflow Phases

## Canonical Trade Lifecycle

```
te-thesis ──► [te-research] ──► [te-spike] ──► te-plan
                                                  │
     ┌────────────────────────────────────────────┘
     ▼
te-risk-size ──► te-execute ──► te-manage ──► te-exit
                                                │
     ┌──────────────────────────────────────────┘
     ▼
te-review ──► te-learn ──► [te-journal / te-triage]
```

Brackets denote optional phases. `te-workflow` orchestrates the full sequence.

## Key Difference From Software Lifecycle

In Harness Engineering, "implement" is a single phase. In trading, execution splits into three distinct skills (execute, manage, exit) because each has fundamentally different decision physics:

- **Execute**: Entry psychology — can I commit capital?
- **Manage**: Monitoring psychology — should I adjust?
- **Exit**: Exit psychology — can I let go?

In software you can undo a bad commit. You can't undo a filled order at a bad price.

## Phase Contracts

| From → To | Contract |
|-----------|----------|
| thesis → plan | Thesis exists, passes lint, has invalidation condition |
| plan → risk-size | Plan has concrete instruments, levels, sizing, stop |
| risk-size → execute | All deterministic risk checks PASS |
| execute → manage | Entry fills logged, stop order verified on exchange |
| manage → exit | Exit criteria triggered (plan-based or deviation with justification) |
| exit → review | Exit fills logged, P&L computed from fills |
| review → learn | Multi-dimensional review complete, findings prioritized |
| learn → archive | Critical/high findings have produced guardrails (file diff exists) |

## Plan Modes

| Mode | Description | Gates |
|------|-------------|-------|
| `scalp` | Intraday, <1hr hold, small size | Thesis + hard stop only, skip formal research |
| `swing` | 1-5 day hold, standard sizing | Full gates |
| `position` | 1-4 week, larger thesis | Full gates + correlation review + scenario analysis |
| `structural` | Multi-month, portfolio-level | Full gates + monthly review cadence |

## Autonomous Agent Mode

When running autonomously (crypto scalping), the phases compress dramatically:

- **te-thesis**: Auto-generated from strategy signals, structured YAML not prose
- **te-research**: Skipped for scalp mode (signal IS the research)
- **te-spike**: Skipped (live trading IS the spike — Loop 2 handles validation)
- **te-plan**: Auto-generated from strategy config + signal parameters
- **te-risk-size**: Fully deterministic, runs in milliseconds via gate process
- **te-execute**: Automatic order placement via gate
- **te-manage**: Continuous monitoring every candle
- **te-exit**: Automatic on signal, stop hit, or time stop
- **te-review**: Automatic per-trade computation (Loop 1)
- **te-learn**: Automatic pattern detection and rule proposal
