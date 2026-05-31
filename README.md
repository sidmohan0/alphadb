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

By default, local Postgres is published on `localhost:55433` and Streamlit on
`localhost:8501`. Override those with `ALPHADB_POSTGRES_PORT` and
`ALPHADB_STREAMLIT_PORT` when needed. Override the Kalshi REST base URL with
`ALPHADB_KALSHI_BASE_URL`.

## License

Private while the project is taking shape. License TBD before any public/open-source release.
