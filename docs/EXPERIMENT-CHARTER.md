# SiYuan Lab Experiment Charter

- Status: Active
- Updated: 2026-08-04
- Parent architecture: `family-lifeos` ADR-0010

## Question

Does SiYuan provide enough editing and navigation value to remain an optional
single-owner LifeOS workspace while preserving portability, recoverability and
low maintenance?

## Current answer

`ADOPT` for the optional authoring-workspace capability only, based on 83.9/90
assessed points and the recorded S1 hard-gate evidence. The result does not
adopt SiYuan as an authoritative store, permission system, family identity
service or required LifeOS dependency.

## Repository boundary

This repository may contain:

- pinned SiYuan/Caddy lab deployment;
- deterministic synthetic corpus and acceptance tests;
- supported API/export adapters;
- fidelity, security, backup, restore, upgrade and maintenance evidence;
- adopt/hold/reject decisions.

This repository must not own:

- LifeOS product migrations or domain schemas;
- a competing LifeOS API or production family facade;
- authoritative family evidence or artifacts;
- real health, identity or financial data;
- unique logic required to recover LifeOS.

## Data rule

Use synthetic or safely de-identified data. Any later real-data authoring trial
requires the parent LifeOS G3 security/recovery gate, a separate non-lab
instance and an explicit data/retention decision.

## Integration seam

SiYuan communicates only through its supported API or portable Markdown/assets
export. LifeOS assigns canonical IDs, checksums, provenance, permissions and
release state. No integration reads SiYuan's internal database or copies
LifeOS migrations into this repository.

## Current work

1. Keep the facade visibly labelled and isolated as a synthetic-data PoC.
2. Remove copied product migrations/code in the repository-boundary change.
3. Point adapters/tests at a pinned LifeOS contract or local integration
   checkout.
4. Retain the export, rebuild, restore, upgrade and maintenance evidence.
5. Reassess SiYuan after the Health artifact pilot using measured owner effort.

## AI and human roles

AI may generate fixtures, execute API/export/fidelity/security/regression tests,
rebuild disposable instances and summarize overnight results. A human must
judge editing usefulness, mobile usability, data fidelity, residual security
risk, maintenance effort and the final adopt/hold/reject decision.

AI cannot merge, deploy real data, waive a failed hard gate or declare its own
test oracle correct.

## Exit criteria

Move SiYuan to `hold` or `reject` if:

- export/rebuild loses material content or links;
- it becomes a second authoritative copy;
- weekly maintenance exceeds the measured benefit;
- removal prevents LifeOS recovery;
- secure owner-only operation cannot be maintained;
- the plain portable artifact workflow provides comparable usability with less
  operational cost.

An abandoned experiment is disabled and documented; it is not left running as
an accidental production dependency.
