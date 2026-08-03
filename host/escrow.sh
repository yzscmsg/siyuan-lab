#!/usr/bin/env bash
# Hard gate 2, second clause: "密钥和恢复说明不只存在于运行主机."
#
# A backup you can only decrypt or reason about from the box that died is not a
# backup. This packages the recovery-critical material into a single archive
# that host/pull.py drags off the VM:
#
#   secrets/          API token, access auth code, postgres password
#   VERSION           the exact pinned image tags in service
#   RECOVERY.md       ordered steps to rebuild from nothing
#   backups/*.manifest.json   what each archive contains + its sha256
#
# The archive is written to exports/escrow/ so the normal pull picks it up. In
# production this target is a NAS dataset + offsite replica, not the lab VM.
set -Eeuo pipefail

BASE=/opt/siyuan-lab
OUT="$BASE/exports/escrow"
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT"

SIYUAN_VER=$(cat "$BASE/VERSION" 2>/dev/null || echo unknown)

cat > "$OUT/RECOVERY.md" <<EOF
# SiYuan S1 recovery instructions

Generated: $(date -Iseconds)
Host at time of writing: $(hostname) ($(hostname -I | awk '{print $1}'))
Pinned SiYuan image: b3log/siyuan:${SIYUAN_VER}
Pinned proxy image:  caddy:2.8.4
Canonical store:     postgres:16 (container lifeos-pg, db lifeos)

## What is authoritative

SiYuan is an authoring workspace only. If everything in this archive is lost but
LifeOS Postgres and the NAS archive survive, no canonical data is lost -- the
notes are recoverable from the registered export. The reverse is NOT true.

## Rebuild from zero

1. Provision a host with Docker and create /opt/siyuan-lab.
2. Restore secrets/ from this archive (chmod 600).
3. Restore the newest backups/siyuan-*.tar.gz into /opt/siyuan-lab/workspace:
       mkdir -p /tmp/r && tar -xzf <archive> -C /tmp/r
       rm -rf /opt/siyuan-lab/workspace && mv /tmp/r/workspace /opt/siyuan-lab/workspace
       chown -R 1000:1000 /opt/siyuan-lab/workspace
4. Verify the archive checksum against its .manifest.json before trusting it.
5. Boot the pinned tag:
       bash host/deploy.sh
   deploy.sh re-reads secrets/authcode; it will NOT mint a new one if present.
6. The restored instance carries its OWN api token in workspace/conf/conf.json.
   Re-extract it into secrets/api_token; the escrowed token belongs to the old
   instance and will 401.
7. Open every notebook and wait for indexing before trusting a doc count:
       python3 scripts/verify_restore.py
8. Rebuild the canonical store if needed:
       bash host/lifeos_pg.sh          # applies migrations idempotently
       python3 scripts/lifeos_handoff.py

## Rollback

VERSION holds the tag in service, PREV_VERSION the previous one.
       bash host/rollback.sh
Rollback swaps the image tag only. The workspace format is forward-compatible
within 3.7.x; crossing a minor version requires a restore, not a rollback.

## Known recovery hazards (observed in S1)

- Extracting the tarball over the live workspace while the kernel is running
  will move data out from under the container. Extract to a temp dir, stop the
  container, then swap.
- mkdir the restore target before mv and you will nest workspace/workspace and
  the kernel will boot to an empty view.
- zstd is not installed on this host; archives are gzip.
EOF

TAR="$OUT/escrow-${STAMP}.tar.gz"
tar -czf "$TAR" \
  -C "$BASE" secrets \
  -C "$BASE" VERSION \
  $( [[ -f "$BASE/PREV_VERSION" ]] && echo "-C $BASE PREV_VERSION" ) \
  -C "$OUT" RECOVERY.md \
  $( ls "$BASE"/backups/*.manifest.json >/dev/null 2>&1 && echo "-C $BASE $(cd "$BASE" && ls backups/*.manifest.json | tr '\n' ' ')" )

sha256sum "$TAR" | awk '{print $1}' > "$TAR.sha256"

# Verify by READING BACK the archive. Asserting "contains_recovery_doc: true"
# without looking is exactly the kind of unchecked claim hard gate 2 exists to
# catch - an escrow you never opened is not an escrow.
LISTING="$(tar -tzf "$TAR")"
has() { printf '%s\n' "$LISTING" | grep -q "$1" && echo true || echo false; }
N_SECRETS="$(printf '%s\n' "$LISTING" | grep -c '^secrets/[^/]\+$' || true)"
RESTORE_OK="$(tar -xzOf "$TAR" RECOVERY.md >/dev/null 2>&1 && echo true || echo false)"

cat > "$OUT/escrow_report.json" <<EOF
{
  "archive": "$(basename "$TAR")",
  "sha256": "$(cat "$TAR.sha256")",
  "bytes": $(stat -c%s "$TAR"),
  "created": "$(date -Iseconds)",
  "entries": $(printf '%s\n' "$LISTING" | wc -l),
  "contains_secrets": $(has '^secrets/'),
  "secret_files": $N_SECRETS,
  "contains_recovery_doc": $(has '^RECOVERY.md$'),
  "recovery_doc_extractable": $RESTORE_OK,
  "contains_version_pin": $(has '^VERSION$'),
  "contains_backup_manifests": $(has '^backups/.*\.manifest\.json$'),
  "offhost_target": "exports/escrow (pulled to the operator workstation by host/pull.py)"
}
EOF

echo "[escrow] $TAR"
echo "[escrow] sha256 $(cat "$TAR.sha256")"
echo "[escrow] pull it off this host: python host/pull.py"
