# Polymarket Market Channel Discovery — Implementation Notes

## What this report covers

This folder now includes the artifacts for the discovery work and the async run architecture:

- `polymarket-market-channels-visual-plan-diagram.html`
  - A full visual plan + topology/flow diagram for the discovery script.
- `polymarket-market-channels-call-graph.html`
  - A call graph / call hierarchy for the same file structure.
- `polymarket-discovery-runs-visual-plan.html`
  - Architecture and endpoint model for async `discovery_runs` + Postgres/Redis orchestration.

Open these files in a browser for rendered visuals.

## Current backend structure (post-refactor)

The discovery feature now follows a layered async run model:

- `server/src/polymarket/types.ts`
  - Shared types, DTO contracts, and constants.
- `server/src/polymarket/utils.ts`
  - Shared parsing and extraction helpers.
- `server/src/polymarket/services/marketChannelDiscoveryService.ts`
  - Domain discovery orchestration for REST + optional websocket probing.
- `server/src/polymarket/services/discoveryRunService.ts`
  - Async run orchestration (queue/running/terminal states, paging, and compatibility shell behavior).
- `server/src/polymarket/controllers/polymarket.controller.ts`
  - HTTP controller for async APIs + backward-compatible `/market-channels`.
- `server/src/app.ts`
  - Express app factory (`createApp`) for runtime + testability.
- `server/src/polymarket/cli/runMarketChannels.ts`
  - CLI entry logic (args/env + result rendering).
- `server/src/polymarket/errors.ts`
  - Centralized typed error mapping and API response contracts.
- `server/src/polymarketMarketChannels.ts`
  - Thin CLI bootstrap wrapper that invokes the CLI entry and handles terminal failure.
- `server/src/polymarket/infra`
  - DB/Redis infra scaffolding and shared connection utilities.
- `server/src/polymarket/repositories`
  - DB persistence adapters for runs, channels, and websocket scan metadata.

## API behavior

Primary async discovery run APIs:

- `POST /api/polymarket/market-channels/runs` (dedupe + queued return)
- `GET /api/polymarket/market-channels/runs/{runId}`
- `GET /api/polymarket/market-channels/runs/latest`

Compatibility path:

- `GET /api/polymarket/market-channels`
  - Returns shell (`202`) when still queued/running.
  - Returns terminal payload (`200`) after `waitMs` if run finishes in time.

Query params on discovery requests:

- `clobApiUrl` (default: `https://clob.polymarket.com`)
- `chainId` (default: `137`)
- `wsUrl` (optional)
- `wsConnectTimeoutMs` (default: `12000`)
- `wsChunkSize` (default: `500`)
- `marketFetchTimeoutMs` (default: `15000`)
- `waitMs` (compatibility timeout in ms, optional)
- `offset` / `limit` for paginated run reads

On error, endpoints return structured error contracts from `server/src/polymarket/errors.ts`.

Example error payload:

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

Common codes:

- `invalid_input` (`400`)
- `clob_request_timeout` (`504`)
- `clob_request_network` (`502`)
- `clob_request_failure` (`502`)
- `discovery_concurrency_limit` (`429`, `retryable: true`)
- `websocket_invalid_url` (`400`) — only when probe URL parsing fails
- `websocket_request_error` (`502`)
- `run_not_found` (`404`)
- `unexpected_error` (`500`)

The service keeps empty states explicit:

- `channels: []` when no markets or asset IDs are discovered
- `wsScan: null` when websocket probe is not requested
- `source.marketChannelCount` mirrors `channels.length`

### Concurrency and de-duplication behavior

- In-memory/Redis-assisted dedupe is used for identical in-flight discovery requests.
- Hard concurrency ceiling is applied for queued unique discovery runs (default `4`, via `MARKET_DISCOVERY_CONCURRENCY_LIMIT`).
- Requests above the limit fail immediately with:
  - HTTP `429`
  - `code: discovery_concurrency_limit`

## Test coverage added

- Added integration tests at `server/test/polymarket.controller.test.ts`.
- Added service unit tests at:
  - `server/test/polymarket.discovery.service.test.ts`
  - `server/test/polymarket.discoveryRunService.test.ts`

Run tests with:

```bash
npm run test
```

## Notes

- `call graph` is the right structural term for these diagrams.
- `stack trace` refers to runtime failure stack, not full-file architecture.
- This split is intentionally service/CLI/controller oriented rather than controller-only.
