# Strategy Diagnosis Guardrail

Use this agent workflow before changing strategy, model, or risk logic. It is a
lightweight MVP guardrail, not a new AlphaDB product object or platform
capability.

## Scope

Create a short diagnosis note first when a request would change:

- strategy logic or parameters,
- model behavior, features, or selection policy,
- risk gates, sizing, caps, or execution admission logic.

Skip the diagnosis-first requirement when:

- the user explicitly asks for a direct implementation-only change,
- the immediate task is an emergency live-risk action such as pause, stop,
  disabling live orders, or reducing exposure.

Emergency actions should happen first. If useful, produce the diagnosis after
the system is made safer.

## Diagnosis Shape

Keep the note to one page unless the user asks for deeper research.

```text
Current status / risk action
- What is live, paused, disabled, or exposure-reduced?
- What immediate safety action was taken or intentionally not taken?

Observed underperformance
- What behavior, PnL, fill pattern, skip pattern, or metric triggered the work?
- What time range, run id, strategy, market family, and config are in scope?

Evidence inspected
- Which logs, reports, Data Explorer views, run manifests, live status, fills,
  decisions, risk decisions, settlements, or artifacts were inspected?
- Which evidence was missing or too weak to trust?

Suspected failure modes
- List the most plausible causes, ordered by evidence strength.
- Separate model belief problems, execution damage, risk/sizing problems,
  data-quality issues, market regime changes, and implementation defects.

One next experiment
- Name the smallest useful replay, paper run, config change, data slice, or code
  inspection that would discriminate between the top failure modes.

Proposed code/config changes, if any
- State whether a change is recommended now.
- If no change is justified yet, say what evidence would justify one.
```

## Artifact Handling

Generated diagnosis runs, exports, logs, and private evidence belong under
ignored roots such as `research/` or `artifacts/`. Do not commit generated
market data, private account material, model binaries, or strategy logs.

Committed docs may summarize public-safe conclusions, but should reference
private or generated artifacts only by stable path, run id, or hash when that is
already part of the existing workflow.

## Boundaries

This workflow does not add Lab integration, schema changes, Cockpit UI,
artifact manifests, Codex skills, runtime changes, model changes, risk changes,
or new `CONTEXT.md` domain terms. Use existing AlphaDB vocabulary such as
Strategy Brief, Strategy Spec, Data evidence, Lab Entry, Runtime, Replay, and
Research when those concepts are already relevant.
