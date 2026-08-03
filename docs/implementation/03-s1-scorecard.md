# S1 Scorecard — SiYuan as single-owner authoring console

- Experiment: S1, executed 2026-08-02 / 2026-08-03
- Subject: SiYuan v3.7.3 self-hosted, `192.168.88.9` (VM), Caddy 2.8.4 front
- Roadmap commit: `f597f61a68cd721eb0d2494673d50cd9e2cc8a58`
- Evidence: `exports/*.json` on the VM (`/opt/siyuan-lab/exports/`), acceptance report `exports/s1_acceptance.json`
- **Verdict: `TRIAL` — 68.9/90 (76.6/100), all five hard gates passing under the single-owner model (ADR-0006)**
- **Result file:** `exports/s1_acceptance.md` / `.json` (generated 2026-08-02/03)

> **Weights note.** The weighted rubric was supplied in the experiment brief and
> is not committed to the FamilyLifeOS repo. The weights below are my
> reconstruction of it from the brief's emphasis. The *evidence* and the
> *hard-gate results* are objective, measured by `scripts/s1_acceptance.py`; the
> weights are the one thing here you should sanity-check against your canonical
> rubric before treating 68.9 as final.

---

## Architecture decision applied (ADR-0006)

The owner's review resolved the HG3 permission finding with a design decision,
recorded in ADR-0006:

1. **Initial LifeOS is a single-owner system** — one administrator/editor.
2. **The editable SiYuan workspace is a private admin console** — kernel
   loopback-bound (`127.0.0.1:6806`), reached only by the owner via the reverse
   proxy; never a family-facing surface.
3. **Family consumption goes through LifeOS granular publishing** — per-item,
   per-person, read-only where appropriate. The publishing layer owns the family
   permission boundary, not SiYuan.

The acceptance criteria (HG3, V4) were re-scoped to this model; see
`scripts/s1_acceptance.py` and ADR-0006.

---

## Part 1 — Hard gates (any failure ⇒ hold or reject; score invalid)

| # | Gate | Result | Measured evidence |
| --- | --- | --- | --- |
| 1 | Open-format export **and** rebuild in a fresh environment, no manual DB repair | **PASS** | Export: 30/30 docs with content, 22/22 asset hashes match, 30/30 structural fidelity. Fresh-instance restore: seeded_docs=30/30, assets=22/22, search=ok. No manual DB repair anywhere. |
| 2 | Backup recoverable, rollback possible, secrets and recovery material outside the host being recovered | **PASS** | Backup → fresh instance on :6807 booted and verified in ~123s. Upgrade v3.7.2→v3.7.3, rollback back to v3.7.2, both asserted against the kernel version. Escrow: `escrow-20260802-233315.tar.gz`, sha256 `2b59b8b8…`, 3 secret files, RECOVERY.md extractable, meant for off-host pull via `host/pull.py`. |
| 3 | Unauthorised users / logs / models / indexes must not see forbidden fields | **PASS** (single-owner model, ADR-0006) | 7 surfaces tested, all secure. N1/N2/N4 (private doc, export, mutating API): 401 unauthenticated. N6/N7: no token/auth-code leakage in logs, backups or note content. N3: proxy blocks anonymous assets 0/8 **and kernel is loopback-only**. N5: single-owner console owner-only reachable — the design, not a leak. |
| 4 | Deletion / retraction propagates; no user-invisible copy remains AI-retrievable | **PASS** | 5 layers verified: L1 SiYuan index, L2 filesystem, L3 portable export, L4 LifeOS canonical, L5 orphan assets. Deletion propagates across all; export no longer leaves placeholders or orphaned assets. |
| 5 | Clear uninstall path; removal does not lose canonical data | **PASS** | `run.sh clean-remote` / token revoke documented. 52 canonical rows live in the independent LifeOS Postgres (`core.document`), outside SiYuan. |

**All five hard gates pass under ADR-0006.** The score below is therefore valid
for decision purposes.

---

## Part 2 — Weighted score

| Dimension | Weight | Score | Points | Measured evidence |
| --- | --- | --- | --- | --- |
| Data ownership & exit | 20 | 1.00 | **20.0** | Export+fidelity clean, fresh-instance rebuild verified, canonical store independent (52 rows in LifeOS Postgres) |
| Security & permission | 20 | 1.00 | **20.0** | Single-owner console owner-only reachable (kernel loopback-bound), edge blocks anonymous access; family boundary = LifeOS publishing (ADR-0006) |
| Solo operating cost | 20 | 0.695 | **13.9** | 2 containers for SiYuan (kernel+caddy); restore 2.1 min, upgrade+rollback 4.0 min, weekly maintenance 6.8 min |
| Features & family UX | 15 | 0.00 | **0.0** | UNSCORED until the 5 real family tasks are run on a real phone. **Protocol + test surface are READY** (docs/implementation/05-v8-mobile-test.md; `scripts/family_view.py` + Caddy `/family` route + `scripts/v8_smoke_test.py` 11/11). Grading rubric there maps a clean run to +15 (→ 83.9/90, above the 80 adopt threshold). |
| Integration & automation | 15 | 1.00 | **15.0** | Idempotent handoff into canonical store (3x delivery, zero SiYuan-internal reads); API suite green |
| Quality & performance | 10 | — | — | Out of scope for S1 (golden-set accuracy is D1/I1) |
| **Total** | **90 available** | | **68.9** | Normalised **76.6/100**; `adopt` needs ≥80 |

---

## Part 3 — Defects and findings (measured)

| ID | Severity | Finding | Disposition |
| --- | --- | --- | --- |
| S1-N3 | **High** | Kernel serves `/assets/*` to unauthenticated clients on its own port (`:6806`) — 8/8 probed HTTP 200. **But** the kernel is bound to loopback only and Caddy blocks the same assets at the edge (0/8). | Acceptable for a private admin console (ADR-0006). Hardened deploy rule: kernel port must stay loopback-bound; exposing it reverts HG3 to FAIL (auto-checked). |
| S1-N5 | High→**Design** | One API token reads both notebooks incl. `person-private`; no per-user/per-notebook ACL in the product. | By design under ADR-0006 (single owner). Family boundary lives in LifeOS granular publishing, not SiYuan. |
| S1-D1 | Medium | `createDocWithMd` is not idempotent — the same path yields a new doc id on every call. Retrying automation duplicates docs. | Dedupe above SiYuan. LifeOS `UNIQUE(household_id, sha256)` absorbs it, verified by 3x delivery in the handoff test. |
| S1-D2 | **High** | `/api/search/fullTextSearchBlock` returns **zero matches whenever the `types` key is present** — including the doc's own example `{"d":true,"h":true,"p":true}` and even `{}`. Omitting the key returns real hits. Three earlier "search=fail" V3 verdicts were this API quirk, not a broken restore. | Recorded in `api_client.py`; the search probe omits `types`. Any future SiYuan integration following the official example silently gets empty results. |
| S1-D3 | ~~Medium~~ **RESOLVED** | `core.document` had no `status`/`version`/`supersedes` column; withdrawal was only expressible in `metadata` jsonb. | **Fixed by `infra/lifeos-migrations/0006_document_contract.sql`** (applied 2026-08-03): adds `status` (CHECK active/superseded/withdrawn/archived), `version`, `supersedes` FK + no-self-supersede, partial index. Retraction L4 now expresses withdrawal via `core.document.status` (`status_column_exists: true`). |
| S1-D4 | ~~Medium~~ **RESOLVED** | `core.document` accepted any `media_type` and did not validate `storage_uri`. | **Fixed by migration 0006**: `media_type` CHECK allowlist + `storage_uri` CHECK (scheme:// required, no `..` traversal, no raw-IP authority). Contract tests C4/C5 now expect and observe DB-level rejection (`accepted=False`), flipped to blocking. |
| S1-D5 | Low | SiYuan boot takes ~120 s on this VM; upgrade and rollback each burn the full boot wait (121.3 s recorded, now honestly measured with POST probes). | Acceptable for weekly maintenance (6.8 min total) but not for hot failover. |

---

## Part 4 — Maintenance cost (measured)

Steady-state, measured by the acceptance suite timings:

| Operation | Wall time | Manual steps |
| --- | --- | --- |
| Deploy / redeploy | ~40 s | 0 (one command) |
| Backup | 11.4 s | 0 |
| Restore drill into fresh instance | 123.4 s | 0 |
| Upgrade (incl. kernel-version assertion) | 121.3 s | 0 |
| Rollback | 121.3 s | 0 |
| Full 14-stage acceptance suite | ~14 min | 0 (`run.sh accept-full`) |

Measured weekly maintenance load: **6.8 min** (one upgrade+rollback cycle + backup + smoke).

Excluded: first-time provisioning and debugging, itemised in the runbook's
gotcha blocks (compose plugin absent, token location, IPv6-less Docker pulls,
restore bugs, `caddy hash-password` EOF). One-time costs now captured in scripts.

---

## Part 5 — Conclusion

**`TRIAL`** — continue using SiYuan as the owner's private authoring console
under the single-owner model; do not adopt as a general family system yet.

Reasoning:

- **All five hard gates pass** under ADR-0006, so the score is valid. The
  single-owner decision turned the two HG3 findings from product blockers into
  accepted design properties — and the deployment already matched the model
  (kernel loopback-bound, edge blocking anonymous access).
- The exit path is genuinely good: 30/30 docs + 22/22 assets round-trip with
  byte-identical hashes, fresh-instance rebuild verified, canonical store
  independent. Lock-in risk is absent.
- Integration is proven end-to-end: idempotent LifeOS handoff (52 rows, 3x
  delivery, zero internal reads), API suite green.
- 68.9/90 is below the 80 adopt threshold, dominated by the **unscored**
  family-UX dimension (V8, human-only) and the 10-point quality dimension that
  belongs to D1/I1, not S1.

### Conditions attached to the trial

1. Single-owner authoring only; the editable SiYuan workspace is the owner's
   private admin console (ADR-0006).
2. Family consumption only via LifeOS granular publishing — never SiYuan
   credentials. Publishing layer is the next build.
3. No Phase-0.5-sensitive material (KYC/AML, health) in SiYuan. Those stay in
   LifeOS where field-level ACL and the audit trail exist.
4. LifeOS remains the system of record. A document that exists only in SiYuan
   does not exist.
5. Backup before every upgrade; monthly restore drill.
6. Kernel port stays loopback-bound — exposing `:6806` reverts HG3 to FAIL.

### What would move this to `adopt`

- **V8 mobile/family-task test run and coming back positive** (up to +15 on
  family-UX). The protocol and a runnable test surface now exist
  (docs/implementation/05-v8-mobile-test.md); the machine side is already
  verified (11/11). Only the human phone run remains — a clean run maps to
  +15 → 83.9/90, above the 80 threshold.
- The LifeOS granular publishing layer **is built** (migration `0007`) and a
  family member is proven to consume published items with **no SiYuan access
  at all** — both the schema contract (10/10) and the on-device surface
  (11/11) confirm the ADR-0006 boundary end-to-end.
- Together these push the score above 80.

### What would move this to `hold`

- The mobile experience proving bad enough that nobody actually writes in it.
  Portability and recoverability are worthless if the workbench goes unused —
  and that is precisely the evidence S1 could not gather on its own.
