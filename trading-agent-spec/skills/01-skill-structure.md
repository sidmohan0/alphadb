# Skill Structure & Conventions

## Adapted From Harness Engineering

Every skill follows a standardized format adapted from Harness Engineering's skill pattern:

```
skills/<skill-name>/
  SKILL.md              ← Skill definition (frontmatter + phases)
  references/           ← Reference material loaded on demand
  templates/            ← Templates for artifacts produced by the skill
```

## SKILL.md Format

```yaml
---
name: te-<name>
description: <one-line description>
argument-hint: "<usage hint>"
---
```

Every skill body follows this structure:

1. **When to Use** — trigger conditions
2. **Key Principles** — non-negotiable rules
3. **Workflow** — phased execution (Phase 0, 1, 2, ...)
4. **Output** — what the skill produces
5. **Exit Gate** — conditions that must be true before moving on
6. **When Things Go Wrong** — error handling guidance
7. **Anti-Patterns to Avoid** — table of anti-patterns and better approaches
8. **Transition Points** — how to move to the next skill

## Skills Inventory (15 Total)

### Lifecycle Skills (8)

| Skill | Purpose | Analogous Harness Skill |
|-------|---------|------------------------|
| `te-thesis` | Convert market observation into structured thesis | `he-spec` |
| `te-research` | Parallel investigation across market dimensions | `he-research` |
| `te-spike` | Paper trade / backtest within timebox | `he-spike` |
| `te-plan` | Create concrete execution plan with levels and sizing | `he-plan` |
| `te-risk-size` | Pre-execution risk gate (fully deterministic) | `he-verify-release` (pre) |
| `te-execute` | Order placement with evidence tracking | `he-implement` |
| `te-manage` | Position monitoring and adjustment | (new, no Harness analog) |
| `te-exit` | Exit execution with deviation tracking | (new, split from execute) |

### Quality & Learning Skills (3)

| Skill | Purpose | Analogous Harness Skill |
|-------|---------|------------------------|
| `te-review` | Multi-dimensional post-trade review | `he-review` |
| `te-learn` | Extract guardrails from outcomes | `he-learn` |
| `te-journal` | Recurring performance analysis and drift detection | `he-doc-gardening` |

### Infrastructure Skills (4)

| Skill | Purpose | Analogous Harness Skill |
|-------|---------|------------------------|
| `te-bootstrap` | Scaffold workspace and docs structure | `he-bootstrap` |
| `te-screener` | Scan for setups matching strategy criteria | `he-triage` |
| `te-workflow` | Orchestrate full lifecycle and enforce phase order | `he-workflow` |
| `te-market-context` | Maintain current market regime classification | generated context |

### Evolution Skills (2, new — no Harness analog)

| Skill | Purpose |
|-------|---------|
| `te-evolve` | Rule efficacy audit, parameter optimization, counterfactual analysis |
| `te-meta-review` | Process effectiveness audit across all loops |
