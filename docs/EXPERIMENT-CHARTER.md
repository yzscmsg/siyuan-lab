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

1. ~~Keep the facade visibly labelled and isolated as a synthetic-data PoC.~~
   **Done 2026-08-06 (ADR-0012 §2).** The facade left this repository entirely:
   `family_facade.py`, `seed_facade_accounts.py` and `facade_smoke_test.py` now
   live in `family-lifeos` (`scripts/experimental/`, `tests/contract/`), the
   `/family*` Caddy route and `host/run_family_facade.sh` are deleted, and the
   destination directory is labelled *DEFERRED PoC — synthetic data only*.
2. ~~Remove copied product migrations/code in the repository-boundary change.~~
   **Done 2026-08-06 (ADR-0012 §2).** 2,570 lines of product-schema code stopped
   being owned here. See "Boundary status" below.
3. ~~Point adapters/tests at a pinned LifeOS contract or local integration
   checkout.~~ **Done 2026-08-06.** `scripts/sync_from_family_lifeos.sh` is the
   only path by which product code enters this working tree, and everything it
   writes is `.gitignore`d.
4. Retain the export, rebuild, restore, upgrade and maintenance evidence.
5. Reassess SiYuan after the Health artifact pilot using measured owner effort.

## Boundary status (2026-08-06)

The cross-repo audit found ~2,570 lines here that read and wrote `core.*` and
`audit.*` — a Principle 11 violation, since this repository is an experiment lab,
not a product owner. ADR-0012 §2 resolved it.

**No longer owned here** (canonical home is now `family-lifeos`):

| Was | Now | Synced back? |
|---|---|---|
| `scripts/lifeos_handoff.py` | `tests/contract/lifeos_handoff.py` | Yes — gitignored |
| `scripts/family_view.py` | `scripts/experimental/family_view.py` | Yes — gitignored |
| `scripts/seed_v8_grants.sql` | `scripts/experimental/seed_v8_grants.sql` | Yes — gitignored |
| `scripts/lifeos_publish.py` | `tests/contract/lifeos_publish.py` | No |
| `scripts/facade_smoke_test.py` | `tests/contract/facade_smoke_test.py` | No |
| `scripts/family_facade.py` | `scripts/experimental/family_facade.py` | No |
| `scripts/seed_facade_accounts.py` | `scripts/experimental/seed_facade_accounts.py` | No |

**Deleted:** `host/run_family_facade.sh`, `host/run_lifeos_api.sh`, and the
`/family*` + `/api*` routes in `infra/compose/Caddyfile`. The Ingest API edge is
now `family-lifeos/infra/compose/Caddyfile`.

**Retained under the ADR-0012 §1 read-mostly exception** — lab evidence that
reads `core.*` to prove a SiYuan-side property: `scripts/retraction_test.py`
(HG4 retraction propagation), `scripts/s1_acceptance.py` (S1 acceptance),
`scripts/v8_smoke_test.py` (V8 smoke). `host/lifeos_pg.sh` is also retained: it
applies *synced, gitignored* migrations, which is the sanctioned pattern, not a
vendored schema copy.

The three sync-back entries exist because retained evidence executes them —
`s1_acceptance.py`, `retraction_test.py`, `run.sh handoff` and `host/escrow.sh`
run `lifeos_handoff.py`; `v8_smoke_test.py` audits `family_view.py`'s source and
uses the `seed_v8_grants.sql` fixture. A gitignored synced copy is not ownership;
it is the same mechanism already used for migrations and `lifeos_api.py`.

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
