#!/usr/bin/env bash
# S1 restore: restore a backup archive into a FRESH instance and verify.
# Usage: host/restore.sh <archive.tar.gz> [fresh-workspace-path]
#
# "Fresh instance" means: a workspace directory that did not exist, a container
# that did not exist, on a different port. The live workspace is never touched.
# Verification is per-document against exports/seed_map.json, not a raw count.
set -euo pipefail
BASE=/opt/siyuan-lab
ARCH="${1:-$(ls -t "$BASE"/backups/*.tar.gz 2>/dev/null | head -1)}"
[ -n "$ARCH" ] || { echo "no backup archive found"; exit 1; }
RESTORE_WS="${2:-/opt/siyuan-lab/restore-workspace}"
AUTHCODE="$(cat "$BASE/secrets/authcode")"
IMAGE_TAG="$(cat "$BASE/VERSION" 2>/dev/null || echo v3.7.3)"
T0=$(date +%s)

echo "[restore] using archive: $ARCH"
echo "[restore] fresh workspace: $RESTORE_WS"
echo "[restore] image tag: $IMAGE_TAG"
# Remove the target entirely so `mv` replaces it (not nests inside it).
rm -rf "$RESTORE_WS"
TMP="$(mktemp -d)"
tar --gzip -xf "$ARCH" -C "$TMP"   # extracts ./workspace inside $TMP (never touches live $BASE/workspace)
mv "$TMP/workspace" "$RESTORE_WS"
rmdir "$TMP" 2>/dev/null || true
chown -R 1000:1000 "$RESTORE_WS" 2>/dev/null || true

# Boot a throwaway SiYuan against the restored workspace on a different port.
docker rm -f siyuan-restore 2>/dev/null || true
docker run -d --name siyuan-restore --network siyuan_net \
  -e PUID=1000 -e PGID=1000 -e TZ=Asia/Shanghai \
  -e SIYUAN_ACCESS_AUTH_CODE="$AUTHCODE" \
  -v "$RESTORE_WS":/siyuan/workspace \
  -p 127.0.0.1:6807:6806 \
  "b3log/siyuan:${IMAGE_TAG}" serve --workspace=/siyuan/workspace/ --accessAuthCode="$AUTHCODE"

echo "[restore] waiting for boot on :6807"
BOOTED=false
for i in $(seq 1 60); do
  if wget -qO- --post-data='{}' http://127.0.0.1:6807/api/system/version >/dev/null 2>&1; then BOOTED=true; break; fi
  sleep 2
done
$BOOTED || { echo "[restore] FAILED: fresh instance never answered on :6807" >&2
             docker logs --tail 40 siyuan-restore >&2 || true
             docker rm -f siyuan-restore >/dev/null 2>&1 || true; exit 4; }
T_BOOT=$(( $(date +%s) - T0 ))
echo "[restore] fresh instance answered after ${T_BOOT}s"

TOKEN="$(python3 -c "import json;print(json.load(open('$RESTORE_WS/conf/conf.json')).get('api',{}).get('token',''))")"

set +e
SIYUAN_BASE_URL=http://127.0.0.1:6807 SIYUAN_TOKEN="$TOKEN" \
WS="$RESTORE_WS" SEED_MAP="$BASE/exports/seed_map.json" \
RESTORE_REPORT="$BASE/exports/restore_verify.json" \
  python3 "$BASE/scripts/verify_restore.py" \
    > "$BASE/exports/restore_doc_count.txt" 2> "$BASE/exports/restore_verify.err"
VRC=$?
set -e

DOCS="$(cat "$BASE/exports/restore_doc_count.txt")"
echo "[restore] $DOCS"
echo "[restore] verify rc=$VRC  elapsed=$(( $(date +%s) - T0 ))s"
[ -s "$BASE/exports/restore_verify.err" ] && {
  echo "[restore] verifier stderr:"; sed 's/^/[restore]   /' "$BASE/exports/restore_verify.err"; }

# Tear down the throwaway restore instance (keep the archive + reports for scoring).
docker rm -f siyuan-restore >/dev/null 2>&1 || true
echo "[restore] done in $(( $(date +%s) - T0 ))s (throwaway instance removed)"
exit $VRC
