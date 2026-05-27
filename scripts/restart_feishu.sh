#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CA_BUNDLE="${REQUESTS_CA_BUNDLE:-/private/tmp/feishu-ca-bundle.pem}"

echo "Stopping existing Feishu long connection processes..."
pkill -f "src.feishu_long_connection" 2>/dev/null || true
sleep 1

cd "$PROJECT_DIR"

echo "Starting Feishu long connection..."
echo "Project: $PROJECT_DIR"
echo "Press Ctrl-C to stop."

REQUESTS_CA_BUNDLE="$CA_BUNDLE" \
SSL_CERT_FILE="${SSL_CERT_FILE:-$CA_BUNDLE}" \
python3 -m src.feishu_long_connection
