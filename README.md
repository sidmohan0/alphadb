# AlphaDB

AlphaDB is an experimental target platform for researching, replaying, and
risk-controlling prediction-market trading systems.

The project starts with Kalshi's `KXBTC15M` Bitcoin market family, but the
platform is being built around reusable boundaries: explicit market
specifications, append-only event capture, deterministic replay, Postgres-backed
operational state, model registry records, shared decisioning, and risk-gated
shadow and paper trading workflows.

## Status

AlphaDB is an early platform scaffold. It is not a live trading bot, not a
signals service, and not investment advice.

The current implementation focus is the first target-platform live-prep slice:

- A local health path for the Python package, Postgres runtime, tests, and
  dashboard shell.
- A `MarketSpec` registry with `KXBTC15M` as the first concrete market family.
- A Postgres-backed operational-state tracer for runs, decisions, risk
  decisions, order intents, paper execution, strategy outcomes, shadow
  comparisons, evidence reports, and guarded live-order attempts.
- Runtime modes for `fixture`, `shadow`, `paper`, and `gated-live`, with live
  order submission denied by default.
- A pinned Current MVP artifact loader, Coinbase feature adapter, Current MVP
  feature-row parity builder, live-data paper runner, shadow parity runner,
  gated-live Kalshi order adapter, and continuous gated-live strategy loop.

Authenticated WebSocket ingestion remains gated work. AlphaDB is not
live-authoritative until the human ALP-15 cutover approval happens.

## Project Boundary

AlphaDB is the target-platform workspace for a future reusable prediction-market
trading system. It is intentionally separate from the current private Kalshi MVP
runner, which remains authoritative until a documented cutover.

This repository is meant to be public portfolio-quality infrastructure and
research code. It should not contain live credentials, generated market data,
private strategy artifacts, account-specific risk settings, or the operational
history of the current MVP.

Live trading is outside the default development path. Any live mode must be
introduced behind explicit configuration, shadow-run evidence, paper-trading
evidence, risk limits, rollback instructions, and a human approval step.

## Core Ideas

- `MarketSpec`: a typed description of a tradable market family, including
  discovery rules, settlement source, feature configuration, label behavior, fee
  assumptions, risk configuration, and trading cutoffs.
- Raw event log: append-only capture of market snapshots, external feature
  events, exchange events, execution events, receive timestamps, schema versions,
  payload hashes, and raw payloads.
- Operational state: transactional Postgres records for runs, market instances,
  decisions, risk decisions, order intents, orders, fills, positions,
  reconciliation, and model registry references.
- Shared decision engine: runtime-independent decisioning that can be reused by
  historical replay, shadow runs, paper trading, and eventually live trading.
- Event-driven replay: deterministic reconstruction of features, model outputs,
  decisions, risk outcomes, execution, positions, PnL, and diagnostics from raw
  events and immutable artifacts.
- Target-platform dashboard: a Streamlit-first operational and research surface
  for health, replay diagnostics, paper trading, live-readiness checks, risk
  state, PnL, latency, and model registry visibility.

## Architecture Shape

```text
MarketSpec registry
  -> ingestion adapters
  -> raw event log
  -> feature rows and no-lookahead ledger
  -> model registry and model outputs
  -> shared decision engine
  -> risk gate and sizing
  -> paper/live execution adapters
  -> operational state, replay reports, and dashboard
```

The same domain contracts should be used across replay, shadow, paper, and live
modes. The event source, clock, and exchange adapter can vary; the decision and
risk boundary should remain inspectable and replayable.

## Repository Layout

```text
.
|-- CONTEXT.md              # Domain vocabulary and architectural boundary
|-- docker-compose.yml      # Local Postgres and dashboard-oriented services
|-- docs/                   # Agent and architecture notes
|-- src/alphadb/            # Python package
|-- tests/                  # Pytest suite
`-- pyproject.toml          # Package metadata and tool configuration
```

## Local Development

AlphaDB targets Python 3.12+.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
```

Start Postgres for local target-platform development:

```bash
docker compose up -d postgres
```

Run the same install/test path inside the Compose app container:

```bash
docker compose run --rm app bash -lc "python -m pip install -e '.[dev,dashboard]' && pytest -q && alphadb-health"
```

Run the dashboard profile when dashboard work is active:

```bash
docker compose --profile dashboard up streamlit
```

Inspect registered market specifications:

```bash
alphadb-markets list
alphadb-markets inspect KXBTC15M --json
```

Run the bounded, read-only KXBTC15M REST collector smoke with deterministic
fixture data:

```bash
alphadb-collect kxbtc15m-smoke --source fixture --max-markets 1
alphadb-collect status
```

To opt into Kalshi public market-data endpoints, use
`--source kalshi-public`. This path only fetches market data and order books;
it does not have order-entry code.

Register and inspect model artifact metadata without storing model binaries in
Postgres:

```bash
alphadb-models register-demo --series KXBTC15M
alphadb-models list --series KXBTC15M
```

Build decision-time feature rows with no-lookahead evidence:

```bash
alphadb-features build-row \
  --run-id <run_id> \
  --market-ticker <market_ticker> \
  --model-id <model_id> \
  --decision-timestamp 2026-05-31T21:13:00+00:00
alphadb-features list --run-id <run_id>
```

Evaluate and persist a runtime-independent decision candidate:

```bash
alphadb-decide evaluate \
  --feature-row-id <feature_row_id> \
  --probability-yes 0.62
alphadb-decide list --run-id <run_id>
```

Apply the fail-closed risk gate and create an approved order intent only when
policy allows it:

```bash
alphadb-risk evaluate \
  --decision-id <decision_id> \
  --realized-pnl-dollars 0
alphadb-risk list --decision-id <decision_id>
```

Run paper-only taker IOC execution and reconciliation:

```bash
alphadb-paper execute \
  --order-intent-id <order_intent_id> \
  --side yes \
  --available-price-dollars 0.52 \
  --available-quantity 1
alphadb-paper status
```

Build an event-driven replay report from raw events through paper execution:

```bash
alphadb-replay report \
  --run-id <run_id> \
  --market-ticker <market_ticker> \
  --model-id <model_id> \
  --decision-timestamp 2026-05-31T21:13:00+00:00 \
  --probability-yes 0.65
```

Compare AlphaDB and Current MVP decision-boundary records without giving
AlphaDB live control:

```bash
alphadb-shadow compare \
  --alpha-json '{"market_ticker":"..."}' \
  --current-json '{"market_ticker":"..."}'
alphadb-shadow status
```

Exercise WebSocket ingestion readiness with mocked events. Live WebSocket smoke
is opt-in only and requires credentials from environment variables outside Git:

```bash
alphadb-ws mock-smoke --market-ticker <market_ticker> --run-id <run_id>

ALPHADB_ENABLE_LIVE_WS_SMOKE=1 \
ALPHADB_KALSHI_WS_URL=wss://... \
KALSHI_API_KEY_ID=... \
KALSHI_PRIVATE_KEY_PATH=/path/to/private-key.pem \
alphadb-ws live-smoke
```

Inspect runtime guard state:

```bash
alphadb-runtime status
```

Validate pinned Current MVP strategy artifacts from local-only config:

```bash
ALPHADB_ARTIFACT_ROOT=/path/to/private/artifacts \
ALPHADB_CURRENT_MVP_ARTIFACT_CONFIG=/path/to/private/artifacts/kxbtc15m.json \
alphadb-artifacts status
```

Run one bounded KXBTC15M live-data paper cycle with fixture market data:

```bash
ALPHADB_ARTIFACT_ROOT=/path/to/private/artifacts \
ALPHADB_CURRENT_MVP_ARTIFACT_CONFIG=/path/to/private/artifacts/kxbtc15m.json \
alphadb-strategy paper-cycle --source fixture --now 2026-05-31T21:13:00Z

alphadb-strategy status
```

Run one hour of live-data paper evidence against live Kalshi public market data
and live Coinbase features. This does not submit real orders:

```bash
ALPHADB_RUNTIME_MODE=paper \
ALPHADB_ENABLE_LIVE_ORDERS=0 \
ALPHADB_LIVE_STAKE_CAP_DOLLARS=1.0 \
ALPHADB_MAX_DAILY_LOSS_DOLLARS=10.0 \
ALPHADB_MIN_EV_DOLLARS=0.0 \
ALPHADB_ARTIFACT_ROOT=/path/to/private/artifacts \
ALPHADB_CURRENT_MVP_ARTIFACT_CONFIG=/path/to/private/artifacts/kxbtc15m.json \
alphadb-strategy paper-loop --source live --duration-minutes 60 --max-markets 3
```

Import a Current MVP decision-boundary export and compare parity:

```bash
alphadb-shadow-current-mvp import /path/to/current-mvp-boundary.json
alphadb-shadow-parity compare-market --run-id <run_id> --market-ticker <market_ticker>
alphadb-shadow status
```

Build an evidence report for a bounded paper run:

```bash
alphadb-evidence report \
  --run-id <run_id> \
  --observed-end 2026-05-31T22:13:00Z
```

Inspect the gated-live adapter. The smoke command is opt-in and still fails
closed unless runtime mode, credentials, explicit live enablement, and human
cutover approval are all present:

```bash
alphadb-live-orders status

ALPHADB_RUNTIME_MODE=gated-live \
ALPHADB_ENABLE_LIVE_ORDERS=1 \
ALPHADB_HUMAN_CUTOVER_APPROVED=1 \
ALPHADB_ENABLE_LIVE_ORDER_SMOKE=1 \
KALSHI_API_KEY_ID=... \
KALSHI_PRIVATE_KEY_PATH=/path/to/private-key.pem \
alphadb-live-orders live-smoke --order-intent-id <order_intent_id>
```

After the one-hour evidence report passes and ALP-15 is approved, run one
guarded live-money cycle or the continuous live loop. The live loop uses live
market data only, submits taker-only IOC orders through the gated-live adapter,
and exits non-zero if a cycle records an error:

```bash
ALPHADB_RUNTIME_MODE=gated-live \
ALPHADB_ENABLE_LIVE_ORDERS=1 \
ALPHADB_HUMAN_CUTOVER_APPROVED=1 \
ALPHADB_LIVE_STAKE_CAP_DOLLARS=1.0 \
ALPHADB_MAX_DAILY_LOSS_DOLLARS=10.0 \
ALPHADB_MIN_EV_DOLLARS=0.0 \
KALSHI_API_KEY_ID=... \
KALSHI_PRIVATE_KEY_PATH=/path/to/private-key.pem \
ALPHADB_ARTIFACT_ROOT=/path/to/private/artifacts \
ALPHADB_CURRENT_MVP_ARTIFACT_CONFIG=/path/to/private/artifacts/kxbtc15m.json \
alphadb-strategy gated-live-cycle --max-markets 1

ALPHADB_RUNTIME_MODE=gated-live \
ALPHADB_ENABLE_LIVE_ORDERS=1 \
ALPHADB_HUMAN_CUTOVER_APPROVED=1 \
ALPHADB_LIVE_STAKE_CAP_DOLLARS=1.0 \
ALPHADB_MAX_DAILY_LOSS_DOLLARS=10.0 \
ALPHADB_MIN_EV_DOLLARS=0.0 \
KALSHI_API_KEY_ID=... \
KALSHI_PRIVATE_KEY_PATH=/path/to/private-key.pem \
ALPHADB_ARTIFACT_ROOT=/path/to/private/artifacts \
ALPHADB_CURRENT_MVP_ARTIFACT_CONFIG=/path/to/private/artifacts/kxbtc15m.json \
alphadb-strategy gated-live-loop --max-markets 3
```

Keep the current private MVP runner available as rollback until the AlphaDB
live smoke and first gated-live cycle both succeed.

By default, local Postgres is published on `localhost:55433` and Streamlit on
`localhost:8501`. Override those with `ALPHADB_POSTGRES_PORT` and
`ALPHADB_STREAMLIT_PORT` when needed. Override the Kalshi REST base URL with
`ALPHADB_KALSHI_BASE_URL`.

The default local Postgres URL is:

```text
postgresql://alphadb:alphadb@localhost:55433/alphadb
```

Use `.env.example` as the local configuration template. Do not commit secrets,
live credentials, generated datasets, model binaries, or exchange/account
artifacts.

## Public Repo Metadata

Recommended GitHub description:

> Replayable, risk-controlled prediction-market trading platform for research,
> shadow evaluation, and paper execution.

Recommended GitHub topics:

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

## Non-Goals

- AlphaDB does not replace the current private MVP until a deliberate cutover.
- AlphaDB does not publish a turnkey profitable strategy.
- AlphaDB does not require live exchange credentials for normal development or
  tests.
- AlphaDB does not store private account data, raw generated datasets, model
  binaries, or secrets in Git.

## License

License TBD before public release. Until a license is added, this code is not
offered under an open-source license.
