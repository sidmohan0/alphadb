# Polymarket Discovery Service (TypeScript Monorepo)

A production-oriented TypeScript starter that now focuses on **Polymarket market-channel discovery** with:

- a layered backend architecture (controller / service / infra)
- REST + websocket discovery orchestration
- explicit empty-state handling
- structured error contracts and retry hints
- distributed dedupe/concurrency protections
- Postgres + Redis-backed async run persistence and polling

The repo also includes a lightweight full-stack shell (Express + React/Vite) so the service can be consumed locally from a frontend with minimal extra wiring.

## Highlights

- **Modular backend** in `server/` with a dedicated `polymarket` domain module
- **Async run lifecycle** with polling and latest-run bootstrapping
- **Query parsing + validation** in API controller
- **Typed error mapping** with stable response codes and retry hints
- **Distributed in-flight dedupe** for identical request configs
- **Concurrency ceiling** for unique discovery runs (defaults to `4`)
- **Connection pooling** for Postgres (`PG_POOL_MAX`, etc.)
- **Run pruning scheduler** for expired run cleanup
- **Integration test hooks** for real Postgres + Redis

## Quick Setup (Local)

```bash

git clone https://github.com/sidmohan0/alphadb.git
cd alphadb
npm install
```

### Start dependencies (local dev)

```bash
docker-compose -f docker-compose.discovery-stack.yml up -d
```

This starts:

- Postgres on `localhost:5432`
- Redis on `localhost:6379`

### Run the app

```bash
npm run dev
```

- Frontend: `http://localhost:5173`
- Backend/API: `http://localhost:4000`

The Vite dev server proxies `/api/*` requests to the backend.

### Apply DB schema for discovery runs

```bash
npm run polymarket:discovery-migrate
```

This runs the schema from `server/src/polymarket/infra/db/schemas.sql` via `DATABASE_URL`.

## Available Scripts

### Top-level

- `npm run dev` — run API and client in development mode
- `npm run build` — build both server and client
- `npm run start` — run API server only
- `npm run test` — run unit/service tests
- `npm run polymarket:market-channels` — run Polymarket discovery CLI
- `npm run polymarket:discovery-migrate` — apply discovery run schema in Postgres

### Server scripts

- `npm run --workspace server test` — run server tests only
- `npm run --workspace server test:integration` — run optional integration test against real Postgres/Redis
- `npm run --workspace server build` — compile server
- `npm run --workspace server discovery:migrate-runs` — apply schema via ts-node

## Build

```bash
npm run build
```

Build output:
- `server/dist`
- `client/dist`

## Test

```bash
npm run test
```

Run unit/service tests only:

```bash
npm run --workspace server test
```

Run integration test (requires `DATABASE_URL`, `REDIS_URL`, and `DISCOVERY_INTEGRATION_TESTS=1`):

```bash
DISCOVERY_INTEGRATION_TESTS=1 \
  DATABASE_URL=postgres://postgres:postgres@localhost:5432/alphadb \
  REDIS_URL=redis://localhost:6379 \
  npm run --workspace server test:integration
```

## Polymarket discovery API

Discovery now uses **async run orchestration** with compatibility legacy wrapper.

### Primary async endpoints

- `POST /api/polymarket/market-channels/runs`
  - Creates or attaches to a dedupe'd run.
  - Returns shell payload immediately with `runId` + polling URL.

```bash
curl -X POST http://localhost:4000/api/polymarket/market-channels/runs \
  -H "Content-Type: application/json" \
  -d '{"chainId":137}'
```

- `GET /api/polymarket/market-channels/runs/{runId}?offset=0&limit=200`
  - Full status + paginated channels + optional ws scan summary.

- `GET /api/polymarket/market-channels/runs/latest`
  - Returns latest run for the configured scope.

Compatibility wrapper:

- `GET /api/polymarket/market-channels`
  - Keeps old shape via dedupe-aware compatibility shell.
  - Defaults to `202` with shell when run is active.
  - `waitMs` can be used to block briefly and return terminal payload.

Query params on discovery requests:

- `clobApiUrl` (optional): default `https://clob.polymarket.com`
- `chainId` (optional): default `137`
- `wsUrl` (optional): enables websocket probing when present
- `wsConnectTimeoutMs` (optional): default `12000`
- `wsChunkSize` (optional): default `500`
- `marketFetchTimeoutMs` (optional): default `15000`

Example status polling flow:

```bash
# create
RUN_ID=$(curl -s -X POST http://localhost:4000/api/polymarket/market-channels/runs \
  -H 'Content-Type: application/json' -d '{"chainId":137}' | jq -r '.runId')

# poll
curl http://localhost:4000/api/polymarket/market-channels/runs/$RUN_ID
```

Example response shape:

```json
{
  "run": {
    "id": "run_...",
    "status": "succeeded",
    "source": {
      "clobApiUrl": "https://clob.polymarket.com",
      "chainId": 137
    },
    "marketCount": 0,
    "marketChannelCount": 0
  },
  "channels": {
    "items": [],
    "page": {
      "offset": 0,
      "limit": 200,
      "total": 0,
      "hasMore": false
    }
  },
  "wsScan": null
}
```

## CLI usage

```bash
# REST-only run
npm run polymarket:market-channels

# REST + JSON output for scripting/automation
npm run polymarket:market-channels -- --json
```

## Environment variables

- Core discovery config:
  - `CLOB_API_URL` (default: `https://clob.polymarket.com`)
  - `CHAIN_ID` (default: `137`)
  - `WS_URL` (optional)
  - `WS_CONNECT_TIMEOUT_MS` (default: `12000`)
  - `WS_CHUNK_SIZE` (default: `500`)
  - `MARKET_FETCH_TIMEOUT_MS` (default: `15000`)
  - `MARKET_DISCOVERY_CONCURRENCY_LIMIT` (default: `4`)

- Run orchestration:
  - `DATABASE_URL` (required for run persistence)
  - `REDIS_URL` (required for distributed dedupe/locks)
  - `DISCOVERY_SCOPE` (default: `default`)
  - `DISCOVERY_RUN_TTL_SECONDS` (default: `86400`)
  - `DISCOVERY_RUN_CACHE_TTL_SECONDS` (default: `600`)
  - `DISCOVERY_SEMAPHORE_TTL_SECONDS` (default: `60`)
  - `DISCOVERY_RUN_ALLOW_IN_MEMORY_CACHE` (`1` to allow local fallback)
  - `DISCOVERY_RUN_PRUNER_ENABLED` (`1` to enable automatic stale run prune)
  - `DISCOVERY_PRUNE_INTERVAL_SECONDS` (default: `300`)

- Postgres connection pool tuning:
  - `PG_POOL_MAX` (default: `5`)
  - `PG_POOL_IDLE_TIMEOUT_MS` (default: `30000`)
  - `PG_POOL_CONNECT_TIMEOUT_MS` (default: `2000`)

- For integration checks:
  - `DISCOVERY_INTEGRATION_TESTS=1`

## Error contract

Discovery errors are returned as structured JSON with:

- `error`
- `code`
- `message`
- `retryable`
- `details`
- `requestId`

Common codes:

- `invalid_input` (`400`)
- `clob_request_timeout` (`504`)
- `clob_request_network` (`502`)
- `clob_request_failure` (`502`)
- `discovery_concurrency_limit` (`429`, retryable)
- `websocket_invalid_url` (`400`)
- `websocket_request_error` (`502`)
- `run_not_found` (`404`)
- `unexpected_error` (`500`)

## Architecture reference

- `server/src/polymarket/services/` — orchestration and run lifecycle
- `server/src/polymarket/controllers/` — HTTP endpoint surface
- `server/src/polymarket/repositories/` — DB persistence adapters
- `server/src/polymarket/infra/` — DB/cache/queue wiring
- `server/src/polymarket/maintenance/` — migrations and ops scripts
- `server/src/polymarket/cli/` — CLI entrypoint and rendering
- `server/src/polymarket/utils.ts` — parsing and traversal helpers
- `server/src/polymarket/errors.ts` — centralized error mapping
- `docs/polymarket/` — implementation notes and diagrams

## Frontend path (ready for wiring)

A Vite React frontend is already scaffolded and wired against the `/api/*` proxy. Use it as a consumer surface for the discovery API when you're ready to build the UI layer.
