# Python Owns the Dashboard API

Accepted. The Agent-first dashboard will call Python-owned Dashboard API endpoints for operational state, actions, Data Explorer views, saved dataset snapshots, Experiment Journal records, and agent skills; Next.js will not connect directly to target-platform Postgres for MVP dashboard behavior. We chose this over TypeScript route handlers owning backend logic so trading, replay, registry, state migrations, and Postgres repositories stay in one Python target-platform backend.

## Considered Options

- Python owns Dashboard API endpoints and Next.js remains the user-facing cockpit.
- Next.js owns route handlers and connects directly to Postgres.
- Hybrid ownership between Python and Next.js.

## Consequences

- Python services need enough API structure and reliability to support a real frontend, not only a tiny stdlib HTML dashboard.
- Frontend work can move fast without duplicating operational queries or trading semantics in TypeScript.
