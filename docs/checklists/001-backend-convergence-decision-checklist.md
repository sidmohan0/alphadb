# Backend Convergence Decision Checklist

- Status: Accepted
- Date: 2026-03-09

This checklist turns the current open questions into ordered product and architecture decisions for converging the ANSI TUI with a production backend service.

The intent is not to answer everything at once. The intent is to decide the right things in the right order.

Accepted on 2026-03-09:

- all recommended defaults in this document
- all recommended answers in Phases 0 through 7
- the immediate decision order
- the suggested first implementation sequence

## Recommended Defaults

Unless there is a strong reason to do otherwise, the recommended defaults are:

- make `ts-v1` the structural base monorepo
- move the TUI into that monorepo as `apps/tui`
- keep separate deployable apps for `api`, `web`, and `tui`
- make the backend the production source for trending, search, history, and user state
- keep direct provider access only as a dev or emergency fallback
- design for multi-tenant boundaries even if first deployment is effectively single-user
- use Postgres and Redis as the initial production data plane
- ship backend-powered read APIs before auth-heavy or alert-heavy features

## Phase 0: Product Direction

These decisions should be made first. Everything else depends on them.

1. Define the product center of gravity.
Recommended answer:
AlphaDB is a prediction-market platform with multiple clients. The TUI is a premium client, not the whole product.

2. Define the merge target.
Recommended answer:
Use `ts-v1` as the merge base because it already has the backend and operational skeleton needed for production.

3. Define the first meaningful integrated milestone.
Recommended answer:
The TUI consumes backend-powered trending, search, and chart history while preserving current UX quality.

4. Define what is explicitly out of scope for the first integrated release.
Recommended answer:
No portfolios, no execution/trading, no collaborative workspaces, no full cross-provider “same market” claims, no advanced alerting.

## Phase 1: Repository And Runtime Shape

These decisions unblock the first engineering merge.

5. Approve the target repo topology.
Recommended answer:

```text
apps/api
apps/web
apps/tui
packages/domain
packages/providers
packages/search
packages/sdk
packages/config
infra
docs
```

6. Decide package boundaries.
Recommended answer:
- `packages/domain`: canonical types and contracts
- `packages/providers`: normalization and provider adapters
- `packages/sdk`: typed API client for web and TUI
- app-specific rendering and route code stays app-local

7. Decide whether direct-provider mode remains in the TUI during migration.
Recommended answer:
Yes, but only behind an explicit config flag and not as the default production path.

8. Decide how the TUI is released.
Recommended answer:
The TUI remains independently buildable and releasable, but production data mode points at the backend service.

## Phase 2: Domain And Data Model

These decisions prevent later schema and API churn.

9. Approve the canonical market domain model.
Recommended answer:
Introduce canonical `Market`, `Outcome`, `Quote`, `Trade`, `Candle`, `Event`, and provider mapping entities with raw payload traceability.

10. Decide how cross-provider relationships work.
Recommended answer:
Model “comparable” or “linked” markets separately from identity. Do not claim two markets are the same unless there is explicit confidence logic or manual curation.

11. Decide what data must be normalized versus stored raw.
Recommended answer:
Normalize data needed for search, charts, and comparison. Store raw provider payloads for debugging, replay, and future model changes.

12. Decide retention classes.
Recommended answer:
- user state: durable
- normalized candles: durable with resolution-based retention
- run events: durable with audit TTL policy
- raw event streams: short retention unless needed for replay

## Phase 3: Backend Product Contract

These decisions define what clients actually consume.

13. Decide the first backend read APIs.
Recommended answer:
- trending markets
- search
- market detail
- chart history
- saved markets
- recents

14. Decide whether discovery-run APIs are user-facing in the TUI.
Recommended answer:
Not in the first integrated milestone. Keep them as backend/operator or advanced power-user capabilities first.

15. Decide the query serving model.
Recommended answer:
Serve query APIs from backend-owned normalized and cached data, not by proxying provider search/live responses directly.

16. Decide the internal client contract.
Recommended answer:
Use a typed SDK package consumed by both web and TUI. Do not let each client hand-roll endpoint contracts.

## Phase 4: Search And Ranking

These decisions matter once backend reads exist.

17. Decide whether search is unified across providers.
Recommended answer:
Yes. One search API, one ranking contract, provider-specific boosts only as ranking features.

18. Decide the ranking priorities.
Recommended answer:
Text relevance first, then liquidity/activity, then freshness, then user affinity, then provider confidence.

19. Decide whether provider-native search remains in production.
Recommended answer:
No, except as a fallback/bootstrap input to backend indexing.

20. Decide whether personalized ranking is in scope for v1.
Recommended answer:
Lightweight personalization only: saved/recent/watchlist boosts. Avoid full recommender complexity at first.

## Phase 5: Realtime And Freshness

These decisions affect ingestion and client behavior.

21. Decide the live delivery mechanism.
Recommended answer:
Backend-managed websocket as primary, with polling-capable pull APIs as correctness fallback.

22. Decide what the TUI subscribes to.
Recommended answer:
Selected markets, visible watchlist items, and current split-view selections. Avoid broad “subscribe to everything” behavior.

23. Decide the source of truth after missed live events.
Recommended answer:
Pull APIs are always the correctness path after reconnect or lag.

24. Decide connector obligations.
Recommended answer:
Every provider connector must support reconnect, backoff, health metrics, and normalization versioning.

## Phase 6: User State, Auth, And Tenancy

These decisions should be made before backend-backed watchlists ship.

25. Decide when auth enters the product.
Recommended answer:
Before backend-backed persistent user state becomes the default.

26. Decide the TUI auth flow.
Recommended answer:
Device code flow or personal access token. Avoid browser-cookie assumptions.

27. Decide tenancy posture.
Recommended answer:
Build explicit tenant boundaries from the start even if only one user exists initially.

28. Decide what user state becomes backend-authoritative.
Recommended answer:
Saved markets, recents, saved searches, alerts, and layout preferences.

## Phase 7: Operations And Production Readiness

These decisions are required before calling the service production-grade.

29. Define service-level goals.
Recommended answer:
Set targets for API latency, search freshness, chart freshness, live-update lag, and degraded-mode behavior.

30. Define observability minimums.
Recommended answer:
- structured logs
- metrics
- alerting
- health/readiness endpoints
- dashboards for provider lag, cache hit rate, worker backlog, and DB pressure

31. Define release controls.
Recommended answer:
- CI for each app and package
- contract tests for SDK/API compatibility
- explicit migrations
- staging environment with realistic topology

32. Define failure modes and graceful degradation.
Recommended answer:
If providers fail, stale-but-labeled cached reads are preferable to a dead UI when feasible. Clients should surface degraded state clearly.

## Immediate Decision Order

If you want the minimum set to unblock real work, decide these next:

1. AlphaDB product center of gravity
2. `ts-v1` as merge base or not
3. first integrated milestone
4. repo topology
5. canonical domain model scope
6. first backend read APIs
7. direct-mode migration policy
8. auth entry point
9. tenancy posture
10. observability minimums

## Suggested First Implementation Sequence

Once the first ten decisions are accepted, the recommended implementation order is:

1. create the merged monorepo structure
2. move the TUI into `apps/tui`
3. extract shared domain and provider packages
4. build backend trending/search/history endpoints
5. add a typed SDK
6. put the TUI behind a backend-read feature flag
7. migrate saved and recent state to backend ownership
8. add auth for TUI and web
9. add live subscriptions
10. retire provider-direct production mode

## Escalation Questions

If any of these answers change, re-open the ADR set:

- the product becomes TUI-only again
- the backend is not intended to own user state
- you want cross-provider equivalence as a first-class product claim
- you want trading/execution in scope
- you want multi-user collaboration in the near term
