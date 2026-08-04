#!/usr/bin/env bash
# Start the V8 family viewer on :6901 (plain HTTP).
# Used by automation clients (curl/python/PowerShell) that cannot negotiate
# Caddy's internal-CA TLS against a raw IP without SNI. The HTTPS path at
# /family on :443 still works for browsers that send SNI.
set -euo pipefail

BASE=/opt/siyuan-lab
cd "$BASE/scripts"
[ -f family_view.py ] || { echo "family_view.py missing"; exit 1; }

# Patch PORT in-place so family_view.py listens on 6901 instead of 6900.
sed -i 's/^PORT = .*/PORT = 6901/' family_view.py

# Stop any existing viewer before re-binding the port.
if [ -f "$BASE/exports/family_view.pid" ]; then
    kill "$(cat "$BASE/exports/family_view.pid")" 2>/dev/null || true
fi
sleep 1

nohup python3 family_view.py > "$BASE/exports/family_view.log" 2>&1 &
echo "$!" > "$BASE/exports/family_view.pid"
sleep 2

ss -tlnp --no-header 2>/dev/null | grep -q ':6901 ' \
    || { echo "WARNING: :6901 not listening; see $BASE/exports/family_view.log"; exit 1; }
echo "family_view.py listening on :6901 (pid $(cat "$BASE/exports/family_view.pid"))"
