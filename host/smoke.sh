#!/usr/bin/env bash
# S1 smoke test after deploy/upgrade/restore: kernel version + doc count.
set -euo pipefail
BASE=/opt/siyuan-lab
PORT="${1:-6806}"
TOKEN="$(cat "$BASE/secrets/api_token" 2>/dev/null || echo "")"
VER="$(wget -qO- http://127.0.0.1:$PORT/api/system/version 2>/dev/null || echo '{}')"
echo "version endpoint (:$PORT): $VER"
DOCS="$(python3 - <<PY
import json,urllib.request,ssl
ctx=ssl.create_default_context();ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE
try:
    body=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:$PORT/api/query/sql',data=json.dumps({'stmt':"SELECT COUNT(*) AS c FROM blocks WHERE type='d'"}).encode(),headers={'Authorization':'Token $TOKEN','Content-Type':'application/json'},method='POST'),context=ctx).read().decode()
    print(json.loads(body)['data'][0]['c'])
except Exception as e:
    print('ERR',e)
PY
)"
echo "doc count (type=d): $DOCS"
echo "$DOCS" > "$BASE/exports/last_smoke_doccount.txt"
