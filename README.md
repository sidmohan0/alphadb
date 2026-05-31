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

By default, local Postgres is published on `localhost:55433` and Streamlit on
`localhost:8501`. Override those with `ALPHADB_POSTGRES_PORT` and
`ALPHADB_STREAMLIT_PORT` when needed.

## License

Private while the project is taking shape. License TBD before any public/open-source release.
