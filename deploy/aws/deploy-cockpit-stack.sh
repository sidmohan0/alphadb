#!/usr/bin/env bash
set -euo pipefail

PROFILE="${AWS_PROFILE:-alphadb}"
REGION="${AWS_REGION:-us-east-2}"
STACK_NAME="${STACK_NAME:-alphadb-cockpit}"
SERVICE_NAME="${SERVICE_NAME:-alphadb-cockpit}"
REPOSITORY="${ECR_REPOSITORY:-alphadb-cockpit}"
TEMPLATE_FILE="${TEMPLATE_FILE:-deploy/aws/ecs-fargate-dashboard.yaml}"
PLATFORM="${PLATFORM:-linux/arm64}"
ASSIGN_PUBLIC_IP="${ASSIGN_PUBLIC_IP:-DISABLED}"
PRIVATE_NAMESPACE_NAME="${PRIVATE_NAMESPACE_NAME:-alphadb.local}"
RUNTIME_MODE="${ALPHADB_RUNTIME_MODE:-gated-live}"
DRY_RUN="${DRY_RUN:-0}"
SKIP_BUILD="${SKIP_BUILD:-0}"
SKIP_PUSH="${SKIP_PUSH:-0}"
SKIP_MIGRATE="${SKIP_MIGRATE:-0}"
SKIP_RELEASE_CHECK="${SKIP_RELEASE_CHECK:-$SKIP_MIGRATE}"
SKIP_SMOKE="${SKIP_SMOKE:-0}"
FORCE_REBUILD="${FORCE_REBUILD:-0}"

context_hash() {
  local platform="$1"
  shift
  python3 - "$platform" "$@" <<'PY'
import hashlib
import pathlib
import subprocess
import sys

platform = sys.argv[1]
paths = sys.argv[2:]
completed = subprocess.run(
    [
        "git",
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        *paths,
    ],
    text=True,
    capture_output=True,
    check=False,
)
if completed.returncode != 0:
    raise SystemExit(completed.stderr or completed.stdout)
digest = hashlib.sha256()
digest.update(f"platform:{platform}\0".encode())
for raw_path in sorted(line for line in completed.stdout.splitlines() if line.strip()):
    path = pathlib.Path(raw_path)
    if not path.is_file():
        continue
    digest.update(f"path:{raw_path}\0".encode())
    digest.update(path.read_bytes())
    digest.update(b"\0")
print(digest.hexdigest()[:16])
PY
}

aws_cli() {
  aws --profile "$PROFILE" --region "$REGION" "$@"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 1
  fi
}

require_env() {
  if [[ -z "${!1:-}" ]]; then
    echo "missing required environment variable: $1" >&2
    exit 1
  fi
}

run() {
  echo "+ $*"
  if [[ "$DRY_RUN" != "1" ]]; then
    "$@"
  fi
}

ecr_image_exists() {
  local tag="$1"
  aws_cli ecr describe-images \
    --repository-name "$REPOSITORY" \
    --image-ids "imageTag=$tag" >/dev/null 2>&1
}

stack_output() {
  aws_cli cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" \
    --output text
}

task_override_json() {
  python3 - "$@" <<'PY'
import json
import sys

print(json.dumps({"containerOverrides": [{"name": "api", "command": sys.argv[1:]}]}))
PY
}

run_api_command() {
  local command_label="$*"
  local cluster task_definition security_group subnets overrides task_arn exit_code stopped_reason

  cluster="$(stack_output ClusterName)"
  task_definition="$(stack_output AlphaDbApiTaskDefinitionArn)"
  security_group="$(stack_output AlphaDbApiSecurityGroupId)"
  subnets="$(stack_output PrivateSubnetIds)"
  overrides="$(task_override_json "$@")"

  echo "ecs one-off: $command_label"
  task_arn="$(aws_cli ecs run-task \
    --cluster "$cluster" \
    --launch-type FARGATE \
    --task-definition "$task_definition" \
    --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$security_group],assignPublicIp=$ASSIGN_PUBLIC_IP}" \
    --overrides "$overrides" \
    --query 'tasks[0].taskArn' \
    --output text)"

  if [[ -z "$task_arn" || "$task_arn" == "None" ]]; then
    echo "failed to start ECS one-off task: $command_label" >&2
    exit 1
  fi

  aws_cli ecs wait tasks-stopped --cluster "$cluster" --tasks "$task_arn"
  exit_code="$(aws_cli ecs describe-tasks \
    --cluster "$cluster" \
    --tasks "$task_arn" \
    --query "tasks[0].containers[?name=='api'].exitCode | [0]" \
    --output text)"
  stopped_reason="$(aws_cli ecs describe-tasks \
    --cluster "$cluster" \
    --tasks "$task_arn" \
    --query 'tasks[0].stoppedReason' \
    --output text)"

  if [[ "$exit_code" != "0" ]]; then
    echo "ECS one-off failed: $command_label" >&2
    echo "task: $task_arn" >&2
    echo "exit_code: $exit_code" >&2
    echo "stopped_reason: $stopped_reason" >&2
    echo "check CloudWatch log group /ecs/$SERVICE_NAME/alphadb-api" >&2
    exit 1
  fi
}

require_command aws
require_command docker
require_command git
require_command python3
require_env VPC_ID
require_env PUBLIC_SUBNET_IDS
require_env PRIVATE_SUBNET_IDS
require_env DATABASE_URL_SECRET_ARN
require_env COCKPIT_PIN_SECRET_ARN
require_env COCKPIT_COOKIE_SECRET_ARN
require_env KALSHI_API_KEY_ID_SECRET_ARN
require_env KALSHI_PRIVATE_KEY_PEM_SECRET_ARN

COCKPIT_CONTEXT_HASH="$(context_hash "$PLATFORM" apps/dashboard)"
RUNTIME_CONTEXT_HASH="$(context_hash "$PLATFORM" Dockerfile pyproject.toml README.md src)"
COCKPIT_IMAGE_TAG="${COCKPIT_IMAGE_TAG:-cockpit-$COCKPIT_CONTEXT_HASH}"
ALPHADB_API_IMAGE_TAG="${ALPHADB_API_IMAGE_TAG:-runtime-$RUNTIME_CONTEXT_HASH}"

ACCOUNT_ID="${AWS_ACCOUNT_ID:-}"
if [[ -z "$ACCOUNT_ID" ]]; then
  ACCOUNT_ID="$(aws_cli sts get-caller-identity --query Account --output text)"
fi

COCKPIT_IMAGE_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPOSITORY:$COCKPIT_IMAGE_TAG"
ALPHADB_API_IMAGE_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPOSITORY:$ALPHADB_API_IMAGE_TAG"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "dry-run: would deploy $STACK_NAME in $REGION"
fi

if [[ "$SKIP_PUSH" != "1" && "$DRY_RUN" != "1" ]]; then
  if ! aws_cli ecr describe-repositories --repository-names "$REPOSITORY" >/dev/null 2>&1; then
    aws_cli ecr create-repository \
      --repository-name "$REPOSITORY" \
      --image-scanning-configuration scanOnPush=true >/dev/null
  fi

  aws_cli ecr get-login-password \
    | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
fi

COCKPIT_IMAGE_EXISTS=0
ALPHADB_API_IMAGE_EXISTS=0
if [[ "$SKIP_PUSH" != "1" && "$FORCE_REBUILD" != "1" && "$DRY_RUN" != "1" ]]; then
  if ecr_image_exists "$COCKPIT_IMAGE_TAG"; then
    COCKPIT_IMAGE_EXISTS=1
    echo "ecr reuse: $COCKPIT_IMAGE_URI"
  fi
  if ecr_image_exists "$ALPHADB_API_IMAGE_TAG"; then
    ALPHADB_API_IMAGE_EXISTS=1
    echo "ecr reuse: $ALPHADB_API_IMAGE_URI"
  fi
fi

if [[ "$SKIP_BUILD" != "1" && "$COCKPIT_IMAGE_EXISTS" != "1" ]]; then
  run docker build --platform "$PLATFORM" \
    -t "$REPOSITORY:$COCKPIT_IMAGE_TAG" \
    -f apps/dashboard/Dockerfile \
    apps/dashboard
fi

if [[ "$SKIP_BUILD" != "1" && "$ALPHADB_API_IMAGE_EXISTS" != "1" ]]; then
  run docker build --platform "$PLATFORM" \
    -t "$REPOSITORY:$ALPHADB_API_IMAGE_TAG" \
    .
fi

if [[ "$SKIP_PUSH" != "1" && "$COCKPIT_IMAGE_EXISTS" != "1" ]]; then
  run docker tag "$REPOSITORY:$COCKPIT_IMAGE_TAG" "$COCKPIT_IMAGE_URI"
  run docker push "$COCKPIT_IMAGE_URI"
fi

if [[ "$SKIP_PUSH" != "1" && "$ALPHADB_API_IMAGE_EXISTS" != "1" ]]; then
  run docker tag "$REPOSITORY:$ALPHADB_API_IMAGE_TAG" "$ALPHADB_API_IMAGE_URI"
  run docker push "$ALPHADB_API_IMAGE_URI"
fi

run aws --profile "$PROFILE" --region "$REGION" cloudformation deploy \
  --stack-name "$STACK_NAME" \
  --template-file "$TEMPLATE_FILE" \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    ServiceName="$SERVICE_NAME" \
    CockpitContainerImage="$COCKPIT_IMAGE_URI" \
    AlphaDbApiContainerImage="$ALPHADB_API_IMAGE_URI" \
    VpcId="$VPC_ID" \
    PublicSubnetIds="$PUBLIC_SUBNET_IDS" \
    PrivateSubnetIds="$PRIVATE_SUBNET_IDS" \
    AssignPublicIp="$ASSIGN_PUBLIC_IP" \
    DatabaseUrlSecretArn="$DATABASE_URL_SECRET_ARN" \
    CockpitPinSecretArn="$COCKPIT_PIN_SECRET_ARN" \
    CockpitCookieSecretArn="$COCKPIT_COOKIE_SECRET_ARN" \
    KalshiApiKeyIdSecretArn="$KALSHI_API_KEY_ID_SECRET_ARN" \
    KalshiPrivateKeyPemSecretArn="$KALSHI_PRIVATE_KEY_PEM_SECRET_ARN" \
    PrivateNamespaceName="$PRIVATE_NAMESPACE_NAME" \
    RuntimeMode="$RUNTIME_MODE" \
    AwsRegionValue="$REGION"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "dry-run: skipping ECS one-off tasks and Cockpit smoke"
  exit 0
fi

if [[ "$SKIP_RELEASE_CHECK" != "1" ]]; then
  run_api_command alphadb-deploy release-check --series KXBTC15M
fi

if [[ "$SKIP_SMOKE" != "1" ]]; then
  DASHBOARD_URL="$(stack_output DashboardUrl)"
  COCKPIT_URL="$DASHBOARD_URL" \
  COCKPIT_PIN_SECRET_ARN="$COCKPIT_PIN_SECRET_ARN" \
  AWS_PROFILE="$PROFILE" \
  AWS_REGION="$REGION" \
    deploy/aws/smoke-cockpit-stack.sh
fi

aws_cli cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs' \
  --output table
