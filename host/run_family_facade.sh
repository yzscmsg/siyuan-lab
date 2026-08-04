#!/usr/bin/env bash
# Start the PRODUCTION LifeOS family facade (scripts/family_facade.py) on :6902.
#
# Replaces the V8 test surface (run_family_view.sh, :6901) as the Caddy /family
# target. Unlike the V8 viewer, this facade uses REAL authentication
# (core.auth_account, migration 0008) instead of a test-grade persona cookie.
#
# REQUIRED: FAMILY_FACADE_SECRET must be set in the environment before launch
# (the facade refuses to start without it -- fail-closed). In production also
# set FAMILY_FACADE_SECURE_COOKIE=1 (behind Caddy TLS).
#
#   FAMILY_FACADE_SECRET=... FAMILY_FACADE_SECURE_COOKIE=1 ./run_family_facade.sh
set -euo pipefail

BASE=/opt/siyuan-lab
LOG="$BASE/exports/family_facade.log"
PIDF="$BASE/exports/family_facade.pid"

[ -n "${FAMILY_FACADE_SECRET:-}" ] || {
    echo "FATAL: FAMILY_FACADE_SECRET is not set in the environment." >&2
    echo "       The facade refuses to start without a signing secret." >&2
    exit 1
}

# stop any previous instance
if [[ -f "$PIDF" ]]; then
  kill "$(cat "$PIDF")" 2>/dev/null || true
  rm -f "$PIDF"
fi

export FAMILY_FACADE_PORT="${FAMILY_FACADE_PORT:-6902}"
export FAMILY_FACADE_SECRET
export FAMILY_FACADE_SECURE_COOKIE="${FAMILY_FACADE_SECURE_COOKIE:-0}"
export ARCHIVE_ROOT="${ARCHIVE_ROOT:-/opt/siyuan-lab/exports/markdown}"
export HOUSEHOLD_NAME="${HOUSEHOLD_NAME:-s1-lab-household}"

cd "$BASE"
nohup python3 "$BASE/scripts/family_facade.py" >"$LOG" 2>&1 &
echo $! > "$PIDF"
sleep 1
if kill -0 "$(cat "$PIDF")" 2>/dev/null; then
  CODE=$(python3 -c "import urllib.request; \
    print(urllib.request.urlopen('http://127.0.0.1:6902/healthz').read().decode())" 2>/dev/null || echo FAIL)
  echo "[family_facade] started pid $(cat "$PIDF"); log $LOG; health=$CODE"
else
  echo "[family_facade] FAILED to start; tail log:"; tail -20 "$LOG"; exit 1
fi
