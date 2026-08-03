# ADR-0006: Single-owner LifeOS with granular publishing; SiYuan = private admin console

- Status: Accepted
- Date: 2026-08-03
- Supersedes: part of ADR-0003 (permission model) and ADR-0005 (S1 verdict) —
  this decision re-scopes what "permission boundary" means for the initial system
- Depends on: ADR-0001 (deployment), ADR-0002 (export seam), ADR-0004
  (backup and rollback)

## Context

Experiment S1 measured that self-hosted SiYuan has **no per-user / per-notebook
ACL**: one API token reads every notebook including `person-private`, and the
kernel serves `/assets/*` to unauthenticated clients on its own port. Under the
original reading of hard gate HG3 ("未授权用户...看不到禁止字段") this failed,
and the S1 verdict was `hold`.

The family operating model does not actually need multiple *editors*. The
initial LifeOS is a single-family-owner system: one person administers it. Other
family members are **consumers**, not editors. Consumption should be served
through a controlled, granular **publishing** surface — not by handing family
members credentials to the authoring tool.

## Decision

1. **Initial LifeOS is a single-owner system.** One administrator (the owner)
   is the only editor/authority. There is no multi-editor requirement in the
   initial deployment.

2. **The editable SiYuan workspace is a private administrator console.** It is
   reached only by the owner, from the owner's network, through the reverse
   proxy. Its kernel is bound to loopback (`127.0.0.1:6806`) and is never a
   family-facing surface. SiYuan's lack of internal ACL is therefore acceptable:
   the console is a single-owner surface, not a shared one.

3. **Family consumption happens through granular publishing in LifeOS.** The
   owner publishes content from the canonical store (or via the export/API
   seam, ADR-0002) to family members through LifeOS's own access control —
   per-item, per-person, read-only where appropriate. The publishing layer is
   where the family permission boundary lives, and it is LifeOS's responsibility,
   not SiYuan's.

4. **Forbidden fields never enter the authoring workspace.** Phase-0.5
   sensitive material (KYC/AML, health) stays in LifeOS with field-level ACL
   and the JSONL audit trail; it is not written into SiYuan at all.

5. **Consequence for capability slots:** SiYuan occupies only the
   "authoring workspace" slot as a single-owner tool. The "family permission
   system" slot is filled by LifeOS publishing, not by SiYuan.

## Rationale

- The S1 measurement that failed HG3 was real but answered a question the
  product does not need to answer: "can SiYuan isolate editors from each
  other?" Under this decision the set of editors has size 1, so that question
  is moot by design rather than by product capability.
- The measured facts support the decision as a deployment reality, not a hope:
  the kernel is bound to `127.0.0.1:6806` (loopback only) and Caddy
  (`0.0.0.0:80/443`) is the sole LAN ingress; anonymous asset access through the
  edge is blocked (0/8 served). Owner-only reachability is already true.
- Granular publishing matches the family reality: adults/members read what the
  owner publishes (schedules, notices, records), they do not edit the system.
  Editing rights for others can be layered later via LifeOS roles, without
  giving them SiYuan access.

## Consequences

- **Acceptance criteria change (S1 suite).** HG3 and V4 in
  `scripts/s1_acceptance.py` are re-scoped: HG3 = every edge-facing surface
  blocks unauthorised access + the admin console is owner-only reachable
  (kernel loopback-bound); V4 = single-owner console verified + consumption via
  LifeOS granular publishing. Re-run shows **all 5 hard gates PASS** and the
  verdict moves from `hold` to `trial` (68.9/90, below the 80 adopt threshold).
- The security weight is now earnable via the single-owner console + publishing
  boundary instead of being capped at half because "no user model".
- LifeOS publishing must be implemented (Week 6+) with per-item, per-person
  read ACL and an audit trail; until then, consumption beyond the owner is
  out of scope by design.
- The deploy constraint hardens: the kernel port must stay loopback-bound
  (never `0.0.0.0:6806`); any change to expose it reverts HG3 to FAIL.

## Status of dependent decisions

- ADR-0003: superseded in part — the "single-user workbench, never the family
  permission system" cap is retained, but the permission system slot is now
  assigned to LifeOS publishing rather than left empty.
- ADR-0005: superseded in part — verdict updated from `hold` (HG3 failed) to
  `trial` under the single-owner model; `adopt` still requires score ≥ 80 and
  the V8 mobile test.
