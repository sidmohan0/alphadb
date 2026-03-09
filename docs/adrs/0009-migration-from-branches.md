# ADR 0009: Migration Plan From `ts-v1` And `ansi-polymarket-tui`

- Status: Accepted
- Date: 2026-03-09

## Context

`ts-v1` already contains the backend-oriented monorepo shape. `ansi-polymarket-tui` already contains the stronger client UX and multi-provider comparison model. We need a low-risk path that preserves both.

## Decision

Merge by stages, with `ts-v1` as the structural base.

Phase 1:

- create shared ADR and package layout
- move the TUI into `apps/tui`
- preserve current direct-provider mode in the TUI

Phase 2:

- extract shared provider-neutral types into `packages/domain`
- extract provider adapters into `packages/providers`
- add a typed internal SDK in `packages/sdk`

Phase 3:

- expose normalized trending/search/history endpoints from `apps/api`
- let the TUI read from the backend behind a feature flag
- keep direct mode as fallback during migration

Phase 4:

- add watchlists, recents, and preferences to backend-backed user state
- add auth for web and TUI
- move search and enrichment logic server-side

Phase 5:

- add live normalized subscriptions
- retire direct provider mode from production builds
- keep dev-only or emergency fallback if justified

## Consequences

Positive:

- avoids rewriting the TUI before the backend is ready
- avoids destabilizing the existing backend branch with a big-bang merge
- makes each migration step testable and reversible

Negative:

- temporary duplication between direct mode and service mode
- longer period of mixed architecture

## Notes

The first real integration milestone should be: the TUI consumes backend trending/search/history while preserving its current UX. That proves the merge is useful before expanding scope.
