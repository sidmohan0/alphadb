# ADR 0002: Client And Backend Contract

- Status: Accepted
- Date: 2026-03-09

## Context

Today the TUI talks directly to public provider APIs. That keeps latency low and removes infrastructure dependencies, but it limits richer features:

- cross-device saved state
- indexed search
- alerting
- server-side caching
- multi-step discovery jobs
- policy/rate-limit control

We want the TUI to eventually consume a backend service without losing local responsiveness.

## Decision

The production contract will be backend-first for enriched features, with optional direct-provider fallback reserved for local development and emergency degradation.

The backend will expose:

- market list and search APIs
- normalized chart/history APIs
- watchlist and recent-state APIs
- discovery job APIs
- websocket or SSE live update channels

The TUI will depend on a typed internal SDK instead of calling backend endpoints ad hoc.

API shape:

- synchronous query APIs for trending/search/history
- asynchronous job APIs for expensive scans and enrichment
- realtime subscription APIs for selected-market and watchlist updates

## Consequences

Positive:

- one authoritative data contract for all clients
- room for caching, policy, auth, and analytics
- direct path from `ts-v1` discovery infrastructure to the TUI

Negative:

- backend becomes a critical dependency in production
- more operational work than direct public API access

## Notes

Fallback mode should remain intentionally limited. Production UX should assume the service exists.
