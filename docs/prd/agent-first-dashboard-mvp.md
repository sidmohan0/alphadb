# Agent-First Dashboard MVP PRD

## Problem Statement

AlphaDB is moving from a live-operator dashboard toward agent-first trading infrastructure. The current target platform has strong backend primitives for replayability, auditability, live runtime config, decisions, risk decisions, model registry records, feature rows, raw events, paper execution, and live attempts. The user experience does not yet expose those primitives as one coherent product.

Humans need to commission and supervise autonomous strategy agents, not manually operate every trading loop. They need to express a strategy as a human-readable Strategy Brief and machine-readable Strategy Spec, observe what the agent is doing in the rhythm of the market, inspect the collected operational data, save useful evidence into Lab, and keep a research memory that accumulates agent and human learning over time.

For this MVP, speed matters more than robust security or perfect platform polish. The capital is disposable, Postgres is already private, and the existing dashboard access controls are enough. New work should not add role systems, granular permissions, extra approval mazes, or direct security infrastructure unless explicitly reprioritized.

## Solution

Build an Agent-First Dashboard MVP using the supplied Next.js dashboard prototype as the frontend seed and AlphaDB's existing Postgres-backed operational state as the data source.

The dashboard should contain five first-class workspaces:

1. Live Operations: the operator's first screen, centered on the current trading cycle, current agent assessment, risk/exposure state, recent attempts, and a single obvious stop/pause intervention path.
2. Strategy Studio: a contract canvas where a user defines a Strategy Brief and uses a constrained Spec Compiler to produce a validated, template-based Strategy Spec covering the hypothesis, market family, evidence sources, belief engine, trade policy, risk envelope, autonomy notes, and promotion path.
3. Agent Terminal: a persistent command surface backed by a small, self-describing skill registry for strategy, data, lab, and system actions.
4. Data Explorer: an evidence locker for browsing curated Postgres views, filtering records, exporting rows, and saving a filtered slice to Lab as evidence.
5. Lab: a flexible research-memory workspace for hypotheses, blocked briefs, data evidence, strategy JSON, run summaries, notes, verdicts, and semantic Lab insights.

The MVP should preserve the target-platform and Current MVP boundary. It may observe, display, and control target-platform components, but it must not assume ownership of the existing live MVP until cutover is explicitly handled by other work.

## User Stories

1. As a strategy creator, I want to describe a market hypothesis in plain English, so that I can start from my trading idea instead of database or model terminology.
2. As a strategy creator, I want the system to turn my idea into a readable strategy contract sentence, so that I can verify what the agent will actually do.
3. As a strategy creator, I want to choose a market family such as KXBTC15M, so that the strategy is bound to a concrete recurring market specification.
4. As a strategy creator, I want to choose the decision minute in the market cycle, so that the agent evaluates each instance at the intended cadence.
5. As a strategy creator, I want to see a market coverage meter, so that I know whether every eligible market instance receives a trade or skip decision.
6. As a strategy creator, I want to choose evidence sources from available sources, so that the strategy only depends on observable inputs the platform can collect.
7. As a strategy creator, I want the interface to suggest missing data sources from my hypothesis, so that I can notice when the idea requires funding rates, on-chain data, weather data, or other sources.
8. As a strategy creator, I want to define the belief source as rules, formula, or model, so that structural, fair-value, and ML strategies all fit one flow.
9. As a strategy creator, I want to configure structural rules, so that non-model strategies can be expressed without pretending to be ML.
10. As a strategy creator, I want to configure formula parameters, so that fair-value strategies can be tuned and understood quickly.
11. As a strategy creator, I want to select a model artifact from the model registry, so that ML strategies reference immutable model and feature provenance.
12. As a strategy creator, I want to choose the trade side policy, so that the agent can trade YES only, NO only, or whichever side has better expected value.
13. As a strategy creator, I want to set minimum edge after fees, so that low-quality opportunities are skipped automatically.
14. As a strategy creator, I want to set max dollars per market and daily loss exposure, so that the agent stays inside a disposable but explicit risk envelope.
15. As a strategy creator, I want to declare autonomy notes and constraints, so that the Strategy Spec is visible even when the MVP does not enforce a full permission system.
16. As a strategy creator, I want to save a draft Strategy Brief and Strategy Spec, so that I can come back to an incomplete strategy without running it.
17. As a strategy creator, I want to promote a strategy through replay, shadow, paper, gated live, and live states, so that the lifecycle is legible.
18. As a strategy creator, I want promotion blockers to be informational and lightweight for the MVP, so that I can move fast without new approval friction.
19. As a live supervisor, I want the dashboard to open on live operations, so that the first thing I see is whether the agent is running and what it is doing.
20. As a live supervisor, I want a countdown to the next market cycle, so that I understand the operating rhythm without reading logs.
21. As a live supervisor, I want to see current position, exposure, P&L, and latest decision outcome, so that I can decide whether intervention is needed.
22. As a live supervisor, I want to see the agent's current assessment and confidence, so that I understand its latest belief at a glance.
23. As a live supervisor, I want a unified activity stream, so that trades, skips, human interventions, and agent reasoning appear in one timeline.
24. As a live supervisor, I want one obvious pause or stop control, so that I can intervene quickly.
25. As a live supervisor, I want live runtime config to remain editable, so that I can adjust disposable capital limits without redeploying.
26. As an agent-terminal user, I want to type commands such as "show pnl" or "pause losing strategies", so that I can supervise the system conversationally.
27. As an agent-terminal user, I want the terminal to show which skill was invoked, so that actions remain understandable.
28. As an agent-terminal user, I want unknown commands to return suggestions, so that I can discover what the system can do.
29. As an external agent, I want a capabilities endpoint, so that I can discover AlphaDB actions programmatically.
30. As an external agent, I want a natural-language ask endpoint, so that I can delegate simple questions or actions without knowing every API route.
31. As a researcher, I want to browse raw events, so that I can inspect what the platform collected.
32. As a researcher, I want to browse feature rows, so that I can inspect decision-time evidence and no-lookahead metadata.
33. As a researcher, I want to browse decisions, so that I can inspect probability, selected side, skip reason, and outcome.
34. As a researcher, I want to browse risk decisions, so that I can see why an order candidate was approved or denied.
35. As a researcher, I want to browse orders and fills, so that I can connect decisions to execution outcomes.
36. As a researcher, I want to browse settlement-related records or manifests, so that I can reason about final outcomes where available.
37. As a researcher, I want to browse model registry records, so that I can connect decisions back to model artifacts.
38. As a researcher, I want simple filters for strategy, run, market, time range, outcome, and skip reason, so that I can answer common questions quickly.
39. As a researcher, I want row counts and schema summaries for each view, so that I understand the shape of the data before exporting it.
40. As a researcher, I want to export a filtered view to CSV or JSON, so that I can analyze data outside the dashboard.
41. As a researcher, I want to save a filtered view to Lab, so that a Lab Entry can reference the exact evidence slice used.
42. As a researcher, I want saved evidence to include filters, row count, schema, query hash, and a small preview, so that the evidence remains reusable and traceable.
43. As a researcher, I want Data Explorer evidence to become a Lab Entry directly, so that data exploration turns into research memory without choosing another object type.
44. As a Lab user, I want to create a Lab Entry with a title and hypothesis or note, so that research starts with a claim we can test.
45. As a Lab user, I want blocked strategy briefs to save as Lab Entries with compiler blockers, so that unsupported ideas are not lost.
46. As a Lab user, I want a Lab Entry to hold strategy JSON, evidence, run summaries, notes, metrics, and metadata, so that related work gathers in one place.
47. As a Lab user, I want aggregate metrics such as trade count, win rate, P&L, and Sharpe-like summary where available, so that I can compare entries.
50. As a Lab user, I want agent notes and human notes, so that interpretation is preserved alongside metrics.
51. As a Lab user, I want to mark a Lab Entry as continue, revise, or kill, so that every tested branch can produce a decision.
52. As a Lab user, I want killed and revised entries to stay visible, so that the agent can learn from failed branches.
53. As a Lab user, I want semantic insights that detect repeated patterns, warnings, similarities, and suggested next tests, so that Lab history becomes active memory.
54. As a Lab user, I want insights to link back to related Lab Entries, so that I can inspect the evidence behind a suggestion.
55. As a Lab user, I want insight confidence to be visible, so that advisory analysis is not confused with proof.
56. As an agent, I want Lab Entry verdicts and notes to be machine-readable, so that I can propose better next tests.
57. As an engineer, I want Data Explorer and Lab repositories to be small and independently testable, so that the backend stays reliable while the UI moves fast.
58. As an engineer, I want curated query definitions instead of arbitrary SQL as the initial API, so that the MVP ships fast with predictable behavior.
59. As an engineer, I want the existing dashboard auth pattern reused, so that we avoid spending MVP time on new security.
60. As a product owner, I want this delivered as one MVP PRD, so that the team can move quickly without front-loading a large issue taxonomy.

## Acceptance Criteria

- The dashboard uses the supplied design prototype as the visual and component foundation.
- The first screen remains live-operations oriented and shows cycle rhythm, agent assessment, recent activity, risk/exposure, and intervention controls.
- Strategy Studio lets a user create and save a Strategy Brief and validated template-based Strategy Spec with market/cadence, data sources, belief mode, trade policy, risk envelope, and promotion state.
- Strategy Studio saves unsupported briefs as Lab Entries with compiler blockers and closest-template metadata instead of pretending they are runnable specs.
- Strategy Studio supports rules, formula, and model belief modes in the same contract flow.
- Data Explorer exposes curated Postgres-backed views for raw events, feature rows, decisions, risk decisions, order/order-like records, fill/fill-like records, settlement-related records or manifests, and model registry records.
- Data Explorer supports common filters, row limits, schema summaries, CSV/JSON export, and Save to Lab evidence creation.
- Data evidence is persisted inside Lab Entries with enough provenance to recreate or explain the source query.
- Lab supports creating flexible Lab Entries with blockers, evidence, strategy JSON, notes, run summaries, metrics, and verdicts.
- Semantic Lab insights are displayed as pattern, warning, similarity, or suggestion records.
- Agent Terminal exposes a small capabilities registry and can route basic strategy, data, lab, and system commands.
- The MVP reuses existing dashboard access controls and private Postgres assumptions; no new role system, permission model, or security review flow is introduced.
- Existing live runtime config and status behavior continues to work.
- The Current MVP remains authoritative until separate cutover work explicitly changes that.

## Implementation Decisions

- Use the supplied Next.js prototype as the starting point for the dashboard frontend. Keep the dark, dense, operator-grade interaction model and adapt names to AlphaDB's target-platform vocabulary.
- Keep the existing Python target-platform services as the operational backend. Add JSON APIs for dashboard data rather than rewriting existing trading, replay, state, or registry logic in the frontend.
- Introduce Strategy, Strategy Brief, and Strategy Spec models for Strategy Studio. The Brief is human-authored thesis and notes; the Spec is a structured JSON contract with human-readable sentence rendering. It should include hypothesis, market family, cadence, evidence sources, belief engine, trade policy, risk envelope, autonomy notes, and promotion stage.
- Introduce a constrained Spec Compiler. The compiler maps a Brief onto an allowlisted Strategy Template, proposes field values with confidence and missing-field markers, asks targeted questions, and runs deterministic validation before saving a Spec.
- Implement the first Spec Compiler with deterministic extraction and constrained UI choices while keeping the proposal shape LLM-ready. It must function without an LLM provider.
- Treat "autonomy and permissions" as Strategy Spec metadata for this MVP. It may guide display and agent behavior, but it should not become a full enforcement system or new approval layer.
- Support template-based Strategy Specs first. MVP templates may cover fair value, momentum, mean reversion, threshold distance, and external-signal shock shapes; arbitrary formula/code generation is out of scope.
- Store and exchange Strategy Specs as JSON-backed structured data for the MVP. YAML import/export is explicitly later work.
- If a Brief does not fit an existing Strategy Template, save it as a Lab Entry with compiler blockers, closest template metadata, missing capabilities, and optional capability-request metadata.
- Persist Lab Entries through one flexible JSON-backed model. The MVP UI should not force users to choose Research Idea, Experiment, Dataset, or Snapshot object types.
- Keep belief generation separate from trade policy. Rules, formulae, and models all produce belief fields; the shared decision policy decides whether to trade or skip.
- Add a curated Data View Catalog. Each catalog entry defines a stable view name, display label, allowed filters, default sort, maximum rows, column metadata, and row mapping for the Data Explorer.
- Prefer curated SQL or repository methods over arbitrary SQL in the first MVP. This is primarily a speed and maintainability choice, not a security project.
- Add Data evidence persistence inside Lab Entries. Evidence records source view, filters, row limit, sort, row count, column schema, query hash, creator label, small preview, and metadata. Exported CSV/JSON row artifacts are optional separate artifacts linked only when produced.
- Add Lab Entry persistence. A Lab Entry records title, hypothesis, status, verdict, blockers, evidence, strategy JSON, configuration summary, aggregate metrics, human notes, agent notes, and timestamps.
- Keep run summaries as JSON on Lab Entries for MVP. They can reference replay, shadow, paper, gated-live, or live run ids and store lightweight metrics from those runs.
- Add Semantic Lab Insight generation. Insights should store type, text, related Lab Entry ids, confidence, source, generated timestamp, and status.
- Implement semantic analysis in the fastest useful way. The first version may use deterministic tags and similarity heuristics. If a configured LLM provider is already available, the insight generator may optionally use it, but the MVP must function without it.
- Add a small Agent Skill Registry that powers both the terminal UI and simple external capability discovery. Skills should be self-describing and include id, name, description, category, params, confirmation requirement, and return type.
- Add capability and ask endpoints for agent friendliness. The ask endpoint can start with simple routing over registered skill triggers; it does not need a full autonomous planner.
- Keep exports simple. CSV and JSON are enough for the MVP. Parquet can be added later if research workflows demand it.
- Keep direct external data-source connection flows out of the first pass. Data-source suggestions can show what would help a hypothesis, but connecting paid APIs is not required.
- Maintain the target-platform/MVP boundary. The new dashboard can observe and control target-platform services, but it must not silently assume live Current MVP cutover.
- Preserve provenance automatically. Data evidence, Lab Entry records, notes, run summaries, and insights should be saved by default because memory is part of the product, not an optional compliance add-on.

## Testing Decisions

- Test external behavior rather than component internals. Backend tests should assert that APIs, repositories, and saved records behave correctly from the caller's perspective.
- Add repository tests for the Data View Catalog query layer. Tests should verify view listing, allowed filters, row limits, sorting, schema summaries, and failure behavior for unknown views or unsupported filters.
- Add repository tests for Data evidence payloads. Tests should verify deterministic query hashing, row-count capture, schema capture, and Lab Entry attachment.
- Add repository tests for Lab Entry records. Tests should verify entry creation, compiler blocker persistence, evidence links, notes, verdict changes, run summary links, and aggregate metrics storage.
- Add tests for Semantic Lab Insight generation. Tests should verify that repeated tags, similar hypotheses, and negative verdict patterns can produce stable advisory insight records without relying on an external LLM.
- Add tests for the Agent Skill Registry. Tests should verify capability listing, trigger matching, parameter validation, confirmation flags, and basic skill execution results.
- Add API-level tests for Data Explorer and Lab endpoints using the same simple HTTP testing style already used for dashboard auth and live console behavior.
- Add lightweight frontend smoke tests only after the frontend is wired into the repo's build system. These should verify that the main workspaces render and basic navigation works, not pixel-perfect styling.
- Existing tests for the live dashboard, live runtime config, decision engine, risk gate, feature ledger, model registry, strategy scheduler, and monitoring status are relevant prior art.

## Out of Scope

- New authentication systems, RBAC, granular permissions, security review flows, or direct database hardening beyond existing private Postgres and dashboard access controls.
- Multi-user collaboration semantics beyond simple created-by labels and timestamps.
- Arbitrary unrestricted SQL editing in the dashboard.
- Paid API onboarding or secrets management for new data sources.
- Full autonomous model retraining, promotion, live cutover, or arbitrary natural-language-to-code strategy generation.
- Maker execution policy implementation.
- A complete external agent handoff protocol beyond basic capabilities and ask endpoints.
- Perfect semantic memory. The first insight engine can be heuristic and advisory.
- Rebuilding the Current MVP or making the target platform authoritative for live trading.
- Building every future PRD or Linear child issue before implementation begins.

## Further Notes

The supplied design prototype already contains strong first-pass implementations of the shell, Strategy Studio, Live Operations components, Agent Terminal, skill registry, mock data, and settings screens. The MVP should copy and adapt useful parts, but remove prototype-only screens and mock-heavy surfaces that add friction or dead ends.

The two new screens provided by the user should be treated as target UX for Data Explorer and Lab:

- Data: "Evidence locker - browse, filter, export, Save to Lab."
- Lab: "Hypotheses, evidence, verdicts, semantic memory."

The product should feel fast and slightly dangerous in the way an MVP trading cockpit should: the agent acts, the human supervises, and the system remembers what happened. The line to hold is not extra permission friction; it is automatic provenance.
