# Polymarket Market Channel Discovery — Implementation Notes

## What this report covers

This folder includes the two diagrams produced during the Polymarket Market Channel work:

- `polymarket-market-channels-visual-plan-diagram.html`
  - A full visual plan + topology/flow diagram for the discovery script.
- `polymarket-market-channels-call-graph.html`
  - A call graph / call hierarchy for the same file structure.

Open these files in a browser for the rendered Mermaid diagrams.

## Current backend structure (post-refactor)

The discovery feature is now structured as:

- `server/src/polymarket/types.ts`
  - Shared types, DTO contracts, constants.
- `server/src/polymarket/utils.ts`
  - Shared parsing and extraction helpers.
- `server/src/polymarket/services/marketChannelDiscoveryService.ts`
  - Service orchestration for REST + optional websocket probing.
- `server/src/polymarket/cli/runMarketChannels.ts`
  - CLI entry logic (args/env + result rendering).
- `server/src/polymarket/controllers/polymarket.controller.ts`
  - HTTP controller (`GET /api/polymarket/market-channels`).
- `server/src/app.ts`
  - Express app factory (`createApp`) for runtime + testability.
- `server/src/polymarketMarketChannels.ts`
  - Thin CLI bootstrap wrapper that invokes the CLI entry and handles terminal failure.

## API behavior

`GET /api/polymarket/market-channels` now maps request query params into the same domain config used by CLI/service:

- `clobApiUrl` (default: `https://clob.polymarket.com`)
- `chainId` (default: `137`)
- `wsUrl` (optional)
- `wsConnectTimeoutMs` (default: `12000`)
- `wsChunkSize` (default: `500`)
- `marketFetchTimeoutMs` (default: `15000`)

On error, the endpoint maps structured error codes and status codes to descriptive JSON (for example):

```json
{
  "error": "Failed to discover market channels",
  "code": "clob_request_network",
  "message": "Clob request failed with code ENOTFOUND",
  "retryable": true,
  "details": {
    "component": "clob",
    "status": 502
  },
  "requestId": "..."
}
```

The service keeps empty states explicit:

- `channels: []` when no markets or asset IDs are discovered
- `wsScan: null` when websocket probe is not requested
- `source.marketChannelCount` mirrors `channels.length`

### Concurrency and de-duplication behavior

In-memory request coalescing is now used for concurrent identical discovery requests. If the same request payload arrives while the same discovery run is in flight, callers receive the same Promise instead of duplicate upstream calls.

## Test coverage added

- Added integration tests at `server/test/polymarket.controller.test.ts`.
- Added service unit tests at `server/test/polymarket.discovery.service.test.ts`.
- Tests validate:
  - service invocation + response mapping
  - default values when query params are omitted
  - websocket query params are passed through correctly
  - empty-state response behavior
  - concurrent dedupe for identical service calls
  - error response mapping

Run tests with:

```bash
npm run test
```

## Notes

- `call graph` is the right structural term for these diagrams.
- `stack trace` refers to runtime failure stack, not full-file architecture.
- This split is not purely controller logic; it is a service/CLI/controller structured API-ready architecture.
