# ADR 0001: Monorepo And App Topology

- Status: Accepted
- Date: 2026-03-09

## Context

`ansi-polymarket-tui` is a terminal-first client with direct provider integrations and local state. `ts-v1` is a TypeScript full-stack service centered on Polymarket discovery runs, persistence, and operational controls. They are related, but they are not the same application.

We need a structure that allows:

- a production backend service
- a terminal client
- a web client
- shared provider/domain code
- independent deployment and release of each surface

## Decision

Adopt a single monorepo with multiple deployable apps and shared packages. Absorb the TUI into the existing `ts-v1` monorepo shape rather than forcing the backend into the TUI repo shape.

Target topology:

```text
apps/api            Backend service and async workers
apps/web            Browser UI
apps/tui            ANSI terminal client
packages/domain     Canonical market models, provider-neutral types
packages/providers  Provider adapters and normalization code
packages/search     Ranking, indexing, query contracts
packages/config     Shared env parsing and runtime config
packages/sdk        Typed client for api/web/tui
infra/              Deployment manifests, migrations, runbooks
docs/adrs/          Architecture decisions
```

## Consequences

Positive:

- shared types without forcing runtime coupling
- one source tree for backend, web, and TUI
- clearer package boundaries than the current branch split
- easier CI, release management, and migration sequencing

Negative:

- more repository complexity than the current standalone TUI
- package boundaries must be enforced early or the monorepo will rot

## Notes

The merge target should be the `ts-v1` shape. It already carries the backend operational model that production requires.
