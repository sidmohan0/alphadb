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

On error, the endpoint returns HTTP `502` with:

```json
{
  "error": "Failed to discover market channels",
  "details": "..."
}
```

## Test coverage added

- Added integration tests at `server/test/polymarket.controller.test.ts`.
- Tests validate:
  - service invocation + response mapping
  - default values when query params are omitted
  - websocket query params are passed through correctly
  - error propagation as 502

Run tests with:

```bash
npm run test
```

## Notes

- `call graph` is the right structural term for these diagrams.
- `stack trace` refers to runtime failure stack, not full-file architecture.
- This split is not purely controller logic; it is a service/CLI/controller structured API-ready architecture.
