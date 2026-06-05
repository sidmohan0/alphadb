# Agent-First Dashboard Priority Plan

This plan codifies the near-term priority sequence after the Agent-first
Dashboard MVP landed on `main`. It is a zoomed-out map for agents and humans who
need to keep moving quickly without reopening solved terminology debates.

## Current State

`origin/main` contains the dashboard MVP as squash commit `4a20b9e`. The tree
matches the previously pushed `feat/fair-value-live-cutover` branch.

The product vocabulary is settled enough for the next implementation pass:

- A user starts with a **Strategy Brief**.
- The **Spec Compiler** converts that brief into a constrained **Strategy Spec**
  when a supported **Strategy Template** fits.
- Unsupported or incomplete briefs become **Lab Entries** with explicit
  **compiler blockers**.
- **Data Explorer** produces **Data evidence** that can be saved into Lab.
- **Lab Entries** hold evidence, strategy JSON, runs, notes, metrics, verdicts,
  and **Semantic Lab insights**.
- The **AlphaDB API** stays Python-owned. Next.js is the Cockpit.

## Module Map

### Cockpit

- `apps/dashboard/app/page.tsx` renders the Live Operations first screen.
- `apps/dashboard/app/strategies/new/page.tsx` is the Strategy Studio creation
  path for Brief -> compile -> Spec -> save.
- `apps/dashboard/app/strategies/page.tsx` and
  `apps/dashboard/app/strategies/[id]/page.tsx` list and inspect saved Strategy
  Specs.
- `apps/dashboard/app/data/page.tsx` renders Data Explorer.
- `apps/dashboard/app/lab/page.tsx` renders Lab.
- `apps/dashboard/components/terminal/agent-terminal.tsx` provides the
  persistent Agent Terminal surface.
- `apps/dashboard/app/api/alphadb/[...path]/route.ts` proxies Cockpit calls to
  the Python AlphaDB API.

### AlphaDB API Boundary

- `src/alphadb/dashboard/app.py` owns HTTP routing, auth reuse, API envelopes,
  dashboard service methods, and the stdlib compatibility surface.
- `DashboardService.compile_strategy()` calls the Spec Compiler.
- `DashboardService.save_strategy()` persists supported Strategy Specs or routes
  unsupported briefs into Lab.
- `DashboardService.query_data_view()`, `export_data_view()`, and
  `save_data_view_to_lab()` expose Data Explorer workflows.
- `DashboardService.save_lab_entry()` and `list_lab_insights()` expose Lab
  memory.
- `DashboardService.capabilities()` and `ask_agent()` expose the first
  agent-friendly skill surface.

### Strategy Brief To Spec

- `src/alphadb/dashboard/strategy.py` owns `StrategyTemplate`,
  `compile_strategy_brief()`, `validate_strategy_spec()`,
  `strategy_spec_hash()`, and `DashboardStrategyRepository`.
- The MVP compiler is deterministic and template-based. It should remain usable
  without an LLM provider.
- The current supported shapes are fair value, model probability, structural
  threshold, momentum/reversal, and external signal threshold.

### Data Evidence

- `src/alphadb/dashboard/data_explorer.py` owns the curated `DATA_VIEWS`
  catalog, allowlisted filters, bounded queries, CSV/JSON export, and evidence
  payload generation.
- Data Explorer deliberately avoids arbitrary SQL for the MVP.
- Evidence carries source view, filters, sort, schema, row count, query hash,
  preview rows, metadata, and creation time.

### Lab Memory

- `src/alphadb/dashboard/lab.py` owns `LabEntry`, `DashboardLabRepository`,
  `lab_entry_from_compile_result()`, and heuristic insight generation.
- Lab is the single flexible research-memory object for MVP. Do not split it
  into separate idea, experiment, dataset, or snapshot object types yet.
- Semantic Lab insights are advisory. They do not promote models, authorize live
  trading, or change cutover state.

### Operational State

- `src/alphadb/state/migrations.py` owns the Postgres schema for platform runs,
  decisions, risk decisions, order intents, paper/live attempts, dashboard
  strategies, and Lab entries.
- `src/alphadb/live_runtime.py` and
  `src/alphadb/model_evaluation/fair_value_live_job.py` own the current
  fair-value live runtime path.
- `src/alphadb/model_evaluation/` owns fair-value model and replay research.

## Priority Sequence

### 1. Keep Live Authority Stable

Do not destabilize the fair-value live cutover path while polishing the
dashboard. The first pass should preserve existing live runtime config, risk-day
accounting, and gated-live behavior.

Agent-run work:

- Verify AlphaDB API health and live status endpoints after every backend
  change.
- Keep Python tests green for live runtime, dashboard API envelopes, Data
  Explorer, Lab, and Strategy Spec behavior.
- Avoid adding new security systems, role models, approval flows, or direct
  database hardening unless explicitly reprioritized.

### 2. Make Strategy Studio Useful Before It Is Smart

The highest product leverage is the Brief -> Spec -> Lab fallback loop. This is
the missing step between a user's statement and machine-executable strategy
JSON.

Agent-run work:

- Tighten the Strategy Spec schema around the fields agents actually need:
  template, market, cadence, inputs, belief, trade policy, risk, metadata, and
  compiler provenance.
- Make compiler output easy to inspect in the UI: selected template, confidence,
  strategy contract sentence, missing fields, questions, and blockers.
- Save supported specs as dashboard strategies.
- Save unsupported or incomplete briefs as Lab Entries with blockers and closest
  templates, without creating fake runnable specs.

### 3. Turn Data Explorer Into The Evidence Workbench

Data Explorer should answer the basic research questions quickly: what happened,
why did the agent act or skip, what data did it see, and what can be saved as
evidence.

Agent-run work:

- Fill out the curated Data View Catalog against real Postgres tables and
  current migrations.
- Add useful filters first: run, market, strategy, model, dataset, promotion
  state, status/outcome, source, and time windows.
- Improve schema metadata beyond `unknown` when it is cheap to do so.
- Keep exports to CSV and JSON.
- Make Save to Lab the main persistence action, not a separate saved-dataset
  workflow.

### 4. Make Lab The Memory Layer

Lab should collect the result of strategy creation, evidence review, replay,
paper/live runs, notes, metrics, and verdicts in one object.

Agent-run work:

- Add a Lab Entry detail workflow that can edit notes, verdict, status, metrics,
  and lightweight run summaries.
- Ensure Data evidence and compiler-blocked briefs both produce useful Lab
  Entries without a kind picker.
- Keep heuristic Semantic Lab insights simple: repeated topics, killed-topic
  warnings, similar briefs, and missing-capability suggestions.
- Make insight confidence and related Lab Entry ids visible, so advisory memory
  does not look like proof.

### 5. Let The Agent Terminal Use The Same Skills

The terminal should not become a separate toy layer. It should call the same
AlphaDB API capabilities that the UI and external agents can discover.

Agent-run work:

- Keep `/api/capabilities` self-describing.
- Keep `/api/ask` as simple intent routing over registered skills.
- Add skills only when they map to real product actions: query data, save
  evidence, create Lab Entry, compile brief, list strategies, inspect live
  status, pause/stop where already supported.
- Unknown commands should return suggestions, not invented behavior.

### 6. Attach Runs And Reports To Research Memory

Once Strategy Studio, Data Explorer, and Lab are coherent, the next unlock is
connecting actual run outcomes to Lab Entries.

Agent-run work:

- Attach replay, shadow, paper, gated-live, or live run summaries as JSON on Lab
  Entries.
- Preserve Strategy Spec snapshots automatically when a run or Lab Entry needs
  provenance.
- Keep promotion stages informational for MVP unless separate cutover work
  explicitly adds gates.
- Use Lab verdicts to drive next-test suggestions, not live-trading authority.

## Explicit Deferrals

These are not priorities for the current MVP pass:

- Arbitrary natural-language-to-code strategy generation.
- Mandatory LLM compilation.
- YAML import/export.
- Arbitrary SQL editing.
- New RBAC, OAuth, approval mazes, or security architecture.
- Paid external-data onboarding flows.
- Full model training or model promotion automation from the dashboard.
- Maker execution policy.
- Separate Research Idea, Experiment, Dataset, or Snapshot object models.
- Multi-user collaboration semantics beyond simple metadata.

## Operating Rule

Prefer sparse and real over rich and fake. If the UI looks empty because the
backend has little data, keep it empty and make the next useful action obvious.
The MVP line is automatic provenance, not decorative completeness.
