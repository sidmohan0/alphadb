# AlphaDB AWS Dashboard Deployment

This runbook prepares the target-platform dashboard for AWS without changing the
Current MVP authority boundary. The deployed dashboard is an operations and
research surface. It does not approve live-order cutover, and the runtime stays
fail-closed for live order submission unless explicit cutover settings are added
later.

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
ALPHADB_STREAMLIT_PORT=8501
ALPHADB_RUNTIME_MODE=paper
ALPHADB_ENABLE_LIVE_ORDERS=0
ALPHADB_HUMAN_CUTOVER_APPROVED=0
ALPHADB_DASHBOARD_PIN=<Secrets Manager value: exactly four digits>
ALPHADB_DASHBOARD_COOKIE_SECRET=<Secrets Manager value: random 32+ bytes>
ALPHADB_DASHBOARD_COOKIE_TTL_SECONDS=604800
```

`ALPHADB_RUNTIME_MODE=paper` is the intended dashboard readiness mode. `fixture`
is acceptable for pure container smoke tests. `gated-live`, live credentials,
`ALPHADB_ENABLE_LIVE_ORDERS=1`, and `ALPHADB_HUMAN_CUTOVER_APPROVED=1` are out of
scope for this dashboard deployment.

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

Run the production-style container locally:

```bash
docker build -t alphadb-dashboard:local .
docker compose --profile dashboard-runtime up --build dashboard-runtime
```

Open `http://localhost:8501`, enter the four-digit PIN, and confirm the dashboard
shows health, state counts, runtime guard status, run monitor, and signal and
execution rows. The smoke command should report:

- `dashboard_auth.ok=true`
- `migrations.ok=true`
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
- Managed Postgres reachable from those private subnets.
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
    DatabaseUrlSecretArn=<database-url-secret-arn> \
    DashboardPinSecretArn=<dashboard-pin-secret-arn> \
    DashboardCookieSecretArn=<dashboard-cookie-secret-arn> \
    AwsRegionValue=us-east-2 \
    RuntimeMode=paper
```

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
- `alphadb-deploy seed-readiness` creates a tracer run visible in the dashboard.
- `alphadb-deploy smoke` passes in AWS-shaped paper mode.
- Dashboard login requires a four-digit PIN in `ALPHADB_ENV=aws`.
- Runtime guard reports `can_submit_live_orders=false`.
- ECS/Fargate service uses `us-east-2`, private task subnets, managed Postgres
  via `DATABASE_URL`, and Secrets Manager for dashboard credentials.
