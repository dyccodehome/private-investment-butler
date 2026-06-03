#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CA_BUNDLE="${REQUESTS_CA_BUNDLE:-}"

if [[ -z "$CA_BUNDLE" ]]; then
  CA_BUNDLE="$(python3 - <<'PY'
from pathlib import Path

try:
    import certifi

    certifi_path = Path(certifi.where())
    if certifi_path.exists():
        print(certifi_path)
        raise SystemExit
except Exception:
    pass

for candidate in (
    Path("/etc/ssl/cert.pem"),
    Path("/Library/Frameworks/Python.framework/Versions/3.13/etc/openssl/cert.pem"),
):
    if candidate.exists():
        print(candidate)
        raise SystemExit
PY
)"
fi

echo "Stopping existing Feishu long connection processes..."
pkill -f "src.feishu_long_connection" 2>/dev/null || true
sleep 1

cd "$PROJECT_DIR"

echo "Starting Feishu long connection..."
echo "Project: $PROJECT_DIR"
echo "CA bundle: ${CA_BUNDLE:-system default}"
echo "Press Ctrl-C to stop."

if [[ -n "$CA_BUNDLE" ]]; then
  REQUESTS_CA_BUNDLE="$CA_BUNDLE" \
  SSL_CERT_FILE="${SSL_CERT_FILE:-$CA_BUNDLE}" \
  python3 -m src.feishu_long_connection
else
  python3 -m src.feishu_long_connection
fi
