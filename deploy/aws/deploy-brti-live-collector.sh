#!/usr/bin/env bash
set -euo pipefail

PROFILE="${AWS_PROFILE:-alphadb}"
REGION="${AWS_REGION:-us-east-2}"
STACK_NAME="${STACK_NAME:-alphadb-brti-live-collector}"
SERVICE_NAME="${SERVICE_NAME:-alphadb-brti-live-collector}"
REPOSITORY="${ECR_REPOSITORY:-alphadb-brti-live-collector}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)-$(date -u +%Y%m%d%H%M%S)}"
TEMPLATE_FILE="${TEMPLATE_FILE:-deploy/aws/brti-live-collector.yaml}"

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

ACCOUNT_ID="$(aws --profile "$PROFILE" sts get-caller-identity --query Account --output text)"
IMAGE_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPOSITORY:$IMAGE_TAG"
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
    DesiredCount="${DESIRED_COUNT:-1}" \
    IndexId="${BRTI_INDEX_ID:-BRTI}" \
    MaxReconnects="${MAX_RECONNECTS:-1000000}" \
    KalshiWebSocketUrl="${KALSHI_WS_URL:-wss://external-api-ws.kalshi.com/trade-api/ws/v2}" \
    DatabaseUrlSecretArn="$DATABASE_URL_SECRET_ARN" \
    KalshiApiKeyIdSecretArn="$KALSHI_API_KEY_ID_SECRET_ARN" \
    KalshiPrivateKeyPemSecretArn="$KALSHI_PRIVATE_KEY_PEM_SECRET_ARN" \
    AwsRegionValue="$REGION"

aws_cli cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs' \
  --output table

aws_cli ecs wait services-stable \
  --cluster "$SERVICE_NAME" \
  --services "$SERVICE_NAME"
