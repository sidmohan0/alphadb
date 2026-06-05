# Local Cockpit Stack

The local Cockpit stack is the target-platform development path for ALP-191.
It starts Postgres, the Python AlphaDB API, and the Next.js Cockpit with one
Compose profile while preserving the boundary:

```text
Cockpit -> AlphaDB API -> Operational State
```

## Start

```bash
docker compose --profile cockpit up --build cockpit
```

Open `http://localhost:3000`.

The profile starts:

- `postgres`: local Operational State, published on `localhost:55433`.
- `alphadb-api`: Python AlphaDB API and legacy compatibility surface, published
  on `localhost:8501`.
- `cockpit`: Next.js Cockpit, published on `localhost:3000`.

The Cockpit container receives `ALPHADB_API_BASE_URL=http://alphadb-api:8501`
and proxies browser calls through `/api/alphadb/*`. It does not receive
`DATABASE_URL` and must not connect directly to Postgres.

Published host ports can be changed with:

```bash
ALPHADB_POSTGRES_PORT=55434 \
ALPHADB_DASHBOARD_PORT=18501 \
ALPHADB_COCKPIT_PORT=3001 \
docker compose --profile cockpit up --build cockpit
```

## Smoke Check

With the stack running, verify the path an AFK agent needs:

```bash
./scripts/smoke-local-cockpit.sh
```

The script checks:

- Python compatibility health at `http://localhost:8501/healthz`.
- Cockpit reachability at `http://localhost:3000`.
- Cockpit proxy reachability at `http://localhost:3000/api/alphadb/health`,
  including Python health and Postgres status.

Set `COCKPIT_URL` or `ALPHADB_API_URL` when using non-default ports.

## Stop

```bash
docker compose --profile cockpit down
```

Add `-v` only when you intentionally want to delete the local Postgres and
frontend dependency volumes.
