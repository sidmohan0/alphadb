# Phase 1 Backend Convergence

- Status: In Progress
- Date: 2026-03-09

This plan assumes the accepted ADR set and accepted backend convergence checklist.

## Goal

Complete the first integrated milestone:

- preserve the current ANSI TUI UX
- move the repository toward the `ts-v1` monorepo shape
- prepare shared packages
- make backend-powered TUI reads feasible without a big-bang rewrite

This phase still does not require backend-backed auth, alerts, or full discovery-run exposure in the TUI.

## Scope

In scope:

- establish merged monorepo structure
- move the TUI into `apps/tui`
- extract shared provider-neutral types
- implement backend market read endpoints for trending, unified trending, search, unified search, and history
- add backend-owned saved/recent user state
- add initial backend realtime fanout for client consumption

Out of scope:

- TUI authentication
- alerting
- claiming cross-provider market identity

## Workstreams

### 1. Repository Merge

Deliverables:

- use `ts-v1` as the structural base
- import the TUI as `apps/tui`
- keep the existing `apps/api` and `apps/web` shape
- keep CI/build scripts green for all apps

Acceptance criteria:

- `apps/tui` boots with `npm run dev --workspace apps/tui` or equivalent
- existing backend and web builds still work

### 2. Shared Domain Package

Deliverables:

- create `packages/market-core`
- move canonical market/provider/range/query types there
- remove ad hoc duplicate type definitions across apps where low-risk

Acceptance criteria:

- TUI and API compile against shared domain types
- no circular dependency between app packages

### 3. Provider Package

Deliverables:

- create `packages/providers`
- move provider normalization and fetch interfaces there
- keep provider-specific runtime edges isolated

Acceptance criteria:

- Polymarket and Kalshi adapters compile from shared package boundaries
- app-layer code no longer owns provider normalization details directly

### 4. SDK Contract

Deliverables:

- create `packages/sdk`
- define typed client contracts for:
  - trending markets
  - search
  - market detail
  - chart history

Acceptance criteria:

- TUI can be wired to SDK calls without endpoint-specific glue everywhere
- web can adopt the same contract later

### 5. Backend Read API Design

Deliverables:

- define normalized read endpoints in `apps/api`
- map provider-backed data into canonical response shapes
- decide which reads can initially proxy existing provider adapters and which need service-owned caching immediately

Acceptance criteria:

- endpoint contract is stable enough for TUI integration work
- response shapes align with `packages/market-core`

### 6. Repo Narrative And Metadata

Deliverables:

- update root README for the unified AlphaDB direction
- update repo-wide docs entry points
- add a follow-up task to refresh the GitHub repository description and topics

Acceptance criteria:

- the repository no longer reads like a single-purpose Polymarket discovery starter
- the next person landing in the repo can understand `api`, `web`, and `tui` without branch archaeology
- GitHub metadata refresh is explicitly tracked as pending

Follow-up TODO:

- update the GitHub repository description
- update GitHub repository topics/tags
- refresh any social preview or repo-wide marketing copy after Phase 1 stabilizes

## Recommended Sequence

1. Merge the TUI into the `ts-v1` monorepo shape without changing TUI behavior.
2. Extract `packages/domain`.
3. Extract `packages/providers`.
4. Create `packages/sdk`.
5. Add backend read endpoints for trending, search, market detail, and chart history.
6. Put the TUI behind a backend-read feature flag.

## Completed In This Phase

- monorepo baseline under `apps/api`, `apps/web`, and `apps/tui`
- shared market contracts in `packages/market-core`
- shared backend client in `packages/sdk`
- backend market reads for trending, unified trending, search, unified search, and history
- backend cached reads and initial SSE streaming
- backend-owned saved/recent user state with Postgres-backed persistence when `DATABASE_URL` is configured
- TUI support for backend market reads, backend unified search, backend state sync, and backend live stream consumption

## Remaining Work After This Slice

- extract provider runtime adapters into a shared package when the boundaries settle
- create a typed SDK package instead of app-local backend client glue
- add backend Polymarket realtime
- move backend user state from JSONB row storage toward fully relational ownership if product scope demands it
- add auth, tenancy, and observability hardening

## Risks

- the merge can become a rewrite if package extraction starts before the TUI is stably moved
- provider abstractions can get overdesigned before the backend contract exists
- backend read APIs can become thin proxies if canonical response design is rushed

## Recommended Immediate Next Step

Start with repository merge and workspace layout.

Concrete first task:

- create a merge branch from `ts-v1`
- import the current TUI under `apps/tui`
- preserve the current TUI boot command and tmux workflow
- do not change user-facing TUI behavior in the same step
