#!/usr/bin/env bash
# SiYuan PoC — bring up the S1 stack on the VM (plain docker run; compose.yaml kept for portability).
# Idempotent: tears down existing containers before recreating.
set -euo pipefail

BASE=/opt/siyuan-lab
SECRETS="$BASE/secrets"
WS="$BASE/workspace"
SIYUAN_IMG=b3log/siyuan:v3.7.3
CADDY_IMG=caddy:2.8.4
NET=siyuan_net
PUID=1000
PGID=1000

AUTHCODE="$(cat "$SECRETS/authcode")"
[ -n "$AUTHCODE" ] || { echo "authcode missing"; exit 1; }

# --- dedicated non-root service account owns the workspace volume ---
if ! id siyuan >/dev/null 2>&1; then useradd -r -s /usr/sbin/nologin -u 1000 siyuan 2>/dev/null || true; fi
chown -R 1000:1000 "$WS" 2>/dev/null || true

# --- network ---
docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET"

# --- SiYuan kernel (published to 127.0.0.1:6806 for local API; not to LAN) ---
docker rm -f siyuan-poc 2>/dev/null || true
docker run -d --name siyuan-poc --restart unless-stopped --network "$NET" \
  -e PUID="$PUID" -e PGID="$PGID" -e TZ=Asia/Shanghai \
  -e SIYUAN_ACCESS_AUTH_CODE="$AUTHCODE" \
  -v "$WS":/siyuan/workspace \
  -p 127.0.0.1:6806:6806 \
  "$SIYUAN_IMG" serve --workspace=/siyuan/workspace/ --accessAuthCode="$AUTHCODE"

# --- Caddy: tls internal (basicauth omitted — see Caddyfile note) ---
docker rm -f siyuan-caddy 2>/dev/null || true
docker run -d --name siyuan-caddy --restart unless-stopped --network "$NET" \
  -e SITE_ADDRESS=192.168.88.9 \
  --add-host host.docker.internal:host-gateway \
  -p 80:80 -p 443:443 \
  -v "$BASE/infra/compose/Caddyfile":/etc/caddy/Caddyfile:ro \
  "$CADDY_IMG"

# --- wait for boot + extract API token into the secret store ---
for i in $(seq 1 60); do
  if wget -qO- http://127.0.0.1:6806/api/system/version >/dev/null 2>&1; then break; fi
  sleep 2
done
TOKEN="$(python3 - <<'PY'
import json
try:
    d = json.load(open('/opt/siyuan-lab/workspace/conf/conf.json'))
    print(d.get('api', {}).get('token') or d.get('system', {}).get('token') or '')
except Exception:
    print('')
PY
)"
if [ -n "$TOKEN" ]; then
  echo "$TOKEN" > "$SECRETS/api_token"; chmod 600 "$SECRETS/api_token"
  echo "deploy done. api_token stored (len=${#TOKEN})"
else
  echo "deploy done. WARNING: api_token not found in conf.json yet (retry after kernel settles)"
fi
echo "--- status ---"
docker ps --format '{{.Names}}\t{{.Status}}' | grep siyuan
