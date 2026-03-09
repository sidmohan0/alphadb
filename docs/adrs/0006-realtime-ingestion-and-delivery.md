# ADR 0006: Realtime Ingestion And Delivery

- Status: Accepted
- Date: 2026-03-09

## Context

The TUI now supports optional live Kalshi websocket updates. A production system needs a general model for:

- provider ingestion
- normalization
- live fanout to clients
- reconnect, replay, and gap handling

## Decision

Introduce provider-specific ingestion workers and a normalized live-update pipeline.

Pipeline:

1. provider connector receives raw websocket or polling updates
2. connector normalizes into canonical quote/trade/candle events
3. normalized events update Postgres-backed state and Redis-backed hot caches
4. API layer fans live updates to clients through websocket or SSE channels

Delivery model:

- TUI subscribes to selected markets and active watchlists
- web subscribes to page-scoped views
- delivery payloads use canonical event shapes

Operational rules:

- every connector must support reconnect/backoff
- every connector must emit health and lag metrics
- every connector must tolerate temporary provider inconsistency
- live delivery is best-effort for freshness but recoverable via pull APIs

## Consequences

Positive:

- one live architecture for all clients
- provider quirks remain isolated in connectors
- pull APIs remain the source of truth after missed realtime updates

Negative:

- more moving parts than direct client-side websockets
- normalized live semantics must be designed carefully

## Notes

Client UIs should never depend on websocket delivery alone for correctness.
