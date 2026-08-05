---
id: S1-V
title: S1 overall verdict driver (runs s1_acceptance.py)
status: ADOPT (83.9/90, 93.2/100)
source: docs/implementation/03-s1-scorecard.md; ADR-0005; scripts/s1_acceptance.py
last_run: 2026-08-04 (verdict upgraded trial→adopt after V8)
recorded_by: s1_acceptance.py + ADR-0005 update
---

# S1-V — Overall experiment verdict

## Goal
Combine the five hard gates (HG1–HG5) and the weighted score into a single
decision: **hold / trial / adopt / reject**. Any hard-gate failure invalidates
the score. Clause: *"任何硬门槛失败时总分无效。"*

## Scope
- Hard gates: HG1–HG5 (all PASS under ADR-0006).
- Weighted dimensions (20+20+20+15+15+10 = 90): data ownership/exit, security/
  permission, solo operating cost, features & family UX, recoverability,
  maintainability.
- V8 family-UX (15/15) closes the features dimension → score 83.9/90 ≥ 80.

## Prerequisites / Dependencies
- HG1–HG5 all PASS (gate-HG1 … gate-HG5 in this directory).
- V8 PASS (gate-V8-family-ux.md).
- `scripts/s1_acceptance.py` present and runnable on the VM.

## Inputs
- `--evaluate-only` reads existing stage reports; `--full` regenerates them.
- Optional weight reconciliation against the canonical rubric (see scorecard
  "Weights note").

## Expected output / pass criteria
- All five hard gates PASS.
- Weighted score ≥ 80 → **adopt**.
- Output: `exports/s1_acceptance.json` + `.md` with verdict + reason.
- Verdict logic: hard-gate fail → hold; gates pass & score<80 → trial; gates
  pass & score≥80 → adopt.

## Steps (human-steppable)
1. `python3 scripts/s1_acceptance.py --list` — confirm stages.
2. `python3 scripts/s1_acceptance.py --evaluate-only` — score from existing
   reports (read-only).
3. Review `exports/s1_acceptance.md` → Hard gates table + weighted score.
4. If regenerating: `python3 scripts/s1_acceptance.py --full --yes` (destructive:
   backup/restore/upgrade/rollback/retraction).
5. Confirm HG3 reading matches ADR-0006 (single-owner + LifeOS publishing).
6. Record verdict in ADR-0005.

## Recorded result (actual run)
- HG1–HG5: all PASS.
- Weighted: 20.0 + 20.0 + 13.9 + 15.0 + … = **83.9/90 (93.2/100)**.
- V8 15/15 closed the features dimension.
- **Verdict: ADOPT** for the optional single-owner authoring slot (ADR-0005
  updated 2026-08-04).

## Issues found / notes
- **Weights are a reconstruction** of the experiment brief's rubric (not
  committed to family-lifeos). The *evidence* and *hard-gate results* are
  objective; sanity-check the weights before treating 83.9 as final.
- 93.2% is a normalization over 90 assessed points, **not** 93.2/100 coverage of
  the wider LifeOS security/identity architecture.
- ADR-0007 defers the custom facade; this verdict does **not** certify the
  facade or the broader LifeOS authz for production.

## Re-run
```bash
python3 scripts/s1_acceptance.py --evaluate-only
python3 scripts/s1_acceptance.py --full --yes     # destructive regeneration
```
