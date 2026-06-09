<div align="center">

# AlphaDB
**Replayable, risk-controlled infrastructure for prediction-market trading systems.**

[![CI][ci-shield]][ci-url]
[![Python][python-shield]][python-url]
[![PostgreSQL][postgres-shield]][postgres-url]
[![Dashboard][dashboard-shield]](#dashboard-and-deployment)
[![Docker Compose][compose-shield]][compose-url]
[![License][license-shield]](#license)

[ci-shield]: https://github.com/sidmohan0/alphadb/actions/workflows/ci.yml/badge.svg
[ci-url]: https://github.com/sidmohan0/alphadb/actions/workflows/ci.yml
[python-shield]: https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat&logo=python&logoColor=white
[python-url]: https://www.python.org/
[postgres-shield]: https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat&logo=postgresql&logoColor=white
[postgres-url]: https://www.postgresql.org/
[dashboard-shield]: https://img.shields.io/badge/Dashboard-Live%20Console-5EE2A0?style=flat
[compose-shield]: https://img.shields.io/badge/Runtime-Docker%20Compose-2496ED?style=flat&logo=docker&logoColor=white
[compose-url]: https://docs.docker.com/compose/
[license-shield]: https://img.shields.io/badge/License-TBD-lightgrey?style=flat

</div>

AlphaDB is a target-platform workspace for researching, replaying, deploying,
and risk-controlling prediction-market trading systems. It starts with Kalshi's
`KXBTC15M` Bitcoin market family, but the design is intentionally broader:
explicit market specifications, append-only event capture, deterministic replay,
Postgres-backed operational state, model registry records, shared decisioning,
and fail-closed runtime guards.

- Build market-family specs instead of one-off strategy scripts.
- Capture raw events and feature rows with no-lookahead evidence.
- Reuse one decision boundary across replay, shadow, paper, and guarded live modes.
- Keep public development useful without live credentials or private artifacts.
- Preserve a hard boundary between this target platform and any current live MVP.

AlphaDB is not a signals service, not investment advice, and not a promise of
profitable trading. Live operation is outside the default contributor path and
requires explicit operator configuration, risk gates, credentials, evidence, and
human approval.

## Get Started

### Local

Install the package and run the test suite:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,dashboard]"
pytest
```

Start local Postgres:

```bash
docker compose up -d postgres
```

Run the same health path inside the Compose app container:

```bash
docker compose run --rm app bash -lc "python -m pip install -e '.[dev,dashboard]' && pytest -q && alphadb-health"
```

### Cockpit

Start the canonical local Cockpit stack:

```bash
docker compose --profile cockpit up --build cockpit
```

Open `http://localhost:3000`. This one Compose profile starts:

- Postgres, published on `localhost:55433` by default.
- The Python AlphaDB API and legacy compatibility surface, published on
  `localhost:8501` by default.
- The Next.js Cockpit, published on `localhost:3000` by default.

The Cockpit calls the Python AlphaDB API through `/api/alphadb/*`; the Next.js
service is not given `DATABASE_URL` and does not connect directly to Postgres.
Override the published host ports with `ALPHADB_POSTGRES_PORT`,
`ALPHADB_DASHBOARD_PORT`, and `ALPHADB_COCKPIT_PORT` when needed.

Run the AFK-agent smoke check after the stack is up:

```bash
./scripts/smoke-local-cockpit.sh
```

It checks the direct Python compatibility health endpoint, the Cockpit page,
and the proxied Cockpit `/api/alphadb/health` route against the Python service.
For more detail, see [docs/deployment/local-cockpit.md](docs/deployment/local-cockpit.md).

Run the lightweight Cockpit auth smoke against a running local Cockpit:

```bash
COCKPIT_URL=http://localhost:3000 apps/dashboard/scripts/smoke-auth.sh
```

For AWS-shaped local auth, run Cockpit with `ALPHADB_COCKPIT_PIN` and
`ALPHADB_COCKPIT_COOKIE_SECRET`, then rerun the same script with
`ALPHADB_COCKPIT_PIN` exported.

### Configuration

Use `.env.example` as the local configuration template:

```bash
cp .env.example .env
```

Do not commit `.env`, live credentials, private keys, model binaries, generated
datasets, strategy logs, exchange account data, or private runtime artifacts.

## What AlphaDB Does

AlphaDB is organized around trading-system boundaries that stay inspectable
under replay and fail closed around live money.

| Surface | What it provides |
| --- | --- |
| `MarketSpec` registry | Typed market-family assumptions, starting with `KXBTC15M`. |
| Raw event log | Append-only market, feature, exchange, and execution events with payload hashes. |
| Feature ledger | Decision-time feature rows with no-lookahead evidence and artifact references. |
| Model registry | Postgres metadata for immutable model, feature, calibration, and dataset artifacts. |
| Decision engine | Runtime-independent order-or-skip decisions from state, features, quotes, and policy. |
| Risk gate | Fail-closed sizing, loss, mode, and live-order checks before execution. |
| Paper execution | Taker-only IOC simulation and reconciliation without live exchange control. |
| Shadow comparison | Decision-boundary parity checks against an external or current MVP export. |
| Cockpit | Next.js human-and-agent supervision UI for live ops, Strategy Studio, Data Explorer, Lab, and Terminal. |
| AlphaDB API | Python product API for Cockpit and external agents; owns strategy, data, Lab, skills, and runtime-config surfaces. |
| AWS deployment | Secret-safe Cockpit and AlphaDB API deployment path with managed infrastructure assumptions. |

## Architecture

```mermaid
flowchart LR
    spec["MarketSpec registry"] --> ingest["REST, WebSocket, fixture ingestion"]
    ingest --> log["Raw event log"]
    log --> features["Feature rows and no-lookahead ledger"]
    features --> registry["Model registry and pinned artifacts"]
    registry --> decision["Shared decision engine"]
    decision --> risk["Risk gate and sizing"]
    risk --> execute["Paper or gated-live execution"]
    execute --> state["Operational state"]
    state --> api["AlphaDB API"]
    api --> cockpit["Cockpit"]
    state --> replay["Replay, evidence, Lab"]
    log --> replay
```

The same domain contracts are meant to run across fixture, replay, shadow,
paper, and gated-live workflows. The event source, clock, and exchange adapter
can change; the decision, risk, and audit boundary should remain reconstructable.
For UI and agent work, the default boundary stack is
`Cockpit -> AlphaDB API -> Operational State -> Runtime / Replay / Research`.
See [docs/architecture/boundaries.md](docs/architecture/boundaries.md).

## Runtime Modes

| Mode | Purpose | Live orders |
| --- | --- | --- |
| `fixture` | Deterministic local development and tests. | Disabled |
| `shadow` | Compare AlphaDB decisions against another decision boundary. | Disabled |
| `paper` | Run live-data or replay-backed simulations without exchange control. | Disabled |
| `gated-live` | Wire live order submission behind explicit operator gates. | Disabled until all gates pass |

Inspect the current runtime guard:

```bash
alphadb-runtime status
```

## Examples

### Market Specs

Inspect registered market families:

```bash
alphadb-markets list
alphadb-markets inspect KXBTC15M --json
```

### Settlement Readiness

Run the public synthetic settlement-state readiness workflow:

```bash
alphadb-settlement synthetic-readiness
```

This uses bundled synthetic fixtures only. It writes generated settlement-state
rows, summaries, public-safe manifests, and readiness reports under ignored
`artifacts/settlement-state/` output by default. Synthetic readiness is not a
strategy promotion decision and does not imply live-trading readiness.

### Market Collection

Run a bounded, read-only `KXBTC15M` collector smoke with fixture data:

```bash
alphadb-collect kxbtc15m-smoke --source fixture --max-markets 1
alphadb-collect status
```

Opt into Kalshi public market-data endpoints:

```bash
alphadb-collect kxbtc15m-smoke --source kalshi-public --max-markets 1
```

This path fetches market data and order books only. It does not contain
order-entry behavior.

### Model Registry And Decisions

Register model artifact metadata without storing model binaries in Postgres:

```bash
alphadb-models register-demo --series KXBTC15M
alphadb-models list --series KXBTC15M
```

Build a decision-time feature row:

```bash
alphadb-features build-row \
  --run-id <run_id> \
  --market-ticker <market_ticker> \
  --model-id <model_id> \
  --decision-timestamp 2026-05-31T21:13:00+00:00
```

Evaluate a runtime-independent decision candidate:

```bash
alphadb-decide evaluate \
  --feature-row-id <feature_row_id> \
  --probability-yes 0.62
```

Apply the risk gate and create an approved order intent only when policy allows:

```bash
alphadb-risk evaluate \
  --decision-id <decision_id> \
  --realized-pnl-dollars 0
```

### Paper Execution And Replay

Run taker-only IOC paper execution:

```bash
alphadb-paper execute \
  --order-intent-id <order_intent_id> \
  --side yes \
  --available-price-dollars 0.52 \
  --available-quantity 1
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

### Shadow Parity

Compare two decision-boundary records without giving AlphaDB live control:

```bash
alphadb-shadow compare \
  --alpha-json '{"market_ticker":"..."}' \
  --current-json '{"market_ticker":"..."}'
```

Import an external decision-boundary export and compare parity:

```bash
alphadb-shadow-current-mvp import /path/to/current-mvp-boundary.json
alphadb-shadow-parity compare-market --run-id <run_id> --market-ticker <market_ticker>
```

### WebSocket Readiness

Exercise WebSocket ingestion with mocked events:

```bash
alphadb-ws mock-smoke --market-ticker <market_ticker> --run-id <run_id>
```

Live WebSocket smoke is opt-in only and requires credentials from environment
variables outside Git:

```bash
ALPHADB_ENABLE_LIVE_WS_SMOKE=1 \
ALPHADB_KALSHI_WS_URL=wss://... \
KALSHI_API_KEY_ID=... \
KALSHI_PRIVATE_KEY_PATH=/path/to/private-key.pem \
alphadb-ws live-smoke
```

### BRTI Live Context

Ingest one controlled `cfbenchmarks_value` BRTI tick into index-level raw events
and the latest-context projection:

```bash
alphadb-brti mock-smoke
alphadb-brti status
```

Live BRTI collection is also credential-gated. It subscribes to
`cfbenchmarks_value` with `index_ids: ["BRTI"]` and writes accepted ticks with
`market_ticker = null` because BRTI is index-level context, not a concrete
Kalshi market instance:

```bash
ALPHADB_ENABLE_LIVE_WS_SMOKE=1 \
ALPHADB_KALSHI_WS_URL=wss://external-api-ws.kalshi.com/trade-api/ws/v2 \
KALSHI_API_KEY_ID=... \
KALSHI_PRIVATE_KEY_PATH=/path/to/private-key.pem \
alphadb-brti live-collect --max-messages 1
```

### Live-Data Paper Runs

Validate pinned model artifacts from local-only config:

```bash
ALPHADB_ARTIFACT_ROOT=/path/to/private/artifacts \
ALPHADB_CURRENT_MVP_ARTIFACT_CONFIG=/path/to/private/artifacts/kxbtc15m.json \
alphadb-artifacts status
```

Run one bounded `KXBTC15M` paper cycle with fixture market data:

```bash
ALPHADB_ARTIFACT_ROOT=/path/to/private/artifacts \
ALPHADB_CURRENT_MVP_ARTIFACT_CONFIG=/path/to/private/artifacts/kxbtc15m.json \
alphadb-strategy paper-cycle --source fixture --now 2026-05-31T21:13:00Z
```

Run one hour of live-data paper evidence against live Kalshi public market data
and Coinbase features. This does not submit real orders:

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

Build an evidence report for a bounded paper run:

```bash
alphadb-evidence report \
  --run-id <run_id> \
  --observed-end 2026-05-31T22:13:00Z
```

### Gated Live Adapter

Inspect the live-order adapter. The smoke command remains opt-in and fails
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

Operator-controlled live-money cycles should run only after evidence, risk,
credential, rollback, and human approval gates are satisfied:

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
```

Continuous live loops follow the same gate pattern:

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
alphadb-strategy gated-live-loop --max-markets 3
```

The fair-value live-money canary has separate ledger-style caps for each order,
each market ticker, and realized daily loss. Locally, either pass
the CLI flags explicitly or set env vars and omit the flags:

```bash
ALPHADB_RUNTIME_MODE=gated-live \
ALPHADB_ENABLE_LIVE_ORDERS=0 \
ALPHADB_LIVE_STAKE_CAP_DOLLARS=2.25 \
ALPHADB_MAX_TICKER_EXPOSURE_DOLLARS=3.50 \
ALPHADB_MAX_DAILY_LOSS_DOLLARS=12.00 \
alphadb-model-eval fair-value-live-trading-job \
  --source fixture \
  --coinbase-source fixture \
  --output-root /tmp/alphadb-fair-value-live \
  --max-markets 1
```

Equivalent explicit flags are `--max-order-dollars`,
`--max-ticker-exposure-dollars`, and `--max-daily-loss-dollars`. In AWS, the
dashboard is the non-secret runtime config control plane. The live worker reads
the latest Postgres-saved config at run start and records the config snapshot in
the run manifest.

## Cockpit, API, And Deployment

The Cockpit is the Next.js human-and-agent supervision UI. The AlphaDB API is
the Python service that owns strategy compilation, curated data access, Lab
memory, agent skills, runtime config, and Postgres-backed operational state.
Cockpit does not connect directly to Postgres or own trading logic.

The canonical local operator URL is the Cockpit at `http://localhost:3000`.
The Python service on `http://localhost:8501` is the local AlphaDB API target
and legacy compatibility surface during the MVP transition.

Start both services with local Postgres through the Cockpit Compose profile:

```bash
docker compose --profile cockpit up --build cockpit
./scripts/smoke-local-cockpit.sh
```

The AWS Cockpit deployment path runs two ECS services: public Cockpit and
private AlphaDB API. The public URL serves the production-built Next.js
Cockpit, while the Python API remains private and owns Postgres access. Browser
calls keep the same `/api/alphadb/*` shape used locally.

Runtime config contains only non-secret fair-value live parameters: max order
dollars, max market exposure dollars, max daily loss dollars, min edge, and max
markets. Secrets and infrastructure values stay outside the dashboard/Cockpit.
In AWS-like environments, Cockpit access requires a four-digit PIN and signed
cookie secret supplied through Secrets Manager. The Cockpit task receives those
Cockpit auth secrets but does not receive `DATABASE_URL`; the private AlphaDB
API task receives `DATABASE_URL`.

Run deployment-shaped local checks:

```bash
export DATABASE_URL=postgresql://alphadb:alphadb@localhost:55433/alphadb
export ALPHADB_ENV=aws
export AWS_REGION=us-east-2
export ALPHADB_AWS_REGION=us-east-2
export ALPHADB_RUNTIME_MODE=paper
export ALPHADB_ENABLE_LIVE_ORDERS=0
export ALPHADB_HUMAN_CUTOVER_APPROVED=0
export ALPHADB_DASHBOARD_PIN=1234
export ALPHADB_DASHBOARD_COOKIE_SECRET="$(openssl rand -hex 32)"

alphadb-deploy migrate
alphadb-deploy seed-readiness --series KXBTC15M
alphadb-deploy smoke
```

See [docs/deployment/aws-dashboard.md](docs/deployment/aws-dashboard.md) for the
current ECS/Fargate Cockpit and private AlphaDB API deployment path. The live
worker deployment remains separate.

## Repository Layout

```text
.
|-- CONTEXT.md              # Domain vocabulary and architecture boundary
|-- deploy/aws/             # Cockpit/API deployment templates and helper scripts
|-- docs/                   # Agent, deployment, public profile, and settlement notes
|-- src/alphadb/            # Python package
|-- tests/                  # Pytest suite
|-- docker-compose.yml      # Local Postgres and Python API/compat services
`-- pyproject.toml          # Package metadata, scripts, and tool config
```

## Repository Hygiene

The public repository is designed to be useful without private runtime material.
Run the hygiene gate before opening a pull request:

```bash
alphadb-repo-hygiene check
```

Run the public-share audit before sending the repository link widely:

```bash
alphadb-repo-hygiene audit
```

Use `--strict-local` when ignored local sensitive files should fail the audit
too. The audit distinguishes tracked Git blockers from ignored local files such
as `.env`, private keys, model artifacts, generated datasets, and strategy logs.

## Roadmap

AlphaDB is early but functional. Active roadmap areas include authenticated
Kalshi WebSocket ingestion, broader market-family support, richer replay
diagnostics, research artifact manifests, live-data paper evidence, and a
documented live cutover path.

The current MVP remains authoritative until a deliberate cutover. AlphaDB may
shadow it, compare against it, and prepare target-platform infrastructure, but
this repository should not assume control of any existing live runner by default.

## Non-Goals

- AlphaDB does not publish a turnkey profitable strategy.
- AlphaDB does not require live exchange credentials for normal development or tests.
- AlphaDB does not store private account data, raw generated datasets, model binaries, or secrets in Git.
- AlphaDB does not make live order submission the default path.

## License

License TBD before public release or broad outside contribution. Until a license
is added, this code is not offered under an open-source license.
