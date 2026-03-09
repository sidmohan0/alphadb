# ADRs

This directory holds architecture decision records for converging the current ANSI TUI with a production-grade backend service and the existing `ts-v1` branch.

Status legend:

- `Proposed`: directionally recommended, not yet frozen
- `Accepted`: approved and ready to implement
- `Superseded`: replaced by a newer ADR

Current ADR set:

- `0001-monorepo-and-app-topology.md`
- `0002-client-backend-contract.md`
- `0003-canonical-market-domain-model.md`
- `0004-storage-caching-and-retention.md`
- `0005-search-discovery-and-ranking.md`
- `0006-realtime-ingestion-and-delivery.md`
- `0007-auth-tenancy-and-user-state.md`
- `0008-observability-sre-and-release.md`
- `0009-migration-from-branches.md`

Accepted on 2026-03-09:

- use `ts-v1` as the merge base
- keep separate deployable apps for `api`, `web`, and `tui`
- move the TUI toward a backend-first production data path
- preserve direct provider access only as a migration or emergency fallback
