#!/usr/bin/env bash
# Sync vendored LifeOS product migrations and scripts from family-lifeos.
#
# Per SL-0007, ADR-0011 and ADR-0012 §2, siyuan-lab does NOT own product schemas,
# migrations, or release code. family-lifeos is the canonical source. This script
# copies the minimum set needed for the lab VM to apply migrations, run the
# Ingest API, and execute the retained lab evidence scripts.
#
# Run this BEFORE pushing to the lab VM (run.sh push / deploy).
# The synced files are .gitignored and must not be committed to siyuan-lab.
#
# If a sync target is missing from family-lifeos this script FAILS rather than
# silently leaving a stale copy behind -- a stale vendored product file is the
# exact drift ADR-0012 exists to prevent.
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

# 4. Dependencies of the RETAINED lab evidence scripts (ADR-0012 §1 exception,
#    §2 move). These left siyuan-lab's git history on 2026-08-06; the lab still
#    executes them, so they are synced in as gitignored working copies.
#
#      lifeos_handoff.py  <- s1_acceptance.py, retraction_test.py,
#                            run.sh handoff, host/escrow.sh
#      family_view.py     <- v8_smoke_test.py (cats the source and greps it for
#                            forbidden SiYuan coupling)
#      seed_v8_grants.sql <- v8_smoke_test.py grant fixture
#
# Missing files are a hard error: v8_smoke_test.py would report a false PASS if
# it audited a stale copy.
sync_required() {  # $1 = source path under $FAMILY_LIFEOS, $2 = dest basename
  local src="$FAMILY_LIFEOS/$1" dst="$REPO_ROOT/scripts/$2"
  if [[ ! -f "$src" ]]; then
    echo "ERROR: required file missing in family-lifeos: $1" >&2
    echo "       (moved there by ADR-0012 §2 -- check the checkout is current)" >&2
    exit 2
  fi
  cp "$src" "$dst"
  echo "[sync] evidence: $2"
}

sync_required "tests/contract/lifeos_handoff.py"          "lifeos_handoff.py"
sync_required "scripts/experimental/family_view.py"       "family_view.py"
sync_required "scripts/experimental/seed_v8_grants.sql"   "seed_v8_grants.sql"

echo "[sync] done. Synced files are .gitignored -- do not commit them."
