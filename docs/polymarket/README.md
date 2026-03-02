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

### Local operator runbook

- Spin up dependencies:

```bash
docker-compose -f docker-compose.discovery-stack.yml up -d
```

- Start API and verify run creation + polling works.
- Enable pruner in non-idle environments:

```bash
DISCOVERY_RUN_PRUNER_ENABLED=1 npm run start
```

### Production polish recommendations implemented

- ✅ Run pruning job:
  - `startDiscoveryRunPruner` + `DISCOVERY_RUN_PRUNER_ENABLED`
- ✅ Cache invalidation on prune:
  - Latest-run cache key is refreshed when stale
- ✅ Structured run lifecycle logs:
  - State transitions logged (`queued`, `running`, `succeeded`, `failed`).
- ✅ Integration verification path:
  - `npm run --workspace server test:integration`

## Suggested manual checks

- Query a run:

```bash
curl http://localhost:4000/api/polymarket/market-channels/runs/<runId>
```

- Poll via compatibility wrapper:

```bash
curl "http://localhost:4000/api/polymarket/market-channels?chainId=137&waitMs=250"
```

## Notes

- This model intentionally places orchestration decisions in services and persistence/caching in infra.
- Redis is the default production mode for dedupe/locks and cross-instance concurrency guarantees.
