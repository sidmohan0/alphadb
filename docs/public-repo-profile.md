# Public Repository Profile

This is the prescriptive public positioning for AlphaDB.

## GitHub Description

Use this as the repository description:

> Replayable, risk-controlled prediction-market trading platform for research, shadow evaluation, and paper execution.

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
model-registry
mlops
quant-research
portfolio-project
```

## Longer Project Description

AlphaDB is an experimental target platform for researching, replaying, and
risk-controlling prediction-market trading systems. It starts with Kalshi's
`KXBTC15M` Bitcoin market family, but the architecture is designed around
reusable market specifications, append-only event capture, deterministic replay,
Postgres-backed operational state, model registry records, shared decisioning,
and risk-gated shadow and paper trading workflows.

The project is a public portfolio workspace for infrastructure and research
engineering. It is not a live trading bot, not a signals service, not investment
advice, and not a public copy of the current private MVP runner.

## Portfolio Boundary

Present AlphaDB as:

- A target-platform rewrite and research platform.
- A demonstration of trading-system architecture, replayability, auditability,
  and risk controls.
- A personal training and portfolio project that may eventually support live
  trading only after shadow and paper evidence.

Do not present AlphaDB as:

- A turnkey profitable strategy.
- A replacement for the current live MVP before cutover.
- A repository that contains live credentials, generated market data, account
  artifacts, private model binaries, or private operational history.
- Financial advice or a recommendation to trade.

## Current Implementation Narrative

The first public milestone should describe three active slices:

- Platform foundation health path: local install, tests, Docker Compose
  Postgres, and a dashboard shell.
- `MarketSpec` registry: explicit market-family assumptions with `KXBTC15M` as
  the first concrete market family.
- Operational-state tracer: Postgres-backed records for market instances,
  decisions, risk decisions, and order intents.

After that, the roadmap should move through raw event logging, REST-first
collection, model registry records, no-lookahead feature rows, shared
decisioning, risk gates, paper IOC execution, replay reports, shadow comparison,
WebSocket ingestion readiness, and a live cutover runbook.
