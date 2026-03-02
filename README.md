# Polymarket Discovery Service (TypeScript Monorepo)

A production-oriented TypeScript starter that now focuses on **Polymarket market-channel discovery** with:

- a layered backend architecture (service / controller / CLI)
- resilient REST + websocket orchestration
- explicit empty-state handling
- structured error contracts and rich failure payloads
- request-level concurrency protections
- end-to-end API integration and docs

The repo also includes a lightweight full-stack shell (Express + React/Vite) so the service can be consumed locally from a frontend with minimal extra wiring.

## Highlights

- **Modular backend** in `server/` with a dedicated `polymarket` domain module
- **REST + websocket discovery** path for extracting Polymarket `assetId` channels
- **Query parsing + validation** in API controller
- **Typed error mapping** with stable response codes and retry hints
- **In-flight dedupe** for identical concurrent discovery requests
- **Concurrency ceiling** for unique discovery runs (defaults to 4)
- **Tests first**: controller + service coverage for success, error, empty, and saturation cases

## Prerequisites

- Node.js 18+
- npm 9+

## Quick Setup (Local)

```bash
git clone https://github.com/sidmohan0/alphadb.git
cd alphadb
npm install
```

From the repo root, run both apps in parallel:

```bash
npm run dev
```

- Frontend: `http://localhost:5173`
- Backend/API: `http://localhost:4000`

The Vite dev server proxies `/api/*` requests to the backend.

## Available Scripts

### Top-level

- `npm run dev` — run API and client in development mode
- `npm run build` — build both server and client
- `npm run start` — run API server only
- `npm run test` — run server integration/unit tests
- `npm run polymarket:market-channels` — run Polymarket discovery CLI

### Server scripts

- `npm run --workspace server test` — run server tests only
- `npm run --workspace server build` — compile server

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

Runs server integration tests (including Polymarket controller/service scenarios).

## Polymarket discovery API

Use the same discovery flow through HTTP:

```bash
GET /api/polymarket/market-channels
```

Query params:

- `clobApiUrl` (optional): override endpoint (defaults to `https://clob.polymarket.com`)
- `chainId` (optional): override chain ID (defaults `137`)
- `wsUrl` (optional): enables websocket probing when present
- `wsConnectTimeoutMs` (optional): default `12000`
- `wsChunkSize` (optional): default `500`
- `marketFetchTimeoutMs` (optional): default `15000`

Example:

```bash
curl "http://localhost:4000/api/polymarket/market-channels?chainId=137"
```

### Example response shape

```json
{
  "source": {
    "clobApiUrl": "https://clob.polymarket.com",
    "chainId": 137,
    "marketCount": 0,
    "marketChannelCount": 0
  },
  "channels": [],
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

### CLI/env configuration

- `CLOB_API_URL` (default: `https://clob.polymarket.com`)
- `CHAIN_ID` (default: `137`)
- `WS_URL` (optional websocket host, e.g. `wss://.../ws`)
- `WS_CONNECT_TIMEOUT_MS` (default: `12000`)
- `WS_CHUNK_SIZE` (default: `500`)
- `MARKET_FETCH_TIMEOUT_MS` (default: `15000`)
- `MARKET_DISCOVERY_CONCURRENCY_LIMIT` (default: `4`)

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
- `unexpected_error` (`500`)

## Architecture reference

- `server/src/polymarket/services/` — orchestration and extraction logic
- `server/src/polymarket/controllers/` — HTTP endpoint
- `server/src/polymarket/cli/` — CLI entrypoint and rendering
- `server/src/polymarket/utils.ts` — parsing and traversal helpers
- `server/src/polymarket/errors.ts` — centralized error mapping
- `docs/polymarket/` — generated visuals and implementation notes

## Frontend path (ready for wiring)

A Vite React frontend is already scaffolded and wired against the `/api/*` proxy. Use it as a consumer surface for the discovery API when you're ready to build the UI layer.
