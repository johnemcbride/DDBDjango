#!/usr/bin/env bash
# scripts/deploy_frontend.sh
# ────────────────────────────────────────────────────────────────────────────
# Builds the React frontend and deploys it to LocalStack S3.
# An nginx container (cloudfront-proxy, port 3000) serves the app and mimics
# a CloudFront distribution with two behaviors:
#   /api/*  →  Lambda API Gateway  (LocalStack)
#   /*      →  S3 static bucket    (LocalStack)
#
# The nginx proxy URL (http://localhost:3000) is baked into the JS bundle as
# VITE_API_URL so the React app calls its own origin — no CORS issues.
# The actual Lambda API Gateway ID is resolved here, written to .env, and
# injected into the nginx container via envsubst at startup.
#
# Usage:
#   ./scripts/deploy_frontend.sh              # full build + deploy
#   ./scripts/deploy_frontend.sh --skip-build # upload existing dist/ only
#
# Requirements:
#   - Node 18+ and npm
#   - LocalStack running (docker-compose up -d)
#   - Lambda already deployed (make lambda-deploy)
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ENDPOINT="http://localhost:4566"
REGION="us-east-1"
BUCKET="ddbdjango-frontend"
LAMBDA_NAME="ddbdjango"
FRONTEND_DIR="frontend"
PROXY_URL="http://localhost:3000"   # the CloudFront-like nginx proxy
SKIP_BUILD="${1:-}"

AWS="aws --endpoint-url=$ENDPOINT --region=$REGION --no-cli-pager --output text"

# ── 1. Resolve Lambda API Gateway ID ─────────────────────────────────────
echo "→ Resolving Lambda API Gateway …"
API_ID=$($AWS apigateway get-rest-apis \
  --query "items[?name=='$LAMBDA_NAME'].id" 2>/dev/null | head -1 | tr -d '[:space:]')

if [[ -z "$API_ID" || "$API_ID" == "None" ]]; then
  echo "  ✗ Lambda not deployed — run 'make lambda-deploy' first."
  exit 1
fi

LAMBDA_URL="http://${API_ID}.execute-api.localhost.localstack.cloud:4566/api"
echo "  ✓ API Gateway ID: $API_ID"
echo "  ✓ Lambda URL:     $LAMBDA_URL"

# ── 2. Write .env so docker-compose injects NGINX_API_ID into nginx ───────
echo "→ Writing .env with NGINX_API_ID=$API_ID …"
ENV_FILE=".env"
touch "$ENV_FILE"
grep -v '^NGINX_API_ID=' "$ENV_FILE" > "$ENV_FILE.tmp" 2>/dev/null && mv "$ENV_FILE.tmp" "$ENV_FILE" || true
echo "NGINX_API_ID=$API_ID" >> "$ENV_FILE"
echo "  ✓ .env updated"

# ── 3. Build React app ────────────────────────────────────────────────────
# VITE_API_URL = the nginx proxy origin — React calls its own origin so
# nginx routes /api/* → Lambda and /* → S3.  No CORS needed.
if [[ "$SKIP_BUILD" != "--skip-build" ]]; then
  echo "→ Installing frontend dependencies …"
  (cd "$FRONTEND_DIR" && npm install --silent)
  echo "  ✓ npm install done"

  echo "→ Building React app …"
  echo "    VITE_API_URL=$PROXY_URL  (baked into bundle)"
  (cd "$FRONTEND_DIR" && VITE_API_URL="$PROXY_URL" npm run build)
  SIZE=$(du -sh "$FRONTEND_DIR/dist" | cut -f1)
  echo "  ✓ Build complete — $SIZE"
else
  echo "→ Skipping build (--skip-build)"
  [[ -d "$FRONTEND_DIR/dist" ]] || {
    echo "  ✗ No dist/ found — run without --skip-build first."
    exit 1
  }
fi

# ── 4. Ensure S3 bucket with website hosting ─────────────────────────────
echo "→ Ensuring S3 bucket '$BUCKET' …"
$AWS s3api create-bucket --bucket "$BUCKET" 2>/dev/null || true
$AWS s3api put-bucket-website --bucket "$BUCKET" --website-configuration \
  '{"IndexDocument":{"Suffix":"index.html"},"ErrorDocument":{"Key":"index.html"}}' \
  2>/dev/null || true
echo "  ✓ Bucket ready"

# ── 5. Upload files ───────────────────────────────────────────────────────
echo "→ Syncing hashed assets (immutable cache) …"
$AWS s3 sync "$FRONTEND_DIR/dist/assets/" "s3://$BUCKET/assets/" \
  --delete \
  --checksum-algorithm CRC32 \
  --cache-control "public, max-age=31536000, immutable" \
  --quiet
echo "  ✓ Assets synced"

echo "→ Uploading index.html (no-cache) …"
$AWS s3 cp "$FRONTEND_DIR/dist/index.html" "s3://$BUCKET/index.html" \
  --checksum-algorithm CRC32 \
  --cache-control "no-cache, no-store, must-revalidate" \
  --content-type "text/html; charset=utf-8" \
  --quiet

find "$FRONTEND_DIR/dist" -maxdepth 1 -type f ! -name 'index.html' | while read -r f; do
  fname=$(basename "$f")
  $AWS s3 cp "$f" "s3://$BUCKET/$fname" \
    --checksum-algorithm CRC32 \
    --cache-control "public, max-age=86400" \
    --quiet
done
echo "  ✓ index.html + root files uploaded"

# ── 6. Restart nginx proxy so it picks up the new NGINX_API_ID ───────────
echo "→ Restarting cloudfront-proxy nginx container …"
if docker ps --format '{{.Names}}' | grep -q 'ddbdjango-cloudfront'; then
  docker restart ddbdjango-cloudfront
  echo "  ✓ Restarted"
else
  echo "  ⚠  Container ddbdjango-cloudfront not running — run 'make docker-up' first."
fi

# ── 7. Summary ────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Frontend deployed to   s3://$BUCKET"
echo "  ✓ App URL:               $PROXY_URL"
echo "  ✓ API URL (baked in):    $PROXY_URL/api"
echo "  ✓ API proxied to:        $LAMBDA_URL"
echo ""
echo "  CloudFront behaviors:"
echo "    $PROXY_URL/api/*  →  Lambda (API Gateway $API_ID)"
echo "    $PROXY_URL/*      →  S3 (s3://$BUCKET)"
echo ""
echo "  Test it:"
echo "    open $PROXY_URL"
echo "    curl $PROXY_URL/api/posts/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
