# AlphaDB

AlphaDB is a fresh workspace for a replayable, risk-controlled prediction-market trading platform.

The initial platform direction is:

- Python modular monolith first.
- Postgres-backed operational state for the target platform.
- Dev Container plus Docker Compose as the reproducible development environment.
- Streamlit-first target-platform dashboard.
- Raw event logs for replay and promotion evidence.
- `MarketSpec` as the canonical abstraction, with `KXBTC15M` as the first concrete market family.

This repository has been reset intentionally. Prior AlphaDB history is not part of this project.

## Development

Open the repository in a Dev Container, or run locally with Python 3.12+:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
```

Docker Compose provides Postgres for target-platform development:

```bash
docker compose up -d postgres
```

Run the same install/test path inside the Compose app container:

```bash
docker compose run --rm app bash -lc "python -m pip install -e '.[dev,dashboard]' && pytest -q && alphadb-health"
```

Start the Streamlit target-platform dashboard:

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

By default, local Postgres is published on `localhost:55433` and Streamlit on
`localhost:8501`. Override those with `ALPHADB_POSTGRES_PORT` and
`ALPHADB_STREAMLIT_PORT` when needed. Override the Kalshi REST base URL with
`ALPHADB_KALSHI_BASE_URL`.

## License

Private while the project is taking shape. License TBD before any public/open-source release.
