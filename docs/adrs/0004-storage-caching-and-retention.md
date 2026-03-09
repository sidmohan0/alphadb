# ADR 0004: Storage, Caching, And Retention

- Status: Accepted
- Date: 2026-03-09

## Context

The backend needs to support:

- transactional state
- run orchestration
- user state
- normalized market metadata
- chart/history retrieval
- low-latency caches

The current `ts-v1` branch already assumes Postgres and Redis. The production design should extend that rather than replace it casually.

## Decision

Use Postgres as the primary system of record and Redis as the low-latency cache/coordination layer.

Postgres stores:

- users and organizations
- watchlists, recents, saved searches, alert rules
- provider markets and normalized markets
- discovery runs and audit events
- normalized candles at bounded resolutions
- mapping tables and enrichment metadata

Redis stores:

- request/result caches
- hot trending/search result sets
- locks, dedupe keys, and worker coordination
- short-lived live quote fanout state

Retention policy:

- raw ingestion payloads: short retention or object storage handoff
- normalized candles: retained by resolution and TTL
- discovery run events: retained for operations and audit
- user state: retained until explicit deletion or policy expiry

## Consequences

Positive:

- aligns with the current backend branch
- minimizes new infrastructure classes
- supports both transactional and operational workloads

Negative:

- very high-frequency history may eventually exceed comfortable plain-Postgres patterns
- retention and compaction policies must be explicit from day one

## Notes

If historical volume materially outgrows Postgres, move raw market event history to object storage or a columnar system without changing the client contract.
