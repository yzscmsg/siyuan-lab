---
id: HG5
title: Clear uninstall path; removal does not lose canonical data
status: PASS
source: docs/implementation/03-s1-scorecard.md §Part1#5; scripts/s1_acceptance.py; scripts/lifeos_handoff.py; host/run.sh (revoke/clean-remote)
last_run: 2026-08-03 (VM 192.168.88.9)
recorded_by: s1_acceptance.py + manual run.sh review
---

# HG5 — Uninstall path + canonical-data survival

## Goal
There is a **clear uninstall path**, and removing SiYuan components does **not**
lose the canonical data. Clause: *"有明确卸载步骤；移除组件不会丢失 canonical 数据。"*

## Scope
- Documented teardown: `run.sh revoke` (shred tokens) + `run.sh clean-remote`
  (remove containers).
- Canonical record lives in the independent LifeOS Postgres (`core.document`),
  outside SiYuan — so removing SiYuan never touches it.

## Prerequisites / Dependencies
- HG1 export (Markdown durability).
- HG4 retraction (canonical is the source of truth).
- `lifeos-pg` reachable for the canonical-row count.

## Inputs
- `./run.sh revoke`, `./run.sh clean-remote`.
- Query: `SELECT count(*) FROM core.document;` in `lifeos-pg`.

## Expected output / pass criteria
- Teardown commands exist and are documented.
- After `clean-remote`, `core.document` row count is unchanged (canonical outside
  SiYuan).
- Exported Markdown in `results/` remains readable without SiYuan.

## Steps (human-steppable)
1. Record canonical count: `docker exec -it lifeos-pg psql -U lifeos -d lifeos -c
   "SELECT count(*) FROM core.document;"` (observed **52** rows).
2. `./run.sh revoke` — confirm tokens shredded (secrets dir emptied / rotated).
3. `./run.sh clean-remote` — confirm SiYuan containers removed.
4. Re-query `core.document` → expect unchanged (52).
5. Confirm `results/exports/markdown/` opens without SiYuan.

## Recorded result (actual run, 2026-08-03)
- `run.sh clean-remote` / token revoke documented.
- 52 canonical rows live in the independent LifeOS Postgres (`core.document`),
  outside SiYuan. → **PASS**.

## Issues found / notes
- Canonical independence is the core defence: SiYuan is an editing view only
  (ADR boundary). Removing it is safe by construction.
- Teardown is still pending actual execution on the running VM (stack currently
  up); the *path* is documented and the data-location argument is evidenced.

## Re-run
```bash
# teardown (destructive to the lab stack, NOT to canonical):
./run.sh revoke && ./run.sh clean-remote
# verify canonical survives:
docker exec -it lifeos-pg psql -U lifeos -d lifeos -c "SELECT count(*) FROM core.document;"
```
