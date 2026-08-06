#!/usr/bin/env bash
# Start the V8 family-view test surface (stdlib, no deps).
# Bound to 0.0.0.0:6900 on the host. This is V8 test scaffolding,
# NOT the production PoC-3 facade.
#
# BOUNDARY NOTE (ADR-0012 section 1): scripts/family_view.py is NOT owned by this
# repo. It is a gitignored artifact synced from
#   family-lifeos/scripts/experimental/family_view.py
# by scripts/sync_from_family_lifeos.sh. This launcher is retained because
# scripts/v8_smoke_test.py (retained evidence) needs the viewer running.
# Never edit the synced copy -- edit it in family-lifeos and re-sync.
#
# ROUTING NOTE (ADR-0012 section 2): the Caddy /family* route was removed on
# 2026-08-06 -- it published a product surface from an experiment repo. Reach
# the viewer directly on :6900 (or :6901 via run_family_view_http.sh).
set -euo pipefail

BASE="${LIFEOS_LAB_BASE:-/opt/siyuan-lab}"
LOG="$BASE/exports/family_view.log"
PIDF="$BASE/exports/family_view.pid"

[ -f "$BASE/scripts/family_view.py" ] || {
  echo "family_view.py missing -- run: bash scripts/sync_from_family_lifeos.sh /path/to/family-lifeos" >&2
  exit 1
}

# stop any previous instance
if [[ -f "$PIDF" ]]; then
  kill "$(cat "$PIDF")" 2>/dev/null || true
  rm -f "$PIDF"
fi

cd "$BASE"
nohup python3 "$BASE/scripts/family_view.py" >"$LOG" 2>&1 &
echo $! > "$PIDF"
sleep 1
if kill -0 "$(cat "$PIDF")" 2>/dev/null; then
  CODE=$(python3 -c "import urllib.request,sys; \
    print(urllib.request.urlopen('http://127.0.0.1:6900/healthz').read().decode())" 2>/dev/null || echo FAIL)
  echo "[family_view] started pid $(cat "$PIDF"); log $LOG; health=$CODE"
else
  echo "[family_view] FAILED to start; tail log:"; tail -20 "$LOG"; exit 1
fi
