#!/usr/bin/env bash
set -euo pipefail

PROFILE="${AWS_PROFILE:-alphadb}"
REGION="${AWS_REGION:-us-east-2}"
STACK_NAME="${STACK_NAME:-alphadb-fair-value-live}"
SERVICE_NAME="${SERVICE_NAME:-alphadb-fair-value-live}"
REPOSITORY="${ECR_REPOSITORY:-alphadb-fair-value-live}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)-$(date -u +%Y%m%d%H%M%S)}"
TEMPLATE_FILE="${TEMPLATE_FILE:-deploy/aws/fair-value-live-trading-job.yaml}"

aws_cli() {
  aws --profile "$PROFILE" --region "$REGION" "$@"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

secret_arn() {
  aws_cli secretsmanager describe-secret \
    --secret-id "$1" \
    --query ARN \
    --output text
}

require_command aws
require_command docker
require_command git
require_command python3

LIVE_AUTHORITY_BACKEND_VALUE="${LIVE_AUTHORITY_BACKEND:-postgres}"
if [[ "$LIVE_AUTHORITY_BACKEND_VALUE" != "postgres" ]]; then
  echo "LIVE_AUTHORITY_BACKEND must be postgres; S3 live-run lock authority has been retired." >&2
  echo "Keep REPORT_BUCKET_NAME/REPORT_PREFIX or --s3-prefix for artifact uploads only." >&2
  exit 1
fi

if [[ "${SCHEDULE_STATE:-DISABLED}" == "ENABLED" ]]; then
  if [[ -n "${FAIR_VALUE_LIVE_SMOKE_EVIDENCE:-}" ]]; then
    python3 scripts/validate-fair-value-live-smoke.py "$FAIR_VALUE_LIVE_SMOKE_EVIDENCE"
  elif [[ "${PRESERVE_ENABLED_SCHEDULE:-0}" == "1" ]]; then
    CURRENT_SCHEDULE_STATE="$(aws_cli events describe-rule \
      --name "$SERVICE_NAME" \
      --query State \
      --output text 2>/dev/null || true)"
    if [[ "$CURRENT_SCHEDULE_STATE" != "ENABLED" ]]; then
      echo "Refusing to preserve ENABLED schedule; current state is ${CURRENT_SCHEDULE_STATE:-unknown}." >&2
      echo "Run one-cycle smoke, write evidence JSON, then retry with that path." >&2
      exit 1
    fi
    echo "Preserving already ENABLED schedule for $SERVICE_NAME." >&2
  else
    echo "Refusing to enable schedule without FAIR_VALUE_LIVE_SMOKE_EVIDENCE." >&2
    echo "Run one-cycle smoke, write evidence JSON, then retry with that path." >&2
    exit 1
  fi
fi

ACCOUNT_ID="$(aws --profile "$PROFILE" sts get-caller-identity --query Account --output text)"
IMAGE_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPOSITORY:$IMAGE_TAG"
REPORT_BUCKET_NAME="${REPORT_BUCKET_NAME:-alphadb-artifacts-$ACCOUNT_ID-$REGION}"
VPC_ID="${VPC_ID:-$(aws_cli ec2 describe-vpcs \
  --filters Name=is-default,Values=true \
  --query 'Vpcs[0].VpcId' \
  --output text)}"

if [[ -z "$VPC_ID" || "$VPC_ID" == "None" ]]; then
  echo "Could not discover a default VPC. Set VPC_ID and SUBNET_IDS explicitly." >&2
  exit 1
fi

SUBNET_IDS="${SUBNET_IDS:-$(aws_cli ec2 describe-subnets \
  --filters Name=vpc-id,Values="$VPC_ID" Name=map-public-ip-on-launch,Values=true \
  --query 'Subnets[].SubnetId' \
  --output text | tr '\t' ',')}"

if [[ -z "$SUBNET_IDS" || "$SUBNET_IDS" == "None" ]]; then
  SUBNET_IDS="$(aws_cli ec2 describe-subnets \
    --filters Name=vpc-id,Values="$VPC_ID" \
    --query 'Subnets[].SubnetId' \
    --output text | tr '\t' ',')"
fi

if [[ -z "$SUBNET_IDS" || "$SUBNET_IDS" == "None" ]]; then
  echo "Could not discover subnets. Set SUBNET_IDS explicitly as comma-separated subnet ids." >&2
  exit 1
fi

KALSHI_API_KEY_ID_SECRET_ARN="${KALSHI_API_KEY_ID_SECRET_ARN:-$(secret_arn alphadb/structural-live/kalshi-api-key-id)}"
KALSHI_PRIVATE_KEY_PEM_SECRET_ARN="${KALSHI_PRIVATE_KEY_PEM_SECRET_ARN:-$(secret_arn alphadb/structural-live/kalshi-private-key-pem)}"
DATABASE_URL_SECRET_ARN="${DATABASE_URL_SECRET_ARN:-$(secret_arn alphadb/dashboard/database-url)}"

if ! aws_cli ecr describe-repositories \
  --repository-names "$REPOSITORY" >/dev/null 2>&1; then
  aws_cli ecr create-repository \
    --repository-name "$REPOSITORY" \
    --image-scanning-configuration scanOnPush=true >/dev/null
fi

aws_cli ecr get-login-password \
  | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

docker build --platform linux/arm64 -t "$REPOSITORY:$IMAGE_TAG" .
docker tag "$REPOSITORY:$IMAGE_TAG" "$IMAGE_URI"
docker push "$IMAGE_URI"

aws_cli cloudformation deploy \
  --stack-name "$STACK_NAME" \
  --template-file "$TEMPLATE_FILE" \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    ServiceName="$SERVICE_NAME" \
    ContainerImage="$IMAGE_URI" \
    VpcId="$VPC_ID" \
    SubnetIds="$SUBNET_IDS" \
    AssignPublicIp="${ASSIGN_PUBLIC_IP:-ENABLED}" \
    ReportBucketName="$REPORT_BUCKET_NAME" \
    ReportPrefix="${REPORT_PREFIX:-fair-value-live}" \
    DatabaseUrlSecretArn="$DATABASE_URL_SECRET_ARN" \
    ScheduleExpression="${SCHEDULE_EXPRESSION:-rate(1 minute)}" \
    ScheduleState="${SCHEDULE_STATE:-DISABLED}" \
    MinEdgeValues="${MIN_EDGE_VALUES:-0.0,0.05,0.10}" \
    MinContractPrice="${MIN_CONTRACT_PRICE:-0.25}" \
    KalshiApiKeyIdSecretArn="$KALSHI_API_KEY_ID_SECRET_ARN" \
    KalshiPrivateKeyPemSecretArn="$KALSHI_PRIVATE_KEY_PEM_SECRET_ARN" \
    AwsRegionValue="$REGION"

aws_cli cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs' \
  --output table
