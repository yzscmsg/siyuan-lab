# ADR-0003: SiYuan is a single-user workbench, not the family permission system

- Status: Accepted
- Date: 2026-08-03
- Relates to: FamilyLifeOS ADR-0004 (health-data sensitivity and access logging)

## Context

The candidate role for SiYuan was "family knowledge workbench" — implying several
family members, some shared material and some private material. The S1 protocol
requires testing the *actual* permission model rather than the intended one, and
sets a hard gate: unauthorised users, logs, models and indexes must not be able
to see forbidden fields.

Two notebooks were created to test the intent: `family-shared` and
`person-private`.

## Evidence

`scripts/perm_matrix.py` and `scripts/negative_tests.py`:

- A single API token reads **every** notebook, including `person-private`
  (`single_token_reads_all` true for all three notebooks).
- Notebook configuration exposes **no** `permission`, `acl` or `share` key —
  there is no per-notebook ACL surface to configure.
- Search executed with that one token returns hits from all notebooks and leaks
  private document paths (`/person-private/native/n06`, …).
- Self-hosted SiYuan issues one token per instance. There is no user concept to
  attach an ACL to.

Separately: backup archives include `conf/conf.json`, which contains the API
token in plaintext.

## Decision

1. **SiYuan is positioned as a single-user authoring workbench.** It is *not*
   the family permission system and must never be assigned that role.
2. **A notebook is an organisational folder, not a security boundary.** Do not
   place material in SiYuan that some family member must not see.
3. **Any real isolation is enforced outside SiYuan** by exactly one of:
   - a **separate instance** per person or boundary (containers, volumes, tokens
     and NAS ACLs all separate) — consistent with **RK-004** (rag-lab-kit instance isolation)
     isolation, where an organisational boundary is never treated as a security
     boundary; or
   - an **authenticating gateway** that terminates the user session, enforces the
     LifeOS ACL, and only then talks to SiYuan with the instance token.
4. **The API token is a full-instance credential.** Treat it as root-equivalent
   for that instance. It is never handed to a browser, an AI agent, or any
   component that processes untrusted input.
5. **Backup archives are secret material** because they embed the token. Encrypt
   at rest and exclude them from every path an AI layer can read.
6. **Sensitive categories are excluded from SiYuan for the duration of the
   trial** — specifically anything in scope for Phase 0.5 field-level ACL
   (KYC/AML, health records). Those stay in LifeOS where field-level ACL and the
   JSONL audit trail exist.

## Consequences

- The multi-user family scenario is not served by a single SiYuan instance.
  Serving it means N instances (N× upgrade, backup and monitoring cost) or
  building the gateway. Neither cost is inside the S1 budget.
- This is the finding that caps the S1 verdict at `trial` rather than `adopt`.
  Per the protocol: *if multi-user isolation is insufficient, it can only be
  positioned as a single-person workbench, not the family permission system.*
- The hard gate "unauthorised users/logs/models/indexes must not see forbidden
  fields" is satisfied only **conditionally** — by keeping forbidden fields out
  of SiYuan entirely, not by SiYuan enforcing anything.
