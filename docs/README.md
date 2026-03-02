# Project Documentation

## Polymarket

- `docs/polymarket/README.md`
  - Implementation notes for discovery architecture, async run APIs, and operations rollout.
- `docs/polymarket/polymarket-market-channels-visual-plan-diagram.html`
  - Call graph / flow-style visual report for `server/src/polymarketMarketChannels.ts`.
- `docs/polymarket/polymarket-market-channels-call-graph.html`
  - A call hierarchy/call graph representation for the same file structure.
- `docs/polymarket/polymarket-discovery-runs-visual-plan.html`
  - Architecture and endpoint model for async `discovery_runs` + Postgres/Redis orchestration.
- `docs/polymarket/discovery-run-implementation-checklist.md`
  - Backend implementation checklist and commit plan used during rollout.

## Discovery run rollout updates now included

- Postgres schema bootstrap: `server/src/polymarket/infra/db/schemas.sql`
- Redis + cache layer: `server/src/polymarket/infra/cache`
- Repositories: `server/src/polymarket/repositories`
- Run orchestration + pruning: `server/src/polymarket/services/discoveryRunService.ts`
- Migration helper: `server/src/polymarket/maintenance/migrateDiscoveryRuns.ts`
- Integration test path: `server/test/polymarket.discovery.integration.test.ts`
