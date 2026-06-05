# AlphaDB Architecture Boundaries

AlphaDB should read like a trading-infrastructure repo, not a pile of dashboard
screens. These boundaries are the default rules for future work.

## Boundary Stack

```text
Cockpit -> AlphaDB API -> Operational State -> Runtime / Replay / Research
```

## Cockpit

The Cockpit is the Next.js human-and-agent supervision UI.

Owns:

- Live Operations display and intervention controls.
- Strategy Studio user flow.
- Data Explorer workspace.
- Lab workspace.
- Agent Terminal surface.
- UI state, navigation, rendering, and optimistic interaction polish.

Does not own:

- Trading logic.
- Postgres queries.
- Runtime state transitions.
- Model, replay, settlement, or risk semantics.
- Direct database access.

Rule: Cockpit calls AlphaDB API. It does not become a second backend.

## AlphaDB API

The AlphaDB API is the Python product API used by Cockpit and external agents.
Current code still uses `dashboard` naming in places, but architecture language
should prefer AlphaDB API.

Owns:

- Strategy Brief compilation.
- Strategy Spec validation and persistence.
- Data Explorer curated views and exports.
- Data evidence creation.
- Lab Entry persistence.
- Semantic Lab insight generation.
- Agent capabilities and ask routing.
- Runtime config read/write surfaces.
- Existing dashboard auth reuse for MVP.

Does not own:

- Frontend presentation.
- Arbitrary user SQL.
- Arbitrary natural-language-to-code execution.
- New enterprise auth or permission systems for the disposable-capital MVP.

Rule: AlphaDB API exposes product capabilities. Cockpit and agents use the same
capability surface.

## Operational State

Operational State is Postgres.

Owns:

- Platform runs.
- Market instances.
- Raw events.
- Feature rows.
- Decisions.
- Risk decisions.
- Order intents.
- Paper orders and fills.
- Live order attempts.
- Model registry records.
- Dashboard runtime config.
- Strategy records.
- Lab Entries.

Does not own:

- Full generated research datasets.
- Model binaries.
- Licensed official settlement inputs.
- Private exchange account material.

Rule: operational state is queryable and replay-supporting, but generated
research artifacts stay file/object-storage backed and hash-referenced.

## Runtime

Runtime workers execute fixture, shadow, paper, gated-live, and future live
flows.

Owns:

- Market-cycle handling.
- Shared decision engine invocation.
- Risk-gate invocation.
- Taker-only paper/live execution path.
- Outcome recording.
- Run manifests and config snapshots.

Does not own:

- Cockpit UI behavior.
- Lab interpretation.
- Model promotion authority unless a separate promotion gate says so.

Rule: runtime consumes Strategy Specs and config, then writes outcomes.

## Replay And Research

Replay and research systems produce evidence, reports, and artifacts.

Owns:

- Fair-value policy replay.
- Model evaluation reports.
- Settlement-state readiness artifacts.
- External signal research datasets and manifests.
- Edge verdicts.

Does not own:

- Live trading authority.
- Cockpit rendering.
- Hidden mutations to operational state.

Rule: reports can inform decisions; they do not authorize live trading by
themselves.

## Spec Compiler

The Spec Compiler maps a Strategy Brief into a constrained Strategy Spec.

Owns:

- Template selection.
- Allowlisted field extraction.
- Confidence and missing-field reporting.
- Compiler blockers.
- Deterministic validation.

Does not own:

- Arbitrary code generation.
- Mandatory LLM dependency.
- Live execution.

Rule: unsupported briefs become Lab Entries with blockers, not fake runnable
specs.

## Data Explorer

Data Explorer is an evidence workbench over curated operational views.

Owns:

- View catalog.
- Allowlisted filters.
- Bounded row queries.
- CSV/JSON export.
- Save-to-Lab evidence payloads.

Does not own:

- Arbitrary SQL editing.
- Separate saved-dataset object model for MVP.
- Direct research artifact storage unless explicitly exported.

Rule: every saved evidence payload records provenance.

## Lab

Lab is research memory.

Owns:

- Lab Entries.
- Compiler blockers.
- Data evidence.
- Strategy JSON references.
- Run summaries.
- Human and agent notes.
- Metrics.
- Verdicts.
- Semantic Lab insights.

Does not own:

- Model promotion gates.
- Live trading authority.
- Separate idea/experiment/dataset/snapshot object types for MVP.

Rule: Lab preserves memory and suggests next work; it does not grant authority.

## Agents

Agents use the same AlphaDB API as Cockpit.

Owns:

- Capability discovery.
- Structured action invocation.
- Natural-language routing where supported.
- Reading Lab and Data evidence.
- Creating or updating Strategy Briefs, Lab Entries, and notes through API.

Does not own:

- Hidden privileged routes.
- Unlogged live actions.
- Special DB access.

Rule: if a human action matters, the agent path should be equally inspectable.

## MVP Security Posture

For disposable live-trading capital, MVP security stays intentionally light:
private Postgres, existing dashboard access controls, signed cookies/PIN in AWS,
and fail-closed live-order gates.

Do not add RBAC, OAuth, granular permission systems, or security review flows
unless explicitly reprioritized.

## Naming Rules

- Use **Cockpit** for the Next.js UI.
- Use **AlphaDB API** for the Python API.
- Use **Operational State** for Postgres.
- Use **Runtime** for workers.
- Use **Lab** for research memory.
- Use **Data evidence**, not saved dataset snapshot, for MVP saved queries.
- Treat **dashboard** as a historical or deployment word when current code still
  uses it.
