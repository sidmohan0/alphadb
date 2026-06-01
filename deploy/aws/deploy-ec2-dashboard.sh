#!/usr/bin/env bash
set -euo pipefail

PROFILE="${AWS_PROFILE:-alphadb}"
REGION="${AWS_REGION:-us-east-2}"
STACK_NAME="${STACK_NAME:-alphadb-dashboard-ec2}"
REPOSITORY="${ECR_REPOSITORY:-alphadb-dashboard}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t4g.micro}"
RUNTIME_MODE="${ALPHADB_RUNTIME_MODE:-paper}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
TEMPLATE_FILE="${TEMPLATE_FILE:-deploy/aws/ec2-dashboard.yaml}"
SECRETS_FILE="${SECRETS_FILE:-$HOME/.aws/alphadb-dashboard.env}"

ACCOUNT_ID="$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)"
IMAGE_URI="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPOSITORY:$IMAGE_TAG"
ALLOWED_HTTP_CIDR="${ALLOWED_HTTP_CIDR:-$(curl -fsS https://checkip.amazonaws.com | tr -d '\n')/32}"
DASHBOARD_PIN="${ALPHADB_DASHBOARD_PIN:-$(printf "%04d" "$((0x$(openssl rand -hex 2) % 10000))")}"
DASHBOARD_COOKIE_SECRET="${ALPHADB_DASHBOARD_COOKIE_SECRET:-$(openssl rand -hex 32)}"
DB_PASSWORD="${ALPHADB_DB_PASSWORD:-$(openssl rand -hex 24)}"

if ! aws ecr describe-repositories \
  --repository-names "$REPOSITORY" \
  --profile "$PROFILE" \
  --region "$REGION" >/dev/null 2>&1; then
  aws ecr create-repository \
    --repository-name "$REPOSITORY" \
    --image-scanning-configuration scanOnPush=true \
    --profile "$PROFILE" \
    --region "$REGION" >/dev/null
fi

aws ecr get-login-password --profile "$PROFILE" --region "$REGION" \
  | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

docker build --platform linux/arm64 -t "$REPOSITORY:$IMAGE_TAG" .
docker tag "$REPOSITORY:$IMAGE_TAG" "$IMAGE_URI"
docker push "$IMAGE_URI"

aws cloudformation deploy \
  --profile "$PROFILE" \
  --region "$REGION" \
  --stack-name "$STACK_NAME" \
  --template-file "$TEMPLATE_FILE" \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    ServiceName=alphadb-dashboard \
    ContainerImage="$IMAGE_URI" \
    InstanceType="$INSTANCE_TYPE" \
    AllowedHttpCidr="$ALLOWED_HTTP_CIDR" \
    DashboardPin="$DASHBOARD_PIN" \
    DashboardCookieSecret="$DASHBOARD_COOKIE_SECRET" \
    DbPassword="$DB_PASSWORD" \
    RuntimeMode="$RUNTIME_MODE" \
    AwsRegionValue="$REGION"

umask 077
{
  printf 'AWS_PROFILE=%s\n' "$PROFILE"
  printf 'AWS_REGION=%s\n' "$REGION"
  printf 'STACK_NAME=%s\n' "$STACK_NAME"
  printf 'IMAGE_URI=%s\n' "$IMAGE_URI"
  printf 'ALLOWED_HTTP_CIDR=%s\n' "$ALLOWED_HTTP_CIDR"
  printf 'ALPHADB_DASHBOARD_PIN=%s\n' "$DASHBOARD_PIN"
} > "$SECRETS_FILE"

aws cloudformation describe-stacks \
  --profile "$PROFILE" \
  --region "$REGION" \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs' \
  --output table

echo "Saved dashboard access values to $SECRETS_FILE"
