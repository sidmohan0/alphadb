# Polymarket Discovery Service (TypeScript Monorepo)

A production-oriented TypeScript starter that focuses on **Polymarket market-channel discovery** with:

- a layered backend architecture (controller / service / infra)
- REST + websocket discovery orchestration
- explicit empty-state handling
- structured error contracts and retry hints
- distributed dedupe/concurrency protections
- Postgres + Redis-backed async run persistence and polling

The repo also includes a lightweight full-stack shell (Express + React/Vite) so the service can be consumed locally from a frontend with minimal extra wiring.

## Highlights

- **Modular backend** in `server/` with a dedicated `polymarket` domain module
- **Async run lifecycle** with polling and latest-run bootstrap APIs
- **Query parsing + validation** in controller layer
- **Typed error mapping** with stable response codes
- **Distributed in-flight dedupe** for identical request configs
- **Concurrency ceiling** for unique discovery runs (default `4`)
- **Postgres connection pooling** via `PG_POOL_MAX`, etc.
- **Run-pruning scheduler** for stale run cleanup
- **Optional integration tests** using real Postgres + Redis

---

## Local setup (recommended)

### 0) Prereqs

- Node.js 18+
- npm 9+

### 1) Clone and install

```bash
git clone https://github.com/sidmohan0/alphadb.git
cd alphadb
npm install
```

### 2) Start local dependencies

Start the included stack (Postgres + Redis):

```bash
docker-compose -f docker-compose.discovery-stack.yml up -d
```

This starts:

- Postgres on `localhost:5432`
- Redis on `localhost:6379`

Verify they are healthy before continuing:

```bash
docker compose -f docker-compose.discovery-stack.yml ps
```

### 3) Configure environment

A starter `.env.example` is included:

```bash
cp .env.example .env
```

Load it in your shell for local sessions:

```bash
set -a
. ./.env
set +a
```

For fresh environments, you can run schema bootstrapping automatically by setting:

```bash
export DISCOVERY_REQUIRE_SCHEMA=1
```

This is useful in ephemeral infra (CI, ephemeral VMs). In long-lived environments, apply migrations explicitly as part of deployment.

If you prefer ad-hoc env-only setup, export directly:

```bash
export DATABASE_URL="postgres://postgres:postgres@localhost:5432/alphadb"
export REDIS_URL="redis://localhost:6379"
export DISCOVERY_REQUIRE_SCHEMA=1  # optional
```

### 4) Apply DB schema

```bash
npm run polymarket:discovery-migrate
```

This runs the SQL migration at:
`server/src/polymarket/infra/db/schemas.sql`

### 5) Run the app

```bash
# same terminal, with DATABASE_URL + REDIS_URL set
npm run dev
```

If you want cleanup of stale runs in local dev too, enable pruner:

```bash
DISCOVERY_RUN_PRUNER_ENABLED=1 npm run dev
```

Expected services:

- Frontend: `http://localhost:5173`
- API: `http://localhost:4000`

---

## Useful API smoke checks

After startup:

```bash
# should return a structured run-not-found error (DB is empty initially)
curl -i http://localhost:4000/api/polymarket/market-channels/runs/latest

# start a discovery run (returns shell immediately)
curl -X POST http://localhost:4000/api/polymarket/market-channels/runs \
  -H "Content-Type: application/json" \
  -d '{"chainId":137}'

# or compatibility endpoint (default is compatibility shell + polling)
curl "http://localhost:4000/api/polymarket/market-channels?chainId=137&waitMs=0"
```

---

## Scripts

### Top-level

- `npm run dev` — run API and client in development mode
- `npm run build` — build both server and client
- `npm run start` — run API server only
- `npm run test` — run unit/service tests
- `npm run polymarket:market-channels` — run Polymarket discovery CLI
- `npm run polymarket:discovery-migrate` — apply discovery run schema in Postgres
- `npm run polymarket:discovery-schema` — run idempotent discovery schema bootstrapping/version check (without applying runtime-specific defaults)

### Server scripts

- `npm run --workspace server test` — run server tests only
- `npm run --workspace server test:integration` — optional integration run against real Postgres/Redis
- `npm run --workspace server build` — compile server
- `npm run --workspace server discovery:ensure-schema` — bootstrap/ensure schema version table and current DDL via ts-node
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

Run integration tests (requires `DATABASE_URL`, `REDIS_URL`, and `DISCOVERY_INTEGRATION_TESTS=1`):

```bash
DISCOVERY_INTEGRATION_TESTS=1 \
  DATABASE_URL=postgres://postgres:postgres@localhost:5432/alphadb \
  REDIS_URL=redis://localhost:6379 \
  npm run --workspace server test:integration
```

---

## Polymarket discovery API

Discovery uses async run orchestration with compatibility wrapper.

### Primary async endpoints

- `POST /api/polymarket/market-channels/runs`
  - Creates or attaches to a run.
  - Returns shell payload with `runId` and `pollUrl`.

```bash
curl -X POST http://localhost:4000/api/polymarket/market-channels/runs \
  -H "Content-Type: application/json" \
  -d '{"chainId":137}'
```

- `GET /api/polymarket/market-channels/runs/{runId}?offset=0&limit=200`
  - Returns full run payload + paginated channels.

- `GET /api/polymarket/market-channels/runs/latest`
  - Returns latest run for configured scope.

### Compatibility wrapper

- `GET /api/polymarket/market-channels`
  - preserves legacy shape.
  - `waitMs=0` returns a shell (`202` if active).
  - `waitMs>0` waits briefly and returns terminal payload when ready.

### Query params

- `clobApiUrl` (optional, default `https://clob.polymarket.com`)
- `chainId` (optional, default `137`)
- `wsUrl` (optional): enables websocket probing when present
- `wsConnectTimeoutMs` (optional, default `12000`)
- `wsChunkSize` (optional, default `500`)
- `marketFetchTimeoutMs` (optional, default `15000`)

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

---

## CLI usage

```bash
# REST-only run
npm run polymarket:market-channels

# REST + JSON output for scripting
npm run polymarket:market-channels -- --json
```

## Environment variables

- Core discovery config:
  - `CLOB_API_URL` (default: `https://clob.polymarket.com`)
  - `CHAIN_ID` (default: `137`)
  - `WS_URL` (optional)
  - `WS_CONNECT_TIMEOUT_MS` (default: `12000`)
  - `WS_CHUNK_SIZE` (default: `500`)
  - `MARKET_FETCH_TIMEOUT_MS` (default: `15_000`)
  - `MARKET_DISCOVERY_CONCURRENCY_LIMIT` (default: `4`)

- Run orchestration:
  - `DATABASE_URL` (**required**)
  - `REDIS_URL` (**required**)
  - `DISCOVERY_REQUIRE_SCHEMA` (`1` to validate/apply migration on startup)
  - `DISCOVERY_SCHEMA_TARGET_VERSION` (optional override, default: `1`)  - `DISCOVERY_SCOPE` (default: `default`)
  - `DISCOVERY_RUN_TTL_SECONDS` (default: `86400`)
  - `DISCOVERY_RUN_CACHE_TTL_SECONDS` (default: `600`)
  - `DISCOVERY_SEMAPHORE_TTL_SECONDS` (default: `60`)
  - `DISCOVERY_RUN_ALLOW_IN_MEMORY_CACHE` (`1` to allow local fallback; single-process only)
  - `DISCOVERY_RUN_PRUNER_ENABLED` (`1` to enable automatic stale-run pruning)
  - `DISCOVERY_PRUNE_INTERVAL_SECONDS` (default: `300`)

- Redis client tuning:
  - `REDIS_CONNECT_TIMEOUT_MS` (default: `2000`)
  - `REDIS_COMMAND_TIMEOUT_MS` (default: `5000`)
  - `REDIS_MAX_RETRIES_PER_REQUEST` (default: `3`)
  - `REDIS_RETRY_BASE_MS` (default: `100`)
  - `REDIS_RETRY_MAX_MS` (default: `2000`)
  - `REDIS_RECONNECT_ON_ERROR` (`1`/`0`, default `1`)

- Postgres pool tuning:
  - `PG_POOL_MAX` (default: `5`)
  - `PG_POOL_IDLE_TIMEOUT_MS` (default: `30000`)
  - `PG_POOL_CONNECT_TIMEOUT_MS` (default: `2000`)

- Integration check toggle:
  - `DISCOVERY_INTEGRATION_TESTS=1`

## Error contract

Discovery errors return JSON with:

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

---

## Architecture reference

- `server/src/polymarket/services/` — orchestration and run lifecycle
- `server/src/polymarket/controllers/` — HTTP endpoint surface
- `server/src/polymarket/repositories/` — DB persistence adapters
- `server/src/polymarket/infra/` — DB/cache/queue wiring
- `server/src/polymarket/maintenance/` — migration + ops scripts
- `server/src/polymarket/cli/` — CLI entrypoint and rendering
- `server/src/polymarket/utils.ts` — parsing and traversal helpers
- `server/src/polymarket/errors.ts` — centralized error mapping
- `docs/polymarket/` — implementation notes and diagrams

## Frontend path (ready for wiring)

A Vite React frontend is already scaffolded and wired against the `/api/*` proxy. Use it as a consumer surface for discovery APIs when you are ready to build the UI layer.
