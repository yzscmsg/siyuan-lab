---
id: HG1
title: Open-format export + rebuild in a fresh environment (no manual DB repair)
status: PASS
source: docs/implementation/03-s1-scorecard.md §Part1#1; scripts/s1_acceptance.py (stage export/fidelity); scripts/export_md.py; scripts/fidelity.py
last_run: 2026-08-03 (VM 192.168.88.9)
recorded_by: s1_acceptance.py + human export review
---

# HG1 — Export & rebuild without manual database repair

## Goal
Prove the data can leave SiYuan in an **open format** and be **rebuilt in a
fresh environment**, and that we never have to hand-edit the database to recover.
Clause: *"能导出到开放格式，并在全新环境重建；不能依赖手工修数据库。"*

## Scope
- Standard Markdown + assets export of all 30 docs (20 corpus + 10 native notes).
- Asset SHA-256 manifest.
- Fresh-instance restore from the export (no SiYuan DB dump, no SQL surgery).
- Round-trip structural + textual fidelity.

## Prerequisites / Dependencies
- Stack deployed and seeded: `./run.sh deploy` then `./run.sh seed`.
- `lifeos-pg` not required for export itself, but the canonical store is the
  cross-check for "canonical data survives" (see HG5).
- `corpus/` present (original source for fidelity comparison).

## Inputs
- Running SiYuan workspace (owner session).
- `corpus/` originals.
- Output dir `exports/markdown/` + `exports/fidelity_report.json`.

## Expected output / pass criteria
- Export: **30/30** docs with content, **22/22** asset hashes match manifest.
- Fresh-instance restore: seeded_docs **30/30**, assets **22/22**, search works.
- Fidelity: **30/30** structural pass, **100%** word retention.
- Zero manual DB edits anywhere in the recovery path.

## Steps (human-steppable)
1. `./run.sh export` — generates `exports/markdown/` + asset hashes.
2. Human check: open 3 exported `.md` files; confirm titles, headings, inline
   images and asset links resolve to local files.
3. `./run.sh fidelity` — compares `corpus/` vs `exports/markdown/`.
4. Fresh-instance rebuild (destructive, separate port `:6807`):
   `python3 scripts/s1_acceptance.py --stages restore` (or `./run.sh restore-test`).
5. Verify the restored instance boots and search returns the 30 docs.
6. Confirm no `psql UPDATE/INSERT` manual fix was needed — if one was, the gate
   fails by definition.

## Recorded result (actual run, 2026-08-03)
- Export 30/30 docs with content; 22/22 asset hashes match.
- Fresh-instance restore: seeded_docs=30/30, assets=22/22, search=ok.
- Fidelity: 30/30 structural, 100% word retention.
- No manual DB repair performed. → **PASS**.

## Issues found / notes
- `createDocWithMd` is **not idempotent** (recorded in scorecard) — handled by
  the handoff layer's own idempotency, not a gate failure.
- The export is the durable exit path; `results/` holds the Markdown so data
  stays readable without SiYuan (also satisfies HG5).

## Re-run
```bash
python3 scripts/s1_acceptance.py --stages export,fidelity
# destructive fresh-instance check:
python3 scripts/s1_acceptance.py --stages restore
```
