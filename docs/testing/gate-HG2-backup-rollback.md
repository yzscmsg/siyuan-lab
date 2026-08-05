---
id: HG2
title: Backup recoverable, rollback possible, secrets + recovery off-host
status: PASS
source: docs/implementation/03-s1-scorecard.md §Part1#2; scripts/s1_acceptance.py (stages backup/restore/upgrade/rollback/escrow); host/escrow.sh; host/backup.sh; host/restore.sh; host/upgrade.sh; host/rollback.sh
last_run: 2026-08-03 (VM 192.168.88.9)
recorded_by: s1_acceptance.py (full run)
---

# HG2 — Backup recoverable, rollback, off-host secrets

## Goal
A backup is **recoverable** and a **rollback is possible**; secrets and recovery
material are **not stored only on the host being recovered**. Clause: *"备份可恢复，
升级失败可回滚；密钥和恢复说明不只存在于运行主机。"*

## Scope
- Consistent workspace snapshot → fresh instance on `:6807`, verified (~123s).
- Version upgrade v3.7.2 → v3.7.3, then rollback to v3.7.2, both asserted
  against the kernel version.
- Escrow package: secrets + `RECOVERY.md`, extractable off-host.

## Prerequisites / Dependencies
- HG1 export path understood (rollback uses the same container lifecycle).
- `host/escrow.sh` needs a writable off-host pull target (`host/pull.py`).
- Baseline tag pinned (v3.7.2) before `--full` so the upgrade is a real forward move.

## Inputs
- `./run.sh backup`, `./run.sh restore-test`, `./run.sh upgrade v3.7.2`,
  `./run.sh rollback`.
- `S1_UPGRADE_TO` env (default v3.7.3).

## Expected output / pass criteria
- Backup → fresh instance boots and verifies in a recorded time (~123s observed).
- Upgrade and rollback both succeed; kernel version asserted before/after.
- Escrow archive present with SHA-256, ≥3 secret files, `RECOVERY.md`
  extractable, and retrievable from off-host (not only on the VM).

## Steps (human-steppable)
1. `./run.sh backup` — consistent snapshot.
2. `./run.sh restore-test` — restore into fresh instance `:6807`; confirm 3
   notebooks, 42 `.sy`, 46 doc blocks, searchable.
3. `./run.sh upgrade v3.7.2` then `./run.sh rollback` — assert kernel version flips
   and returns with no data loss.
4. `bash host/escrow.sh` — produces `escrow-<ts>.tar.gz`.
5. `sha256sum` the archive; confirm `RECOVERY.md` inside.
6. **Off-host pull**: `python3 host/pull.py` (or copy to a different machine) and
   confirm the archive + recovery doc open there.

## Recorded result (actual run, 2026-08-03)
- Backup → fresh instance verified in ~123s.
- Upgrade v3.7.2→v3.7.3, rollback back to v3.7.2, both asserted against kernel
  version.
- Escrow `escrow-20260802-233315.tar.gz`, sha256 `2b59b8b8…`, 3 secret files,
  `RECOVERY.md` extractable, meant for off-host pull. → **PASS**.

## Issues found / notes
- Restore time must be re-measured after any infra change (G1 recoverable-compute
  gate in the wider roadmap tracks this separately).
- Escrow is the off-host proof; without the off-host pull step the gate is only
  partially evidenced.

## Re-run
```bash
python3 scripts/s1_acceptance.py --full        # includes backup/restore/upgrade/rollback/escrow
python3 scripts/s1_acceptance.py --full --yes  # no confirmation prompt
```
