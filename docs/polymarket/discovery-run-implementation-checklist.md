# Discovery Runs Implementation Checklist

## Status: In Progress (core implementation complete)

This folder defines the backend execution model for async discovery runs backed by **Postgres + Redis**.

## Execution Model

- `GET /api/polymarket/market-channels/runs/:runId` is the primary read path.
- `POST /api/polymarket/market-channels/runs` is the primary create path.
- `GET /api/polymarket/market-channels` remains a compatibility shim (thin wrapper).
- `GET /api/polymarket/market-channels/runs/latest` returns latest run for dashboard bootstrap.

## Data and Ownership

- **Controller:** parse/validate → delegate → map response.
- **Service:** orchestration + policy (dedupe keying, slot acquisition, state transitions, cache decisions, periodic cleanup).
- **DB/Cache Layers:** persistence and fast lookup only.

## Completed Items

1. **Types + contracts (`types.ts`)** ✅
   - Run status + request/response contracts.
   - Page contracts for `channels`.
   - Run config + defaults for discovery config.

2. **Schema + repository layer (`infra/db`, `repositories`)** ✅
   - SQL schema and migration registry (`discovery_runs`, `discovery_run_channels`, `discovery_run_ws_scans`, `discovery_run_events`, `discovery_schema_migrations`).
   - Repository adapters for CRUD + paginated channel read.

3. **Redis cache/lock layer (`infra/cache`)** ✅
   - Distributed locks for dedupe and semaphore.
   - Cache keys for latest run, run read-model snapshot, lock state.
   - Redis retry settings and startup-safe defaults.

4. **Service orchestration (`services/discoveryRunService.ts`)** ✅
   - `createOrAttachRun`, `waitForRunIfAllowed`, `getRun`, `getLatestRun`.
   - Added service-level prune (`pruneExpiredRuns`) and background pruner (`startDiscoveryRunPruner`).
   - Added stale cache cleanup + run event persistence.
   - Added explicit state transition logs/events.

5. **Routes (`controllers`)** ✅
   - Async create/read/latest endpoints.
   - Legacy wrapper with `waitMs` handling.

6. **Maintenance + startup** ✅
   - Versioned migration flow (`discovery_schema_migrations`).
   - Optional `DISCOVERY_REQUIRE_SCHEMA=1` startup check.
   - Graceful shutdown hooks close DB/Redis resources.

7. **Tests + docs** ✅
   - Existing service/controller tests continue to validate async contract and dedupe/concurrency paths.
   - Integration test scaffold (`server/test/polymarket.discovery.integration.test.ts`) retained for real Postgres + Redis.
   - Docs and operational notes updated in root README and polymarket docs.

## Remaining Optional Enhancements

- Add CI job coverage for integration profile.
- Add OpenTelemetry/structured tracing around run lifecycle events.
- Add dead-letter/error queue handling if required beyond event logging + retries.
