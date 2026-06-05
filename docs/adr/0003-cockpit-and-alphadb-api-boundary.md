# Cockpit And AlphaDB API Are Separate Boundaries

Accepted. AlphaDB will use **Cockpit** as the architecture term for the Next.js
agent-first UI, and **AlphaDB API** as the architecture term for the Python
product API used by Cockpit and external agents. Existing code and deployment
files may still use `dashboard` naming until renamed deliberately.

## Decision

The boundary stack is:

```text
Cockpit -> AlphaDB API -> Operational State -> Runtime / Replay / Research
```

Cockpit owns presentation, interaction, navigation, and human/agent supervision
surfaces. AlphaDB API owns strategy compilation, Strategy Spec validation, Data
Explorer queries, Lab persistence, agent capabilities, runtime config, and
operational state access.

Next.js must not connect directly to Postgres, duplicate trading semantics, or
own runtime/model/replay logic. Python must not be treated as the long-term
primary UI surface, though the legacy stdlib dashboard may remain as a
compatibility or deployment surface during MVP transition.

## Rationale

The project needs quant-infrastructure-shaped boundaries:

- Typed, constrained product contracts over ad hoc UI state.
- One API surface for humans and agents.
- Replayable operational state.
- Fast UI iteration without TypeScript owning trading behavior.
- Python ownership of state, runtime, risk, replay, and research semantics.

This preserves speed while keeping the repo legible to engineers used to
serious internal trading systems.

## Consequences

- Docs should prefer Cockpit and AlphaDB API over frontend dashboard/backend
  dashboard language.
- `dashboard` remains acceptable in code paths where it is an existing package,
  command, AWS stack, or compatibility term.
- AWS currently deploys the Python dashboard service. Serving the new Cockpit at
  the public URL requires separate deployment wiring.
- Future PRs that add UI features should route through AlphaDB API rather than
  adding direct DB or trading logic in Next.js.
