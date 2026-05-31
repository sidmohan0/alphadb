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
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
```

Docker Compose provides Postgres for target-platform development:

```bash
docker compose up -d postgres
```

## License

Private while the project is taking shape. License TBD before any public/open-source release.
