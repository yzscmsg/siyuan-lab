#!/usr/bin/env bash
# Start the V8 family viewer on :6901 (plain HTTP).
# Used by automation clients (curl/python/PowerShell) that cannot negotiate
# Caddy's internal-CA TLS against a raw IP without SNI.
#
# BOUNDARY NOTE (ADR-0012 section 1): scripts/family_view.py is NOT owned by this
# repo. It is a gitignored artifact synced from
#   family-lifeos/scripts/experimental/family_view.py
# by scripts/sync_from_family_lifeos.sh. This launcher is retained because
# scripts/v8_smoke_test.py (retained evidence) needs the viewer running.
# Never edit the synced copy -- edit it in family-lifeos and re-sync.
set -euo pipefail

BASE="${LIFEOS_LAB_BASE:-/opt/siyuan-lab}"
cd "$BASE/scripts"
[ -f family_view.py ] || {
    echo "family_view.py missing -- run: bash scripts/sync_from_family_lifeos.sh /path/to/family-lifeos" >&2
    exit 1
}

# Stop any existing viewer before re-binding the port.
if [ -f "$BASE/exports/family_view.pid" ]; then
    kill "$(cat "$BASE/exports/family_view.pid")" 2>/dev/null || true
fi
sleep 1

# Port is set via env, NOT by patching the file. The previous version ran
# `sed -i 's/^PORT = .*/PORT = 6901/' family_view.py`, which (a) mutated a
# gitignored sync artifact so the next sync silently reverted it, and
# (b) corrupted the source audit in v8_smoke_test.py that cats this same file.
FAMILY_VIEW_PORT=6901 nohup python3 family_view.py > "$BASE/exports/family_view.log" 2>&1 &
echo "$!" > "$BASE/exports/family_view.pid"
sleep 2

ss -tlnp --no-header 2>/dev/null | grep -q ':6901 ' \
    || { echo "WARNING: :6901 not listening; see $BASE/exports/family_view.log"; exit 1; }
echo "family_view.py listening on :6901 (pid $(cat "$BASE/exports/family_view.pid"))"
