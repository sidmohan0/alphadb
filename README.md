# AlphaDB

![Homepage screenshot](docs/screenshots/homepage.png)

AlphaDB is a prediction-market platform monorepo. It currently contains:

- `apps/api` - the production-oriented backend for market ingestion, discovery runs, persistence, and future shared APIs
- `apps/web` - the browser client for the backend-backed discovery workflows
- `apps/tui` - the terminal-first market workspace for Polymarket and Kalshi with search, split view, saved markets, and ANSI charts
- `packages/market-core` - shared provider-neutral market contracts used by the API and TUI
- `packages/sdk` - shared backend client SDK for market reads, user state, and streaming

The repo is in a Phase 1 convergence step: the legacy Polymarket discovery service and the newer TUI now live in one codebase so the TUI can progressively move onto backend APIs without a rewrite.

## Direction

The target shape is:

- one monorepo
- one canonical market model
- one backend service layer for search, trending, history, realtime delivery, and user state
- multiple clients, starting with web and TUI

Architecture notes and accepted decisions live in:

- `docs/README.md`
- `docs/adrs/README.md`
- `docs/checklists/001-backend-convergence-decision-checklist.md`
- `docs/plans/002-phase-1-backend-convergence.md`

## Workspace Layout

```text
apps/
  api/   Express + TypeScript backend
  web/   React + Vite web client
  tui/   ANSI terminal client
packages/
  market-core/ shared market contracts
  sdk/         shared backend client
docs/
  adrs/
  checklists/
  plans/
  polymarket/
```

## Local Setup

### 1. Install

```bash
git clone https://github.com/sidmohan0/alphadb.git
cd alphadb
npm install
```

### 2. Start local infra for backend work

The backend discovery stack uses Postgres and Redis:

```bash
docker compose -f docker-compose.discovery-stack.yml up -d
```

Expected ports:

- Postgres: `localhost:5432`
- Redis: `localhost:6379`
- API: `http://localhost:4000`
- Web: `http://localhost:5173`

### 3. Configure environment

```bash
cp .env.example .env
set -a
. ./.env
set +a
```

For ad hoc local sessions, the backend mainly needs:

```bash
export DATABASE_URL="postgres://postgres:postgres@localhost:5432/alphadb"
export REDIS_URL="redis://localhost:6379"
export ALPHADB_API_USER_STATE_BACKEND="postgres"
export DISCOVERY_REQUIRE_SCHEMA=1
```

### 4. Apply backend schema

```bash
npm run markets:ensure-state-schema
npm run polymarket:discovery-migrate
```

This applies:

- `apps/api/src/markets/infra/db/userStateSchema.sql`
- `apps/api/src/polymarket/infra/db/schemas.sql`

## Development

Run the backend and web app together:

```bash
npm run dev
```

Run the TUI separately:

```bash
npm run dev:tui
```

Useful workspace-scoped commands:

- `npm run build` - build api, web, and tui
- `npm run test` - run backend tests
- `npm run typecheck:tui` - typecheck the TUI only
- `npm run markets:ensure-state-schema` - ensure backend user-state schema
- `npm run markets:seed-state` - seed backend saved/recent state
- `npm run polymarket:market-channels` - run the backend Polymarket CLI
- `npm run polymarket:discovery-schema` - ensure discovery schema version state
- `npm run polymarket:discovery-migrate` - apply discovery schema

## Current Product Surfaces

### API

`apps/api` owns the durable backend primitives:

- Polymarket discovery runs
- async orchestration and dedupe
- Postgres persistence
- Redis-backed coordination
- normalized market read APIs for trending, search, unified views, and history
- backend user state for saved markets and recents
- backend SSE delivery for live market updates
- migration and maintenance scripts

### Web

`apps/web` is the browser client around the backend discovery workflows. It remains useful as an operational and product shell while AlphaDB expands beyond the original Polymarket-only flow.

### TUI

`apps/tui` is the terminal-native market workspace:

- Polymarket and Kalshi providers
- unified split mode
- fuzzy search
- saved and recent markets
- ANSI candlestick rendering

Today it still reads mostly from provider APIs directly. That is intentional during migration; the accepted direction is to move it behind the backend incrementally.

When `ALPHADB_API_BASE_URL` is set, the TUI now uses backend-owned market reads and backend-owned saved/recent state. Direct-provider mode remains available as a local fallback.

## Docs

- `docs/adrs/` - production architecture decisions for backend convergence
- `docs/checklists/` - ordered decision checklist and accepted answers
- `docs/plans/` - implementation plans
- `docs/polymarket/` - legacy Polymarket discovery implementation notes and generated artifacts

## Repo Metadata Follow-Up

Tracked as a near-term repo task in `docs/plans/002-phase-1-backend-convergence.md`:

- update the GitHub repository description
- update GitHub repository topics/tags
- refresh repo-wide marketing copy once Phase 1 stabilizes

## Status

Phase 1 is in progress. The repo has been restructured into the target app layout, but backend and TUI are not fully integrated yet. The practical goal of this phase is:

1. preserve current behavior in all three apps
2. establish one shared repo and documentation surface
3. make the backend the future source of truth for richer TUI features
