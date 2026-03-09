# ADR 0008: Observability, SRE, And Release Discipline

- Status: Accepted
- Date: 2026-03-09

## Context

The merged system will include clients, backend APIs, workers, provider connectors, caching, and persistent storage. Production quality depends as much on operations as code structure.

## Decision

Treat observability and release controls as first-order architecture, not post-launch cleanup.

Required capabilities:

- structured logs with request and run correlation IDs
- metrics for API latency, cache hit rate, provider lag, worker backlog, and live subscription counts
- tracing across API, worker, and provider boundaries where practical
- health/readiness endpoints for API and workers
- dashboards and alerts for provider failures, job backlog, cache saturation, and DB pressure

Release policy:

- every app/package builds independently in CI
- migrations are explicit and reversible where possible
- contract tests guard the shared SDK and canonical model
- staging environment mirrors production topology closely enough to exercise live flows

Reliability targets:

- graceful degradation when provider APIs fail
- bounded retries with clear dead-letter handling
- idempotent job orchestration
- explicit rate-limit and circuit-breaker policy

## Consequences

Positive:

- production incidents become diagnosable
- client regressions surface before deployment
- backend confidence grows as features expand

Negative:

- higher initial delivery cost
- more non-feature engineering work in the roadmap

## Notes

The current TUI standard of “bootable and usable” should remain, but production success will depend on service-level telemetry and runbooks.
