#!/usr/bin/env bash
# Sync vendored LifeOS product migrations and scripts from family-lifeos.
#
# Per ADR-0007 and ADR-0011, siyuan-lab does NOT own product schemas, migrations,
# or release code. family-lifeos is the canonical source. This script copies the
# minimum set needed for the lab VM to apply migrations and run the Ingest API.
#
# Run this BEFORE pushing to the lab VM (run.sh push / deploy).
# The synced files are .gitignored and must not be committed to siyuan-lab.
#
# Usage: bash scripts/sync_from_family_lifeos.sh [PATH_TO_FAMILY_LIFEOS]
set -Eeuo pipefail

FAMILY_LIFEOS="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../family-lifeos" 2>/dev/null && pwd || echo "")}"

if [[ -z "$FAMILY_LIFEOS" ]] || [[ ! -d "$FAMILY_LIFEOS/db/migrations" ]]; then
  echo "ERROR: family-lifeos not found at '$FAMILY_LIFEOS'." >&2
  echo "Usage: bash scripts/sync_from_family_lifeos.sh /path/to/family-lifeos" >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"

echo "[sync] source: $FAMILY_LIFEOS"
echo "[sync] target: $REPO_ROOT"

# 1. Migrations
MIG_SRC="$FAMILY_LIFEOS/db/migrations"
MIG_DST="$REPO_ROOT/infra/lifeos-migrations"
mkdir -p "$MIG_DST"
for f in "$MIG_SRC"/*.sql; do
  fn="$(basename "$f")"
  cp "$f" "$MIG_DST/$fn"
  echo "[sync] migration: $fn"
done

# 2. Ingest API + seeder (vendored for lab VM; canonical in family-lifeos)
for f in lifeos_api.py seed_service_token.py; do
  if [[ -f "$FAMILY_LIFEOS/scripts/$f" ]]; then
    cp "$FAMILY_LIFEOS/scripts/$f" "$REPO_ROOT/scripts/$f"
    echo "[sync] script:   $f"
  fi
done

# 3. Contract test (vendored for lab VM)
if [[ -f "$FAMILY_LIFEOS/tests/test_ingest_api_contract.py" ]]; then
  cp "$FAMILY_LIFEOS/tests/test_ingest_api_contract.py" "$REPO_ROOT/scripts/ingest_api_test.py"
  echo "[sync] test:     ingest_api_test.py"
fi

echo "[sync] done. Synced files are .gitignored -- do not commit them."
