# Fly Deployment Plan

## Goal

Deploy the current AlphaDB platform to Fly.io with:

- one Fly app for `apps/api`
- one Fly app for `apps/web`
- Fly Managed Postgres for durable state
- Upstash Redis on Fly for discovery cache and locks
- the TUI remaining a local client pointed at the deployed API

This plan assumes the current repo shape on `main`:

- `apps/api` is the backend runtime
- `apps/web` is the browser market workspace
- `apps/tui` is not deployed to Fly and continues to run locally

## Recommended Topology

### Fly apps

- `alphadb-api`
  - runs `apps/api`
  - public HTTPS
  - owns `/api/*`
  - owns SSE market stream delivery
  - talks to Postgres and Redis over Fly private networking

- `alphadb-web`
  - serves the built `apps/web` Vite bundle
  - public HTTPS
  - points at `https://api.<domain>/api` or `https://alphadb-api.fly.dev/api`

### Managed data services

- Fly Managed Postgres
  - primary durable store for user state and discovery persistence
  - same primary region as `alphadb-api`

- Upstash Redis on Fly
  - discovery cache and coordination
  - same primary region as `alphadb-api`

### Client shape

- Browser client talks to `alphadb-api`
- TUI runs locally and uses `ALPHADB_API_BASE_URL=https://api.<domain>/api`
- direct-provider TUI mode remains available as fallback, but production should treat the API as the default path

## Region Recommendation

Use `sjc` as the first production region unless you have a known user concentration elsewhere.

Reason:

- current operator location is US West
- Fly Managed Postgres supports `sjc`
- keeping API, Postgres, and Redis in one region is the right latency posture for the first production cut

If you prefer Los Angeles over San Jose for business or networking reasons, `lax` is also a reasonable primary region. Do not split the API, Postgres, and Redis across regions for the first deploy.

## What Must Be Built Before Deploy

### 1. API deployment files

Add:

- `apps/api/Dockerfile`
- `deploy/fly/api.fly.toml`

The API image should:

- install workspace dependencies
- build `packages/sdk`, `packages/market-core`, and `apps/api`
- run `node apps/api/dist/index.js`

### 2. Web deployment files

Add:

- `apps/web/Dockerfile`
- `deploy/fly/web.fly.toml`

The web image should:

- install workspace dependencies
- build `apps/web`
- serve `apps/web/dist` from a small HTTP server container

Recommendation:

- use a multi-stage Dockerfile
- build in Node
- serve with `nginx`, `caddy`, or a small static HTTP server

### 3. API Fly config

The API `fly.toml` should define:

- `app = "alphadb-api"`
- `primary_region = "sjc"`
- `internal_port = 4000`
- `PORT = "4000"`
- an `http_service`
- HTTP health checks against `/api/health`
- a release command for schema setup
- initial VM sizing

Recommended first-pass config:

- one region
- two Machines once stability is proven
- `shared-cpu-1x` or `shared-cpu-2x`
- rolling deploy first, then blue/green later if desired

### 4. Web Fly config

The web `fly.toml` should define:

- `app = "alphadb-web"`
- `primary_region = "sjc"`
- internal port for the static server
- `http_service`
- health checks against `/`

### 5. Runtime secret model

Set on `alphadb-api`:

- `DATABASE_URL`
- `REDIS_URL`
- `ALPHADB_API_USER_STATE_BACKEND=postgres`
- `ALPHADB_AUTH_MODE`
- `ALPHADB_API_TOKENS_JSON` or `ALPHADB_API_TOKENS_PATH`
- `KALSHI_API_KEY_ID` if Kalshi backend streaming is enabled
- `KALSHI_PRIVATE_KEY_PEM` or mounted key file secret
- `DISCOVERY_REQUIRE_SCHEMA=1`

Set on `alphadb-web`:

- `VITE_ALPHADB_API_BASE_URL=https://alphadb-api.fly.dev/api` for the first deploy

Notes:

- `fly secrets set` triggers a machine restart/redeploy
- secrets can also be mounted as files via `[[files]]`, which is the cleanest option if the Kalshi private key should exist on disk instead of in a plain env var

### 6. Release command

The API deploy should run schema setup before traffic moves:

- `npm run markets:ensure-state-schema --workspace @alphadb/api`
- `npm run polymarket:discovery-migrate --workspace @alphadb/api`

That should be wrapped into one release command entrypoint or a small deploy script.

Important:

- Fly release commands run in a temporary Machine with network, env, and secrets, but no attached volumes
- a failing release command must stop the deploy

### 7. Health checks

Use Fly HTTP service checks:

- API: `GET /api/health`
- Web: `GET /`

Checks should have:

- explicit `grace_period`
- explicit `interval`
- explicit `timeout`

Do not rely on process startup alone. The API already exposes `/api/health`, so this is ready to wire in.

### 8. CORS and origin posture

Before deploying separately hosted web and API apps, verify API CORS allows:

- Fly web domain
- custom production web domain
- optional localhost dev origins

If CORS is currently permissive, tighten it before public launch.

### 9. Observability minimums

Before public deploy, add at least:

- request logging on the API
- provider error logging
- stream disconnect/error logging
- cache hit/miss logging or counters
- Fly log access runbook

This does not need full tracing on day one, but it does need enough signal to debug failed releases and live stream regressions.

## Proposed File Layout

```text
deploy/
  fly/
    api.fly.toml
    web.fly.toml
apps/
  api/
    Dockerfile
  web/
    Dockerfile
```

## Deployment Sequence

### Phase 1. Prepare infrastructure

1. Create `alphadb-api` Fly app.
2. Create `alphadb-web` Fly app.
3. Provision Fly Managed Postgres in `sjc`.
4. Provision Upstash Redis in `sjc`.
5. Capture the resulting `DATABASE_URL` and `REDIS_URL`.

### Phase 2. Add deployment artifacts

1. Add API Dockerfile.
2. Add web Dockerfile.
3. Add `api.fly.toml`.
4. Add `web.fly.toml`.
5. Add a small release script for schema work.

### Phase 3. First API deploy

1. Set API secrets.
2. Deploy `alphadb-api`.
3. Verify:
   - `/api/health`
   - `/api/markets/unified/trending`
   - `/api/markets/stream`
4. Run a smoke test from the local TUI against the Fly API.

### Phase 4. First web deploy

1. Set `VITE_ALPHADB_API_BASE_URL` for `alphadb-web`.
2. Deploy `alphadb-web`.
3. Verify:
   - page load
   - unified trending
   - history charts
   - SSE updates
   - saved/recent state with a test token

### Phase 5. Domain and auth hardening

1. Attach custom domains.
2. Update API base URLs.
3. Rotate any bootstrap test tokens.
4. Confirm PAT auth flow end-to-end from web and TUI.

## Recommended First Production Defaults

### API

- 1 region: `sjc`
- 1 Machine for first cut, then 2 after the first stable deploy window
- `shared-cpu-2x`
- `auto_stop_machines = false`
- `auto_start_machines = true`

Reason:

- SSE and provider polling are not a great fit for aggressive autostop during the first production phase
- keep the service warm and predictable first, optimize cost second

### Web

- 1 region: `sjc`
- 1 Machine
- `shared-cpu-1x`
- static asset caching enabled at the web server layer

## CI/CD Recommendation

Use GitHub Actions after the manual first deploy succeeds.

Suggested workflow split:

- `deploy-api.yml`
  - triggers on changes under `apps/api`, `packages/market-core`, `packages/sdk`
  - runs tests/build
  - deploys `alphadb-api`

- `deploy-web.yml`
  - triggers on changes under `apps/web`, `packages/market-core`, `packages/sdk`
  - builds web
  - deploys `alphadb-web`

This matches Fly’s monorepo deployment model cleanly.

## Risks To Watch

### SSE fanout pressure

The live stream path is now stable in dev, but production traffic will need monitoring for:

- slow consumers
- excess concurrent streams
- provider reconnect churn

### Discovery worker coupling

The API process currently contains both the public API and optional discovery worker toggles. For the first production cut, keep discovery workers disabled unless you explicitly need them.

### Redis requirement

The API bootstrap requires `REDIS_URL` unless `DISCOVERY_RUN_ALLOW_IN_MEMORY_CACHE=1`. Production should not use the in-memory exception.

### Auth token management

PAT mode is acceptable for the first production cut, but treat bootstrap tokens as operational secrets, not user-facing permanent auth UX.

## Acceptance Criteria

The Fly deployment is ready when all of the following are true:

- `alphadb-api` deploys successfully with schema release command
- `alphadb-web` deploys successfully and points at the API
- `/api/health` passes Fly health checks
- web unified workspace loads and streams updates
- TUI can connect to the Fly API with `ALPHADB_API_BASE_URL`
- Postgres-backed saved/recent state works through the deployed backend
- logs are sufficient to debug stream and provider failures

## Immediate Next Step

Implement the deployment artifacts:

1. `apps/api/Dockerfile`
2. `apps/web/Dockerfile`
3. `deploy/fly/api.fly.toml`
4. `deploy/fly/web.fly.toml`
5. API release script for schema setup

## References

- Fly deploy: https://fly.io/docs/launch/deploy/
- Fly monorepo deploys: https://fly.io/docs/launch/monorepo/
- Fly app config: https://fly.io/docs/reference/configuration/
- Fly health checks: https://fly.io/docs/reference/health-checks/
- Fly secrets: https://fly.io/docs/apps/secrets/
- Fly Managed Postgres: https://fly.io/docs/mpg/
- Upstash Redis on Fly: https://fly.io/docs/upstash/redis/
