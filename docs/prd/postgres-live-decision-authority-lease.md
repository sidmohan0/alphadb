# PRD: Postgres Live-Decision Authority Lease

Linear publish status: published as
[ADB-316](https://linear.app/threadfork/issue/ADB-316/prd-postgres-live-decision-authority-lease).

## Problem Statement

The AWS `fair_value_live` worker currently uses an S3 live-run lock as the
singleton authority guard before a live decision cycle can proceed. Real AWS
scheduled-worker manifests from `2026-06-09T22:30Z` to `2026-06-09T23:10Z`
showed 33 live cycles with mean runtime `1.133s`, p95 runtime `1.237s`, and
mean S3 live-run lock time `0.809s`, which was about `71%` of the observed
no-submit hot path.

That is the wrong production-infrastructure shape for a serious trading
control plane. S3 is good for immutable artifacts and audit evidence, but it is
slow and awkward as the source of runtime singleton authority. AlphaDB already
uses Operational State for live runtime config, live risk admission state, live
order attempts, and live status, so live-decision authority should be granted
by the same transactional control plane.

## Solution

Replace the S3 live-run lock in the AWS live hot path with a strategy-scoped
Postgres **Live-decision authority lease** in Operational State.

From the operator's perspective, the live worker should still fail closed when
another worker owns live-decision authority, but the authority check should be
fast, inspectable, transactional, and backed by a fencing token. S3 manifests
should continue to record authority evidence for auditability, but S3 should no
longer be the runtime source of authority.

The implementation should initially target `fair_value_live`, while keeping the
schema and repository strategy-scoped so future live strategies can use the
same authority mechanism.

## User Stories

1. As a live strategy operator, I want each `fair_value_live` cycle to acquire a single live-decision authority lease, so that overlapping workers cannot both act.
2. As a live strategy operator, I want the worker to skip or fail closed when authority cannot be acquired, so that safety beats opportunity.
3. As a live strategy operator, I want authority checks to be faster than the current S3 lock path, so that the one-minute worker spends less time in control-plane waiting.
4. As a live strategy operator, I want the live manifest to record which authority mechanism was used, so that I can audit each run.
5. As a live strategy operator, I want the Cockpit and status payloads to expose current authority state eventually, so that I can diagnose stuck or overlapping workers.
6. As a live strategy operator, I want stale leases to expire cleanly, so that a crashed worker does not permanently block the strategy.
7. As a live strategy operator, I want lease expiry to be explicit in Operational State, so that recovery behavior is inspectable.
8. As a live strategy operator, I want before/after latency evidence, so that the infrastructure improvement is visible and credible.
9. As a live strategy operator, I want the existing live order safety gates preserved, so that replacing the lock does not loosen risk controls.
10. As a live strategy operator, I want S3 artifacts to remain available, so that run evidence and audit trails do not regress.
11. As a platform engineer, I want live-decision authority to live in Operational State, so that authority, config, risk, attempts, and status share one transactional control plane.
12. As a platform engineer, I want an atomic lease acquisition interface, so that competing workers cannot both acquire authority.
13. As a platform engineer, I want each acquired lease to carry a monotonically advancing fencing token, so that stale workers can be rejected after a newer worker takes authority.
14. As a platform engineer, I want authority-bearing writes to carry the fencing token, so that stale writes fail closed.
15. As a platform engineer, I want lease state keyed by strategy, so that `fair_value_live` and future strategies do not block each other.
16. As a platform engineer, I want the lease repository to be a small deep module, so that concurrency behavior can be tested without running the full live strategy.
17. As a platform engineer, I want expired leases to be claimable with one atomic statement, so that recovery does not require manual cleanup.
18. As a platform engineer, I want active unexpired leases to return a structured held result, so that callers can write clear skip evidence.
19. As a platform engineer, I want release to verify the owner and fencing token, so that one worker cannot release another worker's authority.
20. As a platform engineer, I want heartbeat or renewal semantics to be explicit if added, so that lease lifetime is not hidden in incidental writes.
21. As a platform engineer, I want AWS rollout to support a temporary implementation switch, so that the Postgres path can be proven before S3 is removed.
22. As a platform engineer, I want the existing local file lock behavior to remain available for fixture/local runs unless deliberately changed, so that local smoke paths stay simple.
23. As a platform engineer, I want the AWS worker to use Postgres authority when `runtime_config_source=postgres`, so that production-like live authority does not depend on S3.
24. As a platform engineer, I want S3 lock code to remain only as a transitional fallback, so that rollback is available during cutover.
25. As a platform engineer, I want migration tests for the lease table, so that deployment cannot silently miss the authority schema.
26. As a platform engineer, I want race tests for acquire, held, expired, release, and stale-token cases, so that the safety contract is proven.
27. As a runtime maintainer, I want the live worker to stop market collection when authority is held, so that no downstream live path runs without authority.
28. As a runtime maintainer, I want bounded live-risk admission refresh to remain separate from authority acquisition, so that the authority lease does not become a risk ledger.
29. As a runtime maintainer, I want risk reservation and live order attempt writes to validate the acquired authority token, so that stale workers cannot submit or persist attempts.
30. As a runtime maintainer, I want status materialization to record authority denial reasons, so that operators see `live_decision_authority_held` rather than an ambiguous failure.
31. As a runtime maintainer, I want the lease TTL aligned with the one-minute schedule and current worker duration targets, so that normal cycles do not overlap but crashed cycles recover.
32. As a runtime maintainer, I want failed lease acquisition to count as a clean skip, so that monitoring can distinguish expected overlap prevention from runtime errors.
33. As a runtime maintainer, I want the S3 artifact upload to happen after authority-sensitive work, so that artifact latency does not determine authority.
34. As a Cockpit user, I want live operations to show sparse truthful authority status when available, so that I can understand whether a strategy is blocked by another active worker.
35. As an agent, I want the authority state to be queryable from Operational State, so that I can diagnose live runtime latency without scraping S3 lock objects.
36. As a reviewer, I want an ADR documenting why Postgres replaced S3 for live authority, so that the infrastructure trade-off is understandable later.
37. As a reviewer, I want the before/after chart to show the S3 lock contribution disappearing or shrinking, so that the portfolio story is easy to verify.
38. As a reviewer, I want the implementation not to change strategy math, model thresholds, BRTI feature logic, order sizing, or risk caps, so that latency work remains infrastructure-only.

## Implementation Decisions

- Use the canonical term **Live-decision authority lease** for the domain concept. Avoid treating "S3 lock" as the domain term; that is the current implementation.
- Add a Postgres Operational State table for strategy-scoped authority leases. The table should track strategy, current owner id, current run id, fencing token or lease version, acquired timestamp, expiry timestamp, release timestamp/status, and metadata.
- Acquire authority with one atomic database operation. The operation should succeed only when no row exists, the existing lease is expired, or the existing lease has been released.
- Successful acquisition increments the fencing token. The token is returned to the worker and recorded in manifests/status evidence.
- Held authority returns a structured denial with the holder's run id, owner id, token, acquired timestamp, and expiry timestamp where safe to expose.
- Release verifies the current owner and fencing token. A stale worker must not release a newer worker's lease.
- Authority-bearing writes should validate the active fencing token before mutating live attempt, risk, or live-status state. This can be implemented in the first slice for the writes that happen before exchange submission, then expanded as needed.
- Keep the existing live worker behavior that stops before market collection when authority is not acquired.
- Preserve current fail-closed behavior: authority unavailable, database unavailable, stale token, or version conflict means no live order attempt.
- Keep S3 artifact writes and S3 manifest evidence. S3 remains evidence, not authority.
- Add a runtime authority implementation choice during rollout. AWS should move to the Postgres authority lease after tests and smoke evidence pass; S3 lock can remain as a temporary fallback.
- Preserve local fixture ergonomics. Local runs with no live order submission may continue to use the existing no-op authority behavior.
- Keep live risk admission state separate. The authority lease says "this worker may run"; live risk admission state says "this proposed order is admissible."
- Keep bounded live-risk admission refresh separate from lease acquisition. The lease must not scan prior orders, settle P&L, or resolve pending exposure.
- Keep strategy logic unchanged. Fair-value formula, BRTI context rules, quote freshness, `min_edge`, `min_contract_price`, risk caps, and taker-only IOC policy are out of this infrastructure change.
- Update manifests and live edge attribution timing so the authority phase clearly reports `postgres_authority_lease` instead of S3 lock evidence when enabled.
- Use the AWS hot-path evidence from `2026-06-09T22:30Z` to `2026-06-09T23:10Z` as the pre-change baseline: 33 runs, mean total `1.133s`, p95 total `1.237s`, mean S3 lock `0.809s`.
- Expected improvement is a reduction of roughly `0.6s` to `0.8s` per no-submit live cycle if the Postgres lease lands near the existing Postgres phase costs.
- Major modules to build or modify are: Operational State migration, a live-decision authority lease repository, the fair-value live worker authority adapter, manifest/status evidence projection, AWS/live runtime configuration, and focused tests.
- The deepest module should be the lease repository/authority service: a small interface for acquire, release, inspect, and validate-token behavior that encapsulates concurrency details behind testable outcomes.
- An ADR records the infrastructure decision: Postgres owns live-decision authority leases; S3 remains artifact storage.

## Testing Decisions

- Tests should assert external behavior: acquired/held/expired/released results, persisted lease rows, manifest evidence, skip reasons, and no downstream collection/submission when authority is held.
- Add migration tests proving the lease table and indexes exist and can be applied idempotently.
- Add pure repository tests for first acquire, competing acquire denied, expired acquire succeeds, release succeeds with matching token, release fails with stale token, validate-token succeeds, validate-token fails for stale token, and inspect returns current state.
- Add race-shaped tests using separate repository instances or transactions where practical. The important behavior is one winner and one held/denied result.
- Add live worker tests proving a held Postgres lease prevents market data collection and order-client calls, mirroring the existing S3/file lock-held test.
- Add live worker tests proving a successful Postgres lease records authority evidence in the manifest and releases or expires according to the designed lifecycle.
- Add live worker tests proving database authority errors fail closed before exchange submission.
- Add tests proving `submit_live_orders=False` local/report-only paths do not require live authority.
- Add tests proving S3 manifests still write after the Postgres authority path succeeds.
- Add tests proving live risk admission remains separate: acquiring authority alone does not approve an order.
- Add tests proving stale fencing tokens cannot mutate authority-bearing state.
- Add smoke evidence expectations for AWS before/after comparison: p95 total runtime, authority phase p95/mean, run count, submitted order count, and schedule state.
- Prior art includes existing live run lock-held tests, live risk admission repository tests, live runtime config tests, live order attempt persistence tests, and live edge attribution timing tests.

## Out of Scope

- Strategy/model changes.
- New fair-value thresholds, max-price caps, or order sizing changes.
- BRTI feature logic changes.
- Live settlement/P&L materialization.
- Full exchange account reconciliation.
- Maker execution policy.
- New Cockpit control surfaces beyond optional read-only authority status.
- Replacing EventBridge scheduling.
- Removing all S3 artifacts.
- Multi-region live authority.
- General distributed lock framework for unrelated systems.
- Current MVP cutover or legacy live-runner changes.

## Acceptance Criteria

- The `fair_value_live` AWS hot path can acquire live-decision authority through Postgres Operational State instead of S3.
- At most one worker can hold authority for a strategy at a time under concurrent acquire attempts.
- A stale worker cannot release, reserve risk, persist authority-bearing status, or submit live orders after a newer fencing token exists.
- Authority-held and authority-error paths fail closed before market collection and exchange submission.
- Live manifests record the authority backend, token, owner/run evidence, and authority timing phase.
- S3 remains the immutable artifact/audit store but is not the runtime authority source when the Postgres path is enabled.
- Before/after evidence reports mean/p95 total runtime and authority-phase contribution for the AWS live hot path.

## Further Notes

The pre-change status bar and summary were generated from read-only AWS evidence
and are stored locally under `artifacts/fair-value-live-latency-benchmark/`:

- `aws-live-hot-path-components.png`
- `aws-live-hot-path-latency-summary.json`
- `aws-live-report-20260609T223000Z-231000Z.json`

Those artifacts are evidence for product planning and portfolio presentation,
not live runtime authority. The important public-safe facts are the summarized
numbers above and the architectural conclusion: S3 should remain the audit
artifact store, while Operational State should grant live-decision authority.
