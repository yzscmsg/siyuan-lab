#!/usr/bin/env bash
# Start the V8 family-view test surface (stdlib, no deps).
# Bound to 0.0.0.0:6900 on the host; reached from phones via the Caddy
# /family* route (see infra/compose/Caddyfile). This is V8 test scaffolding,
# NOT the production PoC-3 facade.
set -euo pipefail

BASE=/opt/siyuan-lab
LOG="$BASE/exports/family_view.log"
PIDF="$BASE/exports/family_view.pid"

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
