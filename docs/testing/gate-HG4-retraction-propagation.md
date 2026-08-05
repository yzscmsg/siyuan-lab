---
id: HG4
title: Deletion / retraction propagates; no user-invisible copy remains AI-retrievable
status: PASS
source: docs/implementation/03-s1-scorecard.md §Part1#4; scripts/s1_acceptance.py (stage retraction); scripts/retraction_test.py
last_run: 2026-08-03 (VM 192.168.88.9)
recorded_by: s1_acceptance.py (retraction stage, destructive)
---

# HG4 — Retraction propagation across all layers

## Goal
When a document is deleted/retracted, the deletion **propagates**; no
user-invisible copy remains AI-retrievable. Clause: *"删除/撤回能传播；不会留下用户
不可见但 AI 仍可检索的副本。"*

## Scope — 5 layers
- L1 SiYuan index
- L2 filesystem (workspace blobs)
- L3 portable export (`exports/markdown/`)
- L4 LifeOS canonical (`core.document`)
- L5 orphan assets

## Prerequisites / Dependencies
- HG1 export path established (L3 is the export).
- HG5 canonical store live (L4).
- Destructive: the test **deletes a document** — run on a disposable clone or
  accept the deletion in the lab workspace.

## Inputs
- `./run.sh` lifecycle + `python3 scripts/retraction_test.py`.
- A target doc id to delete.

## Expected output / pass criteria
- After deletion: absent in L1–L4; no orphaned asset references remain (L5);
  export no longer leaves placeholders or orphaned assets.
- `hard_gate_4_pass = true` in `exports/retraction_report.json`.

## Steps (human-steppable)
1. Capture baseline counts per layer (index hit, file exists, export md exists,
   `core.document` row, asset reference).
2. `python3 scripts/retraction_test.py` — performs the delete and re-checks each
   layer.
3. Confirm L1–L4 all report absence and L5 reports no dangling asset.
4. Read `exports/retraction_report.json` → `hard_gate_4_pass == true`.

## Recorded result (actual run, 2026-08-03)
- 5 layers verified: L1 SiYuan index, L2 filesystem, L3 portable export, L4
  LifeOS canonical, L5 orphan assets.
- Deletion propagates across all; export no longer leaves placeholders or
  orphaned assets.
- `hard_gate_4_pass = true`. → **PASS**.

## Issues found / notes
- Two behaviours existed because hard gate 4 caught them (now fixed): export
  previously left placeholders and orphaned assets. Both resolved.
- The AI/derived layer (Dify RAG) is rebuildable from canonical, so a retraction
  that clears L4 + re-indexes leaves no AI-retrievable copy.

## Re-run
```bash
python3 scripts/s1_acceptance.py --stages retraction   # destructive: deletes a doc
```
