# ADR-0004: Backup, restore and rollback for the SiYuan workbench

- Status: Accepted
- Date: 2026-08-03
- Relates to: FamilyLifeOS ADR-0005 (layered backup and restore testing)

## Context

The S1 hard gate requires that a backup is recoverable and a rollback is
possible, with secrets and recovery material held **outside** the host being
recovered. FamilyLifeOS ADR-0005 already establishes that a backup is not
considered successful until automated checks pass.

SiYuan's state is a single workspace directory (`data/`, `conf/`, `temp/`), so
the backup unit is obvious. The risk is not capturing it — it is proving the
capture is *restorable* somewhere else.

## Decision

1. **Cold snapshot.** `host/backup.sh` stops the kernel, waits for writes to
   flush, `tar --gzip` the workspace, restarts the kernel. A brief outage is
   preferred over a torn snapshot of a live SQLite index.
   (`zstd` is not present on this host; `tar --zstd` silently produces a 0-byte
   archive. Use gzip.)
2. **Every archive gets a manifest** recording archive name, timestamp, `.sy`
   document count, size and sha256. An archive without a manifest is not a backup.
3. **Restore is always tested into a *fresh* instance**, never over the live one.
   `host/restore.sh` extracts to a `mktemp -d`, moves it to a separate workspace
   path, boots a **throwaway** container on port 6807, verifies, then removes it.
4. **Verification is automated and content-based**, not "the container started":
   open all notebooks, wait for indexing, then assert notebook count, `.sy` file
   count and indexed document count.
5. **Rollback = redeploy the previous pinned tag.** `host/upgrade.sh` writes the
   outgoing tag to `PREV_VERSION`; `host/rollback.sh` redeploys it and re-runs
   the smoke test. Rollback does not depend on restoring a backup.
6. **A backup is taken before every upgrade**, without exception.
7. **Secrets live outside the archive's blast radius** — but note the archive
   *contains* `conf.json` with the API token, so archives are themselves secret
   material and must be encrypted at rest (see ADR-0003).

## Evidence

- Backup: `siyuan-20260802-165053.tar.gz`, 29.8 MB, 42 `.sy` files,
  sha256 `9bf8bbcc…da5c4`.
- Restore into a fresh instance: `notebooks=3 docs_sql=46 sy_files=42`,
  documents searchable, attachments present, **no manual database repair**.
- Upgrade/rollback: v3.7.3 → v3.7.2 → v3.7.3, smoke test passing at each step,
  document count unchanged. Downtime ≈ 20–40 s per switch, zero manual steps.

## Consequences

- Backup causes a short planned outage. Acceptable for a single-user workbench;
  would need a snapshot-based approach if this ever became always-on shared.
- **Rollback is only proven across a patch range.** SiYuan applies one-way data
  migrations on some minor upgrades. Across a minor version, assume rollback
  requires a *restore* (`make restore-test` semantics), not a tag swap, and
  verify on a clone before touching the live workspace.
- Restore leaves the archive and the verification count in place while removing
  the throwaway container, so evidence survives the test.
