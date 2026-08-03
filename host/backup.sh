#!/usr/bin/env bash
# S1 backup: consistent snapshot of the SiYuan workspace volume + conf.
# Stops the kernel so in-flight writes flush, tars, restarts. Records a manifest.
set -euo pipefail
BASE=/opt/siyuan-lab
WS="$BASE/workspace"
BACK="$BASE/backups"
TS="$(date +%Y%m%d-%H%M%S)"
ARCH="$BACK/siyuan-$TS.tar.gz"
mkdir -p "$BACK"

echo "[backup] stopping kernel for consistent snapshot"
docker stop siyuan-poc >/dev/null 2>&1 || true
sleep 2

DOC_COUNT="$(find "$WS/data" -name '*.sy' 2>/dev/null | wc -l)"
tar --gzip -cf "$ARCH" -C "$BASE" workspace
SZ="$(stat -c %s "$ARCH")"

echo "[backup] starting kernel"
docker start siyuan-poc >/dev/null 2>&1 || true

cat > "$BACK/siyuan-$TS.manifest.json" <<JSON
{
  "archive": "$(basename "$ARCH")",
  "timestamp": "$TS",
  "workspace_doc_count_sy": $DOC_COUNT,
  "size_bytes": $SZ,
  "sha256": "$(sha256sum "$ARCH" | cut -d' ' -f1)"
}
JSON
echo "[backup] wrote $ARCH (docs=$DOC_COUNT, $((SZ/1024)) KiB)"
ls -1 "$BACK"/*.tar.gz | tail -5
