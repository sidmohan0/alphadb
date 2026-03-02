# Polymarket Market Channel Discovery — Implementation Notes

## What this report covers

This folder contains implementation notes and runbook artifacts for the discovery work and async run architecture:

- `polymarket-market-channels-visual-plan-diagram.html`
  - Visual plan + topology/flow diagram.
- `polymarket-market-channels-call-graph.html`
  - Call graph / call hierarchy.
- `polymarket-discovery-runs-visual-plan.html`
  - Architecture and endpoint model for async `discovery_runs` + Postgres/Redis orchestration.

Open these files in a browser for rendered visuals.

## Current backend structure

The discovery feature now follows a distributed async model:

- `server/src/polymarket/types.ts`
  - Run lifecycle contracts, config defaults, paging contracts.
- `server/src/polymarket/utils.ts`
  - Parsing and extraction helpers.
- `server/src/polymarket/services/marketChannelDiscoveryService.ts`
  - Discovery orchestration and websocket probing.
- `server/src/polymarket/services/discoveryRunService.ts`
  - Async run orchestration (`queued/running/succeeded/partial/failed`), dedupe, concurrency and pruning.
- `server/src/polymarket/controllers/polymarket.controller.ts`
  - HTTP controller for async endpoints + compatibility wrapper.
- `server/src/polymarket/infra/db/*`
  - Postgres pool + schema scripts.
- `server/src/polymarket/infra/cache/*`
  - Redis-backed lock/semaphore/cache layer.
- `server/src/polymarket/repositories/*`
  - Persistence adapters for runs/channels/ws scan.
- `server/src/polymarket/maintenance/migrateDiscoveryRuns.ts`
  - Schema bootstrap helper.

## API behavior

Primary async endpoints:

- `POST /api/polymarket/market-channels/runs`
  - Returns `{ status, runId, pollUrl, requestId }`.
- `GET /api/polymarket/market-channels/runs/{runId}`
  - Returns full run payload + `channels` page slice.
- `GET /api/polymarket/market-channels/runs/latest`
  - Returns latest run in DB/cache for dashboard bootstrap.

Compatibility path:

- `GET /api/polymarket/market-channels`
  - `waitMs=0` → no wait (legacy shell)
  - `waitMs>0` → waits up to provided window and returns terminal payload when ready

Error codes now include:

- `invalid_input`
- `clob_request_timeout`
- `clob_request_network`
- `clob_request_failure`
- `discovery_concurrency_limit`
- `websocket_invalid_url`
- `websocket_request_error`
- `run_not_found`
- `unexpected_error`

## Operations / rollout checklist

### One-time schema setup

```bash
npm run polymarket:discovery-migrate
```

This applies:

- `server/src/polymarket/infra/db/schemas.sql`
  - `discovery_runs`
  - `discovery_run_channels`
  - `discovery_run_ws_scans`
  - `discovery_run_events`
  - `discovery_schema_migrations`

You can also let the app enforce schema state on startup with:

```bash
export DISCOVERY_REQUIRE_SCHEMA=1
npm run dev
```

The startup check writes `discovery_schema_migrations.schema_name='discovery_runs_schema'` with version 1 when up-to-date.

### Local operator runbook (single command path)

```bash
# 1) start infra
docker-compose -f docker-compose.discovery-stack.yml up -d

# 2) load local env (.env is tracked from .env.example)
cp .env.example .env
set -a
. ./.env
set +a

# 3) run the stack (migration can be automatic with DISCOVERY_REQUIRE_SCHEMA=1)
DISCOVERY_REQUIRE_SCHEMA=1 DISCOVERY_SCHEMA_TARGET_VERSION=1 npm run dev

# or run explicit migration beforehand if you prefer manual control
npm run polymarket:discovery-migrate

# 4) run the stack with optional pruning
DISCOVERY_RUN_PRUNER_ENABLED=1 npm run dev
```

### Smoke checks after startup

```bash
# should return "run_not_found" until at least one run exists
curl -i http://localhost:4000/api/polymarket/market-channels/runs/latest

# start + poll a run
RUN_ID=$(curl -s -X POST http://localhost:4000/api/polymarket/market-channels/runs -H 'Content-Type: application/json' -d '{"chainId":137}' | jq -r '.runId')
curl "http://localhost:4000/api/polymarket/market-channels/runs/$RUN_ID"
```

- Enable pruner in non-idle environments:

```bash
DISCOVERY_RUN_PRUNER_ENABLED=1 npm run start
```

### Production polish recommendations implemented

- ✅ Run pruning job:
  - `startDiscoveryRunPruner` + `DISCOVERY_RUN_PRUNER_ENABLED`
- ✅ Cache invalidation on prune:
  - Pruned run IDs now clear cached run payloads and dedupe keys to avoid stale attachments.
- ✅ Structured run lifecycle logs/events:
  - State transitions logged in `discovery_run_events` for audit and troubleshooting.
- ✅ Startup migration handling:
  - `DISCOVERY_REQUIRE_SCHEMA=1` gates schema bootstrap/update at boot.
- ✅ Integration verification path:
  - `npm run --workspace server test:integration`

## Notes

- This model intentionally places orchestration decisions in services and persistence/caching in infra.
- Redis is the default production mode for dedupe/locks and cross-instance concurrency guarantees.
