# AlphaDB AWS Dashboard Deployment

This runbook captures the current AWS-ready deployment path for AlphaDB's
legacy Python dashboard service and AlphaDB API compatibility surface. The
canonical product UI is now the Next.js Cockpit. Local and future AWS operator
work should treat Cockpit as the user-facing surface and the Python service as
the API/runtime owner until the AWS deployment wiring serves Cockpit at the
public dashboard URL.

## Region Decision

Default deployment region: `us-east-2`.

Grounding as of 2026-06-01:

- Kalshi's current documentation points production REST traffic at
  `https://external-api.kalshi.com/trade-api/v2`, with WebSocket traffic at the
  matching `external-api-ws.kalshi.com` host.
- A live DNS check from this workspace returned both production hostnames as
  CNAMEs to `elections-external-api-107430227.us-east-2.elb.amazonaws.com`.
- AWS documents `us-east-2` as US East (Ohio).

Re-check before any live cutover or latency-sensitive move:

```bash
dig +short external-api.kalshi.com CNAME
dig +short external-api-ws.kalshi.com CNAME
curl -sS -o /dev/null \
  -w '%{remote_ip} connect=%{time_connect} tls=%{time_appconnect} first_byte=%{time_starttransfer} total=%{time_total}\n' \
  https://external-api.kalshi.com/trade-api/v2/exchange/status
```

If the CNAME stops naming `us-east-2`, update `DEFAULT_AWS_REGION`, the AWS
template parameter default, and this runbook before deploying latency-sensitive
collectors or strategy workers.

Sources:

- [Kalshi API environments](https://docs.kalshi.com/getting_started/api_environments)
- [Kalshi API docs](https://docs.kalshi.com/api-reference/exchange/get-exchange-status)
- [Kalshi market data quick start](https://docs.kalshi.com/getting_started/quick_start_market_data)
- [AWS Region table](https://docs.aws.amazon.com/global-infrastructure/latest/regions/aws-regions.html)
- [DNS snapshot for external-api.kalshi.com](https://www.vedbex.com/dns/external-api.kalshi.com)

## Required Runtime Values

For AWS-like environments, use Secrets Manager for secret values:

```text
ALPHADB_ENV=aws
AWS_REGION=us-east-2
ALPHADB_AWS_REGION=us-east-2
DATABASE_URL=<Secrets Manager value>
ALPHADB_DASHBOARD_PORT=8501
ALPHADB_RUNTIME_MODE=gated-live
ALPHADB_ENABLE_LIVE_ORDERS=0
ALPHADB_HUMAN_CUTOVER_APPROVED=0
ALPHADB_DASHBOARD_PIN=<Secrets Manager value: exactly four digits>
ALPHADB_DASHBOARD_COOKIE_SECRET=<Secrets Manager value: random 32+ bytes>
ALPHADB_DASHBOARD_COOKIE_TTL_SECONDS=604800
```

`ALPHADB_RUNTIME_MODE=gated-live` keeps the dashboard environment aligned with
the live control plane. The dashboard web task still cannot submit orders because
`ALPHADB_ENABLE_LIVE_ORDERS=0`, `ALPHADB_HUMAN_CUTOVER_APPROVED=0`, and Kalshi
live credentials are not attached to the dashboard service. `fixture`, `shadow`,
and `paper` are acceptable only for local/container readiness checks, not the AWS
operator console.

The dashboard-owned runtime config stored in Postgres contains only non-secret
MVP knobs:

- Max order dollars.
- Max market exposure dollars.
- Max daily loss dollars.
- Min edge.
- Max markets.

Database URLs, Kalshi credentials, private keys, dashboard PINs, cookie secrets,
subnets, security groups, and task wiring stay in Secrets Manager or AWS
infrastructure configuration. The live worker reads the latest active Postgres
config at run start and records the config id/version/snapshot in each run
manifest.

## Local AWS-Shaped Readiness

Install the local package with dashboard and dev dependencies:

```bash
.venv/bin/python -m pip install -e '.[dev,dashboard]'
```

Start local Postgres:

```bash
docker compose up -d postgres
```

Run the AWS-shaped checks with live orders disabled:

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

.venv/bin/alphadb-deploy migrate
.venv/bin/alphadb-deploy seed-readiness --series KXBTC15M
.venv/bin/alphadb-deploy smoke
```

Run the production-style Python API and legacy compatibility container locally
when you only need the Python surface:

```bash
docker build -t alphadb-dashboard:local .
docker compose --profile dashboard-runtime up --build dashboard-runtime
```

For the canonical local operator surface, start the one-command Cockpit stack:

```bash
docker compose --profile cockpit up --build cockpit
./scripts/smoke-local-cockpit.sh
```

Open `http://localhost:3000` and confirm the Cockpit opens on the Live workspace.
The Python service remains available at `http://localhost:8501` for AlphaDB API
proxying and legacy compatibility while the MVP transition is in progress. See
[local-cockpit.md](local-cockpit.md) for the local stack and proxy smoke path.

The AWS-shaped smoke command should report:

- `dashboard_auth.ok=true`
- `migrations.ok=true`
- `runtime_config.ok=true`
- `runtime_guard.can_submit_live_orders=false`
- `ok=true`

The container also includes a read-only machine status command for SSM-based
monitoring. It does not authenticate to the human dashboard UI and does not
start, stop, or modify live strategy state:

```bash
docker exec alphadb-dashboard alphadb-monitor status --json
```

The command exits `0` only when health checks pass, exactly one
`alphadb-strategy gated-live-loop` process is visible, and the latest strategy
run status is `running`. It emits JSON suitable for Codex or AWS-side watchdog
logs.

## AWS Deployment Skeleton

The CloudFormation skeleton in
`deploy/aws/ecs-fargate-dashboard.yaml` assumes these dependencies already exist:

- VPC with public subnets for an ALB.
- Private subnets for Fargate tasks.
- Managed Postgres reachable from those private subnets by both dashboard tasks
  and live worker tasks.
- `DATABASE_URL`, dashboard PIN, and dashboard cookie secret stored in Secrets
  Manager.
- ECR image built from this repository's `Dockerfile`.

Build and push an image:

```bash
export AWS_REGION=us-east-2
export AWS_ACCOUNT_ID=<account-id>
export ECR_REPOSITORY=alphadb-dashboard
export IMAGE_TAG=$(git rev-parse --short HEAD)

aws ecr create-repository --repository-name "$ECR_REPOSITORY" --region "$AWS_REGION"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
docker build -t "$ECR_REPOSITORY:$IMAGE_TAG" .
docker tag "$ECR_REPOSITORY:$IMAGE_TAG" \
  "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY:$IMAGE_TAG"
docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY:$IMAGE_TAG"
```

Create or update the stack:

```bash
aws cloudformation deploy \
  --region "$AWS_REGION" \
  --stack-name alphadb-dashboard \
  --template-file deploy/aws/ecs-fargate-dashboard.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ContainerImage="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY:$IMAGE_TAG" \
    VpcId=<vpc-id> \
    PublicSubnetIds=<public-subnet-a>,<public-subnet-b> \
    PrivateSubnetIds=<private-subnet-a>,<private-subnet-b> \
    AssignPublicIp=DISABLED \
    DatabaseUrlSecretArn=<database-url-secret-arn> \
    DashboardPinSecretArn=<dashboard-pin-secret-arn> \
    DashboardCookieSecretArn=<dashboard-cookie-secret-arn> \
    AwsRegionValue=us-east-2 \
    RuntimeMode=gated-live
```

Use `AssignPublicIp=ENABLED` only for a public-subnet smoke deployment without
NAT egress. The production preference remains private task subnets with managed
egress.

Before enabling the service for users, run one-off tasks from the same task
definition:

```bash
alphadb-deploy migrate
alphadb-deploy seed-readiness --series KXBTC15M
alphadb-deploy smoke
```

When running those commands through ECS, override the container command to the
desired `alphadb-deploy ...` command and use the same private subnets and service
security group as the dashboard service.

For ALP-156, the human deployment verifier should also run or schedule the
fair-value live worker template with `DatabaseUrlSecretArn` pointing to this same
managed Postgres secret. The worker task security group/subnets must be able to
reach the database, and the task command should include
`--runtime-config-source postgres`.

The fair-value live worker uses a single S3 live-run lock under the configured
artifact prefix to prevent overlapping scheduled ECS tasks from submitting
duplicate orders. A task that cannot acquire that lock should leave auditable
run artifacts, but it must not replace the dashboard's latest actionable live
status with `live_run_lock_held` / `not_submitted`.

Use `docs/deployment/live-money-cutover-checklist.md` as the ALP-157 checklist
and evidence template before any live-money authority change.

## Rollback

Rollback is image and service oriented:

- Re-deploy the stack with the previous known-good `ContainerImage` tag.
- If the dashboard should be removed quickly, set `DesiredCount=0`.
- Keep the managed Postgres instance intact unless an operator explicitly
  chooses data teardown.
- Inspect `/ecs/alphadb-dashboard` CloudWatch logs and the JSON output from
  `alphadb-deploy smoke` before reattempting deployment.

## Acceptance Checklist

- Docker image builds from the repository root.
- `alphadb-deploy migrate` applies all operational-state migrations.
- `alphadb-deploy smoke` verifies the live runtime config table exists and an
  active config can be read.
- `alphadb-deploy seed-readiness` creates a tracer run visible in the dashboard.
- `alphadb-deploy smoke` passes in AWS-shaped dashboard mode without live-order
  credentials on the dashboard service.
- Dashboard login requires a four-digit PIN in `ALPHADB_ENV=aws`.
- Runtime guard reports `can_submit_live_orders=false`.
- ECS/Fargate service uses `us-east-2`, private task subnets, managed Postgres
  via `DATABASE_URL`, and Secrets Manager for dashboard credentials.
