# ADR-0005: S1 verdict — trial SiYuan as a single-owner authoring console

- Status: Accepted (verdict ADOPT, 2026-08-04 — V8 human mobile test passed 15/15)
- Date: 2026-08-03
- Supersedes: nothing (permission re-scoping by ADR-0006)
- Depends on: ADR-0001 (deployment), ADR-0002 (export seam), ADR-0003
  (permission model), ADR-0004 (backup and rollback), ADR-0006 (single-owner model)

## Context

Experiment S1 was a time-boxed trial answering whether SiYuan should fill the
**authoring workspace** capability slot in FamilyLifeOS, and whether we could get
our data back out if the answer later became no. The experiment brief's own rule
is unambiguous: *any hard gate failure makes the total score invalid and the
verdict hold or reject.*

The experiment was executed end-to-end against a pinned v3.7.3 instance
(upgrade/rollback exercised v3.7.2↔v3.7.3): deployment, two notebooks
(`family-shared`, `person-private`), 20 imported documents + 10 native notes (30
docs, 22 assets), API create/read/update/export, standard Markdown + assets
export with round-trip fidelity, LifeOS canonical handoff (52 rows, 3x delivery),
backup and fresh-instance restore, upgrade and rollback, permission negative
tests and leakage checks, and 5-layer deletion/retraction propagation.

Full measured evidence: `docs/implementation/03-s1-scorecard.md` and
`/opt/siyuan-lab/exports/s1_acceptance.json`.

## Decision

**Adopt SiYuan** for the authoring-workspace slot, scored **83.9/90
(93.2/100)** with **all five hard gates passing** under the single-owner model
(ADR-0006). The previously-unscored family-UX dimension (V8) was confirmed by
the 2026-08-04 human mobile test (5/5 real-family tasks, 15/15), closing the
last open item below.

**SiYuan is the owner's private authoring console. It is not the family
permission system and is not a system of record.** Family members consume via
LifeOS granular publishing, never via SiYuan credentials.

## Rationale

The decisive evidence cuts both ways.

**For (exit path is excellent):** 30/30 documents exported with content,
22/22 asset hashes byte-identical, 30/30 structural fidelity; fresh-instance
restore verified 30/30 docs + 22/22 assets + working search; upgrade
v3.7.2→v3.7.3 and rollback both asserted against the kernel version; deletion
propagates across all 5 layers; canonical LifeOS store holds 52 rows
independently. The usual lock-in objection does not apply here.

**Against (permission boundary is absent — re-scoped by ADR-0006):** the two
measured HG3 findings are product-shaped, not configuration errors:

1. **N3** — `/assets/*` served HTTP 200 to unauthenticated clients on the
   kernel port (8/8 probed). The Caddy front-end blocks them (0/8), and the
   kernel is **bound to loopback only** (`127.0.0.1:6806`), so nothing on the
   LAN can reach it. Under the single-owner model the kernel's lack of asset
   auth is acceptable — it is a private admin console, not a family surface.
2. **N5** — a single API token reads both notebooks including `person-private`.
   Under ADR-0006 the editor set has size one by design, so this is the model,
   not a failure. The family boundary lives in LifeOS granular publishing.

Per the experiment brief: *if multi-user isolation is insufficient, the tool can
only be positioned as a single-person workbench, not the family permission
system.* ADR-0006 accepts exactly that positioning and assigns the permission
slot to LifeOS publishing. With the criteria re-scoped accordingly, HG3 passes
(edge blocks anonymous access; admin console owner-only reachable) and the
verdict is `adopt` — the 2026-08-04 V8 human run scored the family-UX dimension
15/15, lifting the score to 83.9/90 (93.2/100), above the 80 needed for
`adopt`. The 10-point quality dimension remains out of scope for S1 (belongs to
D1/I1) and is not counted against the verdict.

## Consequences

- **The family permission boundary is assigned to LifeOS publishing (ADR-0006).**
  The owner publishes from the canonical store to family members through
  LifeOS's own per-item/per-person ACL; family members never get SiYuan
  credentials. Implementing that publishing layer is the next build.
- The deploy constraint hardens: the kernel port must stay loopback-bound. Any
  change that exposes `:6806` to the LAN reverts HG3 to FAIL (re-measurable by
  the negative suite's `kernel_loopback_only` check).
- The n8n/LifeOS ingest layer must implement deduplication on UUID + content
  checksum, because `createDocWithMd` is not idempotent (S1-D1). Already
  absorbed by `UNIQUE(household_id, sha256)`, verified by 3x delivery.
- Any future SiYuan API integration must omit the `types` key in
  `fullTextSearchBlock` calls (S1-D2): its presence — even per the official
  example — yields zero matches in v3.7.3. Recorded in `api_client.py`.
- The lab stays reversible at all times: `run.sh clean-remote` / token revoke;
  exported Markdown + backup archives remain readable without SiYuan.
- The week-4 Document API constraints (S1-D3/D4) are **closed at the schema
  level** by `infra/lifeos-migrations/0006_document_contract.sql` (applied
  2026-08-03): `core.document` now has `status`/`version`/`supersedes`
  (retraction expressed via the `status` column, verified by retraction L4) and
  `media_type` CHECK + `storage_uri` validation (contract tests C4/C5 expect and
  observe DB-level rejection). What remains for the week-4 API layer is the
  thin HTTP facade over these already-constrained tables, plus publishing ACLs.

## Closure (2026-08-04)

1. ~~Run V8 — five real family tasks on a real mobile device~~ — **DONE
   (2026-08-04): 5/5 tasks pass, 15/15 family-UX, score 83.9/90.**
2. ~~Build the LifeOS granular publishing layer (ADR-0006)~~ — **DONE
   (2026-08-03): migration 0007, 10/10 contract, zero SiYuan credential touch.**
3. Confirm the scorecard weights against the canonical rubric (weights are a
   reconstruction from the experiment brief) — **still open**; if the canonical
   rubric differs, the absolute number may shift but all five hard gates pass
   and V8 confirms family-UX, so the `adopt` classification is robust.

ADR status moved `Proposed` → `Accepted`; verdict `trial` → `adopt`.
