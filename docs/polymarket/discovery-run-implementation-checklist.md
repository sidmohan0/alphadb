# Discovery Runs Implementation Checklist

## Status: In Progress

This folder now defines the backend execution model for async discovery runs backed by **Postgres + Redis**.

## Execution Model

- `GET /api/polymarket/market-channels/runs/:runId` is the primary read path.
- `POST /api/polymarket/market-channels/runs` is the primary create path.
- `GET /api/polymarket/market-channels` remains a compatibility shim (thin wrapper).
- `GET /api/polymarket/market-channels/runs/latest` returns latest run for dashboard bootstrap.

## Data and Ownership

- **Controller:** parse/validate → delegate → map response.
- **Service:** orchestration + policy (dedupe keying, slot acquisition, state transitions, caching decisions, error mapping to run state).
- **DB/Cache Layers:** persistence and fast lookup only.

## Commit Steps

1. **Types + contracts (`types.ts`)**
   - Add run status + request/response contracts.
   - Add page response models for `channels`.
   - Add discovery run config contract and defaults for run/env behavior.

2. **Schema + repository layer (`infra/db`, `repositories`)**
   - Add SQL schema file for `discovery_runs`, `discovery_run_channels`, `discovery_run_ws_scans` (+ optional events table).
   - Implement repository adapters for CRUD + paginated channel read.

3. **Redis cache/lock layer (`infra/cache`)**
   - Implement keys for:
     - active run pointer (`latest`)
     - cached run read model
     - dedupe lock by normalized request key
     - distributed concurrency semaphore

4. **Service orchestration (`services/discoveryRunService.ts`)**
   - `createOrAttachRun`, `waitForRunIfAllowed`, `getRun`, `getLatestRun`.
   - Add worker path that runs existing discovery sync function, persists result, updates cache, and handles cleanup of locks/slots.

5. **Routes (`controllers`)**
   - Add primary runs endpoints.
   - Convert old route to compatibility wrapper with `waitMs` handling.

6. **Tests + docs updates**
   - Add unit tests for service orchestration behavior.
   - Update controller tests for new flows and compatibility behavior.
   - Keep existing service extraction tests focused on parsing/extraction behavior.
   - Update docs (`README`, `docs/polymarket/README`, docs index) to match API surface.

## Core Invariants

- Keep business rules in service layer, not inside SQL constraints.
- DB stores durable state + constraints.
- Redis enforces runtime uniqueness/concurrency across instances.
- Controller stays thin.
- Existing structured error contract remains the canonical response for failures (`code`, `message`, `retryable`, `requestId`, `details`).
