# Phase 2 Productionization Baseline

- Status: In Progress
- Date: 2026-03-09

This plan starts after repository convergence is complete.

## Goal

Make the backend the production-grade control plane for client identity, user state, and runtime observability without regressing the current TUI UX.

## Scope

In scope:

- backend-backed authentication with explicit user identity
- TUI support for authenticated backend access
- observability baseline for API, cache, and stream health
- provider package extraction when boundaries are stable

Out of scope:

- execution or trading
- full alerting product
- strong cross-provider market identity claims

## Workstreams

### 1. Auth Baseline

Deliverables:

- backend auth mode configuration
- explicit viewer identity resolution
- typed auth status endpoint
- TUI/backend SDK support for authenticated requests

Acceptance criteria:

- user-state endpoints are no longer implicitly tied to `local-user`
- the TUI can authenticate with one backend token configuration path
- backend mode degrades cleanly when auth is required but missing

### 2. Observability Baseline

Deliverables:

- structured request logging
- provider and stream health metrics
- cache hit/miss visibility
- readiness and degraded-state visibility

Acceptance criteria:

- stream failures and provider failures are measurable
- operators can distinguish auth problems from provider problems

### 3. Provider Package Extraction

Deliverables:

- create `packages/providers`
- move provider runtime normalization there
- keep app-local rendering and route code outside the package

Acceptance criteria:

- API and TUI compile against shared provider boundaries
- provider normalization logic is no longer duplicated across app layers

### 4. User-State Schema Hardening

Deliverables:

- evaluate when JSONB snapshot storage should become relational tables
- preserve current product behavior during any storage migration

Acceptance criteria:

- migration path is explicit before analytics or richer preferences depend on it

## Recommended Sequence

1. Ship the auth baseline.
2. Add observability for auth, cache, and stream behavior.
3. Extract `packages/providers`.
4. Revisit relational user-state design once the authenticated product shape settles.
