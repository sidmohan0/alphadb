# Public Repository Profile

This is the prescriptive public positioning for AlphaDB.

## GitHub Description

Use this as the repository description:

> Open-source prediction-market trading platform for replay, risk controls, paper execution, and guarded live deployment.

## GitHub Topics

Use these repository topics:

```text
prediction-markets
kalshi
algorithmic-trading
trading-systems
market-data
event-sourcing
event-driven
risk-management
paper-trading
backtesting
python
postgresql
streamlit
pydantic
docker-compose
aws
model-registry
mlops
quant-research
portfolio-project
```

## Longer Project Description

AlphaDB is an open-source-oriented platform for building, researching,
replaying, deploying, and risk-controlling prediction-market trading systems. It
starts with Kalshi's `KXBTC15M` Bitcoin market family, but the architecture is
designed around reusable market specifications, append-only event capture,
deterministic replay, Postgres-backed operational state, model registry records,
shared decisioning, and risk-gated shadow, paper, and guarded live workflows.

The project is a public portfolio workspace for trading-system infrastructure,
research engineering, and deployment discipline. It is not a signals service,
not investment advice, not a turnkey profitable strategy, and not a repository
for private credentials, generated datasets, model binaries, account-specific
state, or private runtime history.

## Portfolio Boundary

Present AlphaDB as:

- An open-source prediction-market trading platform.
- A demonstration of trading-system architecture, replayability, auditability,
  and risk controls.
- A local-first developer workspace with Docker Compose and a public AWS
  deployment story.
- A portfolio-quality project that can support guarded live operation only under
  explicit operator controls.

Do not present AlphaDB as:

- A turnkey profitable strategy.
- A repository that contains live credentials, generated market data, account
  artifacts, private model binaries, or private operational history.
- Financial advice or a recommendation to trade.

## Current Implementation Narrative

The public implementation narrative should emphasize these active slices:

- Platform foundation health path: local install, tests, Docker Compose
  Postgres, and a dashboard shell.
- `MarketSpec` registry: explicit market-family assumptions with `KXBTC15M` as
  the first concrete market family.
- Operational-state tracer: Postgres-backed records for market instances,
  decisions, risk decisions, and order intents.
- AWS dashboard deployment: a public, secret-safe deployment path that
  demonstrates production-shaped operations without committing private runtime
  state.
- Repository hygiene: automated checks and a public-share audit command that
  keep secrets, generated artifacts, and private runtime material out of Git.

After that, the roadmap should move through raw event logging, REST-first
collection, model registry records, no-lookahead feature rows, shared
decisioning, risk gates, paper IOC execution, replay reports, shadow comparison,
WebSocket ingestion readiness, and a live cutover runbook.
