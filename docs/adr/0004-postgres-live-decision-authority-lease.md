# Postgres Owns Live-Decision Authority Leases

Accepted. AlphaDB will move live-decision authority from the S3 live-run lock to
a strategy-scoped Postgres authority lease in Operational State, with a
monotonically advancing fencing token on successful acquisition. S3 remains the
artifact and audit-evidence store, but runtime singleton authority belongs with
the same transactional control plane that owns live runtime config, risk
admission state, live order attempts, and live status.

## Rationale

Recent AWS fair-value live manifests show the S3 live-run lock consuming about
71% of observed no-submit hot-path latency. More importantly, S3 object storage
is the wrong production primitive for runtime coordination: it is durable and
auditable, but it is slower and less transactionally meaningful than Operational
State. A Postgres lease keeps authority, risk, attempts, and status in one
inspectable control plane while preserving fail-closed singleton behavior.

## Consequences

- Live workers must acquire a Live-decision authority lease before any live
  order attempt.
- Authority-bearing writes should carry the acquired fencing token so stale
  workers cannot mutate state after a newer worker takes authority.
- S3 manifests should record lease evidence for auditability, but S3 must not be
  the source of runtime authority.
- The transitional S3 live-run lock fallback is retired after AWS post-change
  evidence proved the Postgres lease path; stale S3 authority configuration
  should be rejected rather than silently used.
