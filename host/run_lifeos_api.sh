#!/usr/bin/env bash
# run_lifeos_api.sh -- launch the LifeOS Ingest API (optional-tool contract).
#
# Runs scripts/lifeos_api.py on :6903 (plaintext, host-side). Caddy terminates
# TLS and proxies /api -> 172.18.0.1:6903 (see infra/compose/Caddyfile).
# Auth is by scoped service token (migration 0009), not a process secret, so
# there is no token to set here -- but the API refuses to serve a plaintext
# edge (LIFEOS_API_REQUIRE_HTTPS=1) and must sit behind Caddy.
#
# Provision a token first (lab):
#   python3 scripts/seed_service_token.py --label n8n-lab --scope ingest
#
# Then run this, and:
#   python3 scripts/ingest_api_test.py            # contract checks
set -euo pipefail
cd "$(dirname "$0")/.."

export LIFEOS_API_HOST="${LIFEOS_API_HOST:-0.0.0.0}"
export LIFEOS_API_PORT="${LIFEOS_API_PORT:-6903}"
export LIFEOS_API_BASE="${LIFEOS_API_BASE:-/api}"
export LIFEOS_API_REQUIRE_HTTPS="${LIFEOS_API_REQUIRE_HTTPS:-1}"

echo "Starting lifeos_api on ${LIFEOS_API_HOST}:${LIFEOS_API_PORT} (Caddy /api -> this)"
exec python3 scripts/lifeos_api.py
