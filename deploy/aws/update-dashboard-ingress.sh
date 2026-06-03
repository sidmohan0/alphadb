#!/usr/bin/env bash
set -euo pipefail

PROFILE="${AWS_PROFILE:-alphadb}"
REGION="${AWS_REGION:-us-east-2}"
STACK_NAME="${STACK_NAME:-alphadb-dashboard-ec2}"
SECRETS_FILE="${SECRETS_FILE:-$HOME/.aws/alphadb-dashboard.env}"
ALLOWED_HTTP_CIDR="${ALLOWED_HTTP_CIDR:-$(curl -fsS https://checkip.amazonaws.com | tr -d '\n')/32}"

PARAMS_FILE="$(mktemp)"
trap 'rm -f "$PARAMS_FILE"' EXIT

cat > "$PARAMS_FILE" <<JSON
[
  {"ParameterKey":"DashboardCookieSecret","UsePreviousValue":true},
  {"ParameterKey":"DbPassword","UsePreviousValue":true},
  {"ParameterKey":"ServiceName","UsePreviousValue":true},
  {"ParameterKey":"DashboardPin","UsePreviousValue":true},
  {"ParameterKey":"DashboardPort","UsePreviousValue":true},
  {"ParameterKey":"AwsRegionValue","UsePreviousValue":true},
  {"ParameterKey":"ContainerImage","UsePreviousValue":true},
  {"ParameterKey":"AllowedHttpCidr","ParameterValue":"$ALLOWED_HTTP_CIDR"},
  {"ParameterKey":"InstanceType","UsePreviousValue":true},
  {"ParameterKey":"AmiId","UsePreviousValue":true},
  {"ParameterKey":"RuntimeMode","UsePreviousValue":true}
]
JSON

aws cloudformation update-stack \
  --profile "$PROFILE" \
  --region "$REGION" \
  --stack-name "$STACK_NAME" \
  --use-previous-template \
  --parameters "file://$PARAMS_FILE" \
  --capabilities CAPABILITY_IAM >/dev/null

aws cloudformation wait stack-update-complete \
  --profile "$PROFILE" \
  --region "$REGION" \
  --stack-name "$STACK_NAME"

if [ -f "$SECRETS_FILE" ]; then
  if grep -q '^ALLOWED_HTTP_CIDR=' "$SECRETS_FILE"; then
    sed -i.bak "s#^ALLOWED_HTTP_CIDR=.*#ALLOWED_HTTP_CIDR=$ALLOWED_HTTP_CIDR#" "$SECRETS_FILE"
    rm -f "$SECRETS_FILE.bak"
  else
    printf 'ALLOWED_HTTP_CIDR=%s\n' "$ALLOWED_HTTP_CIDR" >> "$SECRETS_FILE"
  fi
fi

printf 'Allowed HTTP CIDR updated to %s\n' "$ALLOWED_HTTP_CIDR"
