# TypeScript Full-Stack Boilerplate

This is a minimal full-stack setup with:
- **Backend**: Express + TypeScript (`/server`)
- **Frontend**: React + TypeScript + Vite (`/client`)

## Prerequisites
- Node.js 18+
- npm 9+

## Install

```bash
npm install
```

## Development

Run both apps at once:

```bash
npm run dev
```

- Frontend: http://localhost:5173
- Backend: http://localhost:4000

The Vite dev server proxies `/api/*` requests to the backend.

## Build

```bash
npm run build
```

Build both projects (`server/dist` and `client/dist`).

## Test

```bash
npm run test
```

Runs server integration tests.

## Polymarket market channel discovery (WebSocket)

This repo now includes a refactored discovery flow with explicit layers:
- `server/src/polymarket/services/...` for orchestration and extraction
- `server/src/polymarket/cli/runMarketChannels.ts` for command parsing + terminal rendering
- `server/src/polymarket/utils.ts` for shared parsing/payload helpers

The command still does:
1. Pull all markets from Polymarket CLOB REST (`/markets`)
2. Extract every unique market channel (`asset_id` / `token_id`) from those markets
3. Optionally connect to the market websocket stream and capture observed channel IDs

You can also call the same flow through HTTP:

```bash
GET /api/polymarket/market-channels
```

Query params:
- `clobApiUrl` (optional): override endpoint (defaults to `https://clob.polymarket.com`)
- `chainId` (optional): override chain ID (defaults `137`)
- `wsUrl` (optional): when set, triggers websocket probing for this session
- `wsConnectTimeoutMs` (optional): default `12000`
- `wsChunkSize` (optional): default `500`
- `marketFetchTimeoutMs` (optional): default `15000` per page

Example:

```bash
curl "http://localhost:4000/api/polymarket/market-channels?chainId=137"
```

```bash
# Discover channels via REST only (set WS_URL for websocket probe)
npm run polymarket:market-channels

# JSON output (good for scripting)
npm run polymarket:market-channels -- --json
```

Environment variables:
- `CLOB_API_URL` (default: `https://clob.polymarket.com`)
- `CHAIN_ID` (default: `137`)
- `WS_URL` (optional; websocket host, e.g. `wss://.../ws`)
- `WS_CONNECT_TIMEOUT_MS` (default: `12000`)
- `WS_CHUNK_SIZE` (default: `500`)
- `MARKET_FETCH_TIMEOUT_MS` (default: `15000`)
