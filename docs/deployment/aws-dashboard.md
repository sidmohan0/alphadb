# AlphaDB AWS Cockpit Deployment

This is the canonical AWS operator path for the MVP cutover.

The public AWS URL serves the production-built Next.js Cockpit. Browser API
calls stay same-origin at `/api/alphadb/*`; the Cockpit server proxies those
requests to a private Python AlphaDB API ECS service through VPC-only service
discovery. The Python service remains the AlphaDB API and Postgres owner. The
Cockpit does not receive database credentials.

The previous Python-only public dashboard path is deprecated after this cutover.
The Python `alphadb-dashboard` command may still serve legacy HTML routes as a
private compatibility surface, but it is not the public operator UI.

## Boundary

```text
browser -> public ALB -> Cockpit ECS service -> /api/alphadb/* proxy -> private AlphaDB API ECS service -> managed Postgres
```

- Public surface: Cockpit only.
- Private product API: AlphaDB API only.
- Private state: managed Postgres, provided before this stack is deployed.
- Live worker: unchanged and out of scope for this deployment.

## Required Inputs

Use existing AWS resources and Secrets Manager values. Do not pass raw secret
values to the deploy script.

```text
AWS_PROFILE=alphadb
AWS_REGION=us-east-2
STACK_NAME=alphadb-cockpit
SERVICE_NAME=alphadb-cockpit
ECR_REPOSITORY=alphadb-cockpit
VPC_ID=<vpc-id>
PUBLIC_SUBNET_IDS=<public-subnet-a>,<public-subnet-b>
PRIVATE_SUBNET_IDS=<private-subnet-a>,<private-subnet-b>
DATABASE_URL_SECRET_ARN=<secret arn containing DATABASE_URL>
COCKPIT_PIN_SECRET_ARN=<secret arn containing four-digit PIN>
COCKPIT_COOKIE_SECRET_ARN=<secret arn containing random cookie secret>
KALSHI_API_KEY_ID_SECRET_ARN=<secret arn containing KALSHI_API_KEY_ID>
KALSHI_PRIVATE_KEY_PEM_SECRET_ARN=<secret arn containing Kalshi private key PEM>
```

The AlphaDB API task receives the Kalshi private key as an ECS-injected PEM
environment secret. Its task command materializes that PEM into a restrictive
task-local `/tmp/alphadb-kalshi-private-key.pem` file and exports
`KALSHI_PRIVATE_KEY_PATH` before starting `alphadb-dashboard`, so the Cockpit
portfolio balance path can use the existing AlphaDB API image.

Optional MVP knobs:

```text
ASSIGN_PUBLIC_IP=DISABLED
PRIVATE_NAMESPACE_NAME=alphadb.local
ALPHADB_RUNTIME_MODE=gated-live
PLATFORM=linux/arm64
DRY_RUN=1
SKIP_BUILD=1
SKIP_PUSH=1
SKIP_MIGRATE=1
SKIP_SMOKE=1
```

`ASSIGN_PUBLIC_IP=ENABLED` is only for smoke deployments in public subnets
without NAT. The preferred shape is private task subnets with managed egress.

To deploy only task-definition or parameter changes while reusing known-good
images, set the existing image tags and skip build/push:

```bash
COCKPIT_IMAGE_TAG=<existing-cockpit-image-tag> \
ALPHADB_API_IMAGE_TAG=<existing-api-image-tag> \
SKIP_BUILD=1 \
SKIP_PUSH=1 \
deploy/aws/deploy-cockpit-stack.sh
```

## Deploy

Run one command from the repository root:

```bash
AWS_PROFILE=alphadb \
AWS_REGION=us-east-2 \
VPC_ID=<vpc-id> \
PUBLIC_SUBNET_IDS=<public-subnet-a>,<public-subnet-b> \
PRIVATE_SUBNET_IDS=<private-subnet-a>,<private-subnet-b> \
DATABASE_URL_SECRET_ARN=<database-url-secret-arn> \
COCKPIT_PIN_SECRET_ARN=<cockpit-pin-secret-arn> \
COCKPIT_COOKIE_SECRET_ARN=<cockpit-cookie-secret-arn> \
KALSHI_API_KEY_ID_SECRET_ARN=<kalshi-api-key-id-secret-arn> \
KALSHI_PRIVATE_KEY_PEM_SECRET_ARN=<kalshi-private-key-pem-secret-arn> \
deploy/aws/deploy-cockpit-stack.sh
```

The script:

- Builds the Cockpit image from `apps/dashboard/Dockerfile`.
- Builds the AlphaDB API image from the root `Dockerfile`.
- Tags both images separately in one ECR repository.
- Deploys `deploy/aws/ecs-fargate-dashboard.yaml`.
- Runs one-off AlphaDB API tasks for `alphadb-deploy migrate`,
  `alphadb-deploy seed-readiness --series KXBTC15M`, and
  `alphadb-deploy smoke`.
- Runs public Cockpit smoke against the ALB URL.

Use a dry run to check inputs and rendered commands without touching AWS:

```bash
DRY_RUN=1 \
VPC_ID=vpc-example \
PUBLIC_SUBNET_IDS=subnet-public-a,subnet-public-b \
PRIVATE_SUBNET_IDS=subnet-private-a,subnet-private-b \
DATABASE_URL_SECRET_ARN=arn:aws:secretsmanager:us-east-2:123456789012:secret:database \
COCKPIT_PIN_SECRET_ARN=arn:aws:secretsmanager:us-east-2:123456789012:secret:pin \
COCKPIT_COOKIE_SECRET_ARN=arn:aws:secretsmanager:us-east-2:123456789012:secret:cookie \
KALSHI_API_KEY_ID_SECRET_ARN=arn:aws:secretsmanager:us-east-2:123456789012:secret:kalshi-api-key-id \
KALSHI_PRIVATE_KEY_PEM_SECRET_ARN=arn:aws:secretsmanager:us-east-2:123456789012:secret:kalshi-private-key-pem \
deploy/aws/deploy-cockpit-stack.sh
```

For local Cockpit auth preflight, start the production build with Cockpit auth
env vars and run:

```bash
COCKPIT_URL=http://localhost:3000 \
ALPHADB_COCKPIT_PIN=1234 \
apps/dashboard/scripts/smoke-auth.sh
```

## Smoke

The deploy script runs the smoke gate by default. To rerun only the public
Cockpit smoke:

```bash
AWS_PROFILE=alphadb \
AWS_REGION=us-east-2 \
STACK_NAME=alphadb-cockpit \
COCKPIT_PIN_SECRET_ARN=<cockpit-pin-secret-arn> \
deploy/aws/smoke-cockpit-stack.sh
```

The smoke verifies:

- `GET /healthz` reaches the public Cockpit service.
- Unauthenticated `GET /api/alphadb/health` returns `401`.
- PIN login sets a signed cookie.
- The signed cookie can open the Cockpit.
- The signed cookie reaches proxied `/api/alphadb/health`.
- The proxied Python health response reports Postgres as `ok`.
- The signed cookie reaches proxied `/api/alphadb/live` and confirms the
  portfolio path no longer reports missing Kalshi credentials. The smoke output
  prints only redacted status/detail and does not log cash, assets, or portfolio
  balance values.

The API one-off `alphadb-deploy smoke` verifies migrations, runtime config, and
that live order submission remains fail-closed.

## Rollback

For this single-operator MVP, rollback stays image/service oriented:

- Re-run `deploy/aws/deploy-cockpit-stack.sh` with the previous known-good
  `COCKPIT_IMAGE_TAG` and `ALPHADB_API_IMAGE_TAG`.
- Or set the stack `DesiredCount` to `0` if the operator URL should be removed
  quickly.
- Keep managed Postgres intact unless an operator explicitly chooses teardown.
- Inspect `/ecs/<service>/cockpit`, `/ecs/<service>/alphadb-api`, and the smoke
  output before redeploying.

## Explicit Deferrals

- No live worker deployment, schedule, image, or order-authority changes.
- No new managed Postgres provisioning.
- No CI/CD or GitHub Actions workflow.
- No custom domain, TLS, ACM, or Route53.
- No OAuth, RBAC, ALB auth, or approval workflow.
- No public AlphaDB API endpoint.
- No blue/green, canary, or parallel public Python dashboard.
- No broad AlphaDB API hardening or route redesign.
