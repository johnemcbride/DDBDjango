#!/usr/bin/env bash
# scripts/deploy_lambda.sh
# ────────────────────────────────────────────────────────────────────────────
# Packages the DDBDjango app and deploys it as a Lambda function on LocalStack,
# fronted by an API Gateway HTTP API.
#
# Usage:
#   ./scripts/deploy_lambda.sh            # full build + deploy
#   ./scripts/deploy_lambda.sh --code-only  # skip pip install (faster re-deploy)
#
# Requirements:
#   - LocalStack running with lambda,apigateway enabled (docker-compose up -d)
#   - AWS CLI installed  (brew install awscli)
#   - .venv activated or run from project root
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ENDPOINT="http://localhost:4566"
REGION="us-east-1"
FUNCTION_NAME="ddbdjango"
RUNTIME="python3.12"
ROLE_ARN="arn:aws:iam::000000000000:role/lambda-role"
BUILD_DIR="lambda_build"
ZIP_FILE="lambda_build.zip"
S3_BUCKET="ddbdjango-lambda"
CODE_ONLY="${1:-}"

AWS="aws --endpoint-url=$ENDPOINT --region=$REGION --no-cli-pager --output text"

# ── 1. Build package ──────────────────────────────────────────────────────
if [[ "$CODE_ONLY" != "--code-only" ]]; then
  echo "→ Installing dependencies into $BUILD_DIR/ ..."
  rm -rf "$BUILD_DIR"
  mkdir -p "$BUILD_DIR"
  .venv/bin/pip install \
    --quiet \
    --requirement requirements.txt \
    --target "$BUILD_DIR" \
    2>/dev/null || \
  .venv/bin/pip install \
    --quiet \
    --requirement requirements.txt \
    --target "$BUILD_DIR"
  echo "  ✓ Dependencies installed"
else
  echo "→ Skipping pip install (--code-only)"
  mkdir -p "$BUILD_DIR"
fi

# Copy project source (exclude venv, tests, build artefacts, etc.)
echo "→ Copying project source ..."
rsync -a --quiet \
  --exclude=".venv" \
  --exclude="$BUILD_DIR" \
  --exclude="$ZIP_FILE" \
  --exclude="*.pyc" \
  --exclude="__pycache__" \
  --exclude=".pytest_cache" \
  --exclude=".git" \
  --exclude="tests/" \
  --exclude="*.egg-info" \
  --exclude="scripts/" \
  --exclude="docker/" \
  --exclude="*.md" \
  --exclude="*.txt" \
  --exclude="*.toml" \
  --exclude="*.ini" \
  --exclude="Makefile" \
  --exclude=".gitignore" \
  . "$BUILD_DIR/"
echo "  ✓ Source copied"

# Zip
echo "→ Creating $ZIP_FILE ..."
(cd "$BUILD_DIR" && zip -r "../$ZIP_FILE" . -q)
echo "  ✓ Package: $(du -sh "$ZIP_FILE" | cut -f1)"

# ── 2. Upload zip to S3 (avoids 50 MB direct-upload limit) ───────────────
S3_KEY="$ZIP_FILE"

echo "→ Ensuring S3 bucket '$S3_BUCKET' ..."
$AWS s3api create-bucket --bucket "$S3_BUCKET" 2>/dev/null || true
echo "  ✓ Bucket ready"

echo "→ Uploading $ZIP_FILE to s3://$S3_BUCKET/ ..."
$AWS s3 cp "$ZIP_FILE" "s3://$S3_BUCKET/$S3_KEY" --quiet
echo "  ✓ Uploaded ($(du -sh "$ZIP_FILE" | cut -f1))"

# ── 3. Create IAM role (no-op if exists) ─────────────────────────────────
echo "→ Ensuring IAM role ..."
$AWS iam create-role \
  --role-name lambda-role \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
  2>/dev/null || true

# ── 4. Create or update Lambda function ──────────────────────────────────
LAMBDA_ENV="Variables={
  DJANGO_SETTINGS_MODULE=config.settings,
  DYNAMO_SKIP_STARTUP=1,
  DYNAMO_ENDPOINT_URL=http://host.docker.internal:4566,
  AWS_DEFAULT_REGION=us-east-1,
  AWS_ACCESS_KEY_ID=test,
  AWS_SECRET_ACCESS_KEY=test,
  DJANGO_ALLOWED_HOSTS=*
}"

if $AWS lambda get-function --function-name "$FUNCTION_NAME" &>/dev/null; then
  echo "→ Updating Lambda function code ..."
  $AWS lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --s3-bucket "$S3_BUCKET" \
    --s3-key "$S3_KEY" > /dev/null
  echo "  ✓ Code updated"

  echo "→ Updating Lambda environment ..."
  $AWS lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --environment "$LAMBDA_ENV" > /dev/null
  echo "  ✓ Config updated"
else
  echo "→ Creating Lambda function ..."
  $AWS lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime "$RUNTIME" \
    --role "$ROLE_ARN" \
    --handler "lambda_handler.handler" \
    --code "S3Bucket=$S3_BUCKET,S3Key=$S3_KEY" \
    --timeout 30 \
    --memory-size 512 \
    --environment "$LAMBDA_ENV" > /dev/null
  echo "  ✓ Lambda created"
fi

# Wait for the function to be Active
echo "→ Waiting for Lambda to be Active ..."
for i in $(seq 1 20); do
  STATE=$($AWS lambda get-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --query State 2>/dev/null || echo "Unknown")
  if [[ "$STATE" == "Active" ]]; then
    echo "  ✓ Lambda is Active"
    break
  fi
  sleep 2
done

# ── 5. Create API Gateway REST API v1 (idempotent) ─────────────────────────
LAMBDA_ARN="arn:aws:lambda:$REGION:000000000000:function:$FUNCTION_NAME"
INTEG_URI="arn:aws:apigateway:$REGION:lambda:path/2015-03-31/functions/${LAMBDA_ARN}/invocations"

EXISTING_API=$($AWS apigateway get-rest-apis \
  --query "items[?name=='$FUNCTION_NAME'].id" \
  2>/dev/null | head -1 | tr -d '[:space:]' || true)

if [[ -n "$EXISTING_API" && "$EXISTING_API" != "None" ]]; then
  API_ID="$EXISTING_API"
  echo "→ Using existing API Gateway: $API_ID"
else
  echo "→ Creating API Gateway REST API ..."

  API_ID=$($AWS apigateway create-rest-api \
    --name "$FUNCTION_NAME" \
    --query id)

  # Get root resource id
  ROOT_ID=$($AWS apigateway get-resources \
    --rest-api-id "$API_ID" \
    --query "items[?path=='/'].id")

  # Create greedy proxy resource  /{proxy+}
  PROXY_ID=$($AWS apigateway create-resource \
    --rest-api-id "$API_ID" \
    --parent-id "$ROOT_ID" \
    --path-part "{proxy+}" \
    --query id)

  # Helper: wire ANY on a resource to Lambda
  setup_method() {
    local RES_ID=$1
    $AWS apigateway put-method \
      --rest-api-id "$API_ID" --resource-id "$RES_ID" \
      --http-method ANY --authorization-type NONE > /dev/null
    $AWS apigateway put-integration \
      --rest-api-id "$API_ID" --resource-id "$RES_ID" \
      --http-method ANY --type AWS_PROXY \
      --integration-http-method POST \
      --uri "$INTEG_URI" > /dev/null
  }

  setup_method "$ROOT_ID"
  setup_method "$PROXY_ID"

  # Deploy to a stage
  $AWS apigateway create-deployment \
    --rest-api-id "$API_ID" \
    --stage-name api > /dev/null

  # Allow API Gateway to invoke Lambda
  $AWS lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "apigw-invoke" \
    --action "lambda:InvokeFunction" \
    --principal "apigateway.amazonaws.com" \
    --source-arn "arn:aws:execute-api:$REGION:000000000000:$API_ID/*/*" \
    > /dev/null

  echo "  ✓ API Gateway REST API configured"
fi

# ── 6. Print summary ──────────────────────────────────────────────────────
URL="http://localhost:4566/restapis/${API_ID}/api/_user_request_"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Lambda deployed: $FUNCTION_NAME"
echo "  ✓ Endpoint:        $URL"
echo ""
echo "  Test it:"
echo "    curl $URL/"
echo "    curl $URL/api/posts/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
