# LifeOS granular publishing layer (ADR-0006 / ADR-0009)

- Status: built and contract-tested on VM `192.168.88.9` (2026-08-03)
- Relates to: ADR-0006 (siyuan-lab), ADR-0009 (family-lifeos), migration `0007`,
  `scripts/lifeos_publish.py`, roadmap §下一轮

## Why this exists

Under the single-owner model the editable SiYuan workspace is a **private admin
console** (kernel loopback-bound, owner-only via Caddy). Family members are
**consumers**. They must consume through LifeOS's own per-item access control and
**never hold a SiYuan credential**. This module is that consumer boundary.

## What it is

Schema (`infra/lifeos-migrations/0007_publishing_layer.sql`, mirrored to
`family-lifeos/db/migrations`):

- `core.publish_grant` — one row per (document, scope). Scope is **exactly one**
  of: a single person, a role (`owner`/`adult`/`member`), or the whole household.
  Default-deny: a document with no grant is private to the owner console.
- `core.can_consume(doc, person)` — returns true iff the document is `active`,
  the person is a current household member, and a live (not revoked, not expired)
  grant covers them. Resolution lives in SQL, so no caller can silently forget
  the rule.
- `core.published_to(person)` — the feed a person may consume; delegates to
  `can_consume` (single source of truth).
- `publish_grant_owner_guard_tg` — trigger that makes **publish owner-only** and
  restricts person-scope grants to current household members. This is the
  concrete schema-side expression of "family consumption via LifeOS granular
  publishing; SiYuan is a private administrator console."

## Boundary proof — zero SiYuan credentials

`scripts/lifeos_publish.py` runs **only** against `lifeos-pg` and consumes from
the existing 51-row canonical fixture (the S1 handoff). It records every
host/container it touches; the report asserts `allowed_scope == ['lifeos-pg']`
and zero references to any SiYuan asset (`:6806`, the siyuan container, `/api/`,
the API token). Consumed content is read from `core.document.storage_uri` (a
`lifeos://` logical name), never a SiYuan path.

## Contract result (10/10 pass, 45 audit events)

| Case | Result |
| --- | --- |
| D1 default-deny (no grant) | pass |
| P1 person-scoped grant | pass |
| P2 role-scoped grant (member) | pass |
| P3 whole-household grant | pass |
| N1 ungranted doc denied | pass |
| N2 non-owner publish rejected (trigger) | pass |
| N3 revoked grant denied | pass |
| N4 expired grant denied | pass |
| P5 withdrawn doc not consumable | pass |
| N5 grant to non-member rejected (trigger) | pass |

Evidence: `results/exports/lifeos_publish_report.json` (pulled from VM).

## Gotcha fixed during the build

SQL function parameters named `doc_id`/`person_id` collided with column names
inside the role-matching subquery (`m.person_id = person_id` resolved to the
column, silently breaking person/role scope matching). Renamed to `p_doc`/`p_person`
prefix so parameters can never shadow columns. Lesson carried to the migration
comment.

## Carry-forward

The thin **HTTP facade** (API/Web) that wraps `can_consume`/`published_to` into a
family consumption endpoint — the Week-9+ PoC-3 (identity/RLS) deliverable — is
now **built**: `scripts/family_facade.py` adds real authentication
(`core.auth_account`, migration `0008`) on top of this authorization boundary,
replacing the V8 test surface's test-grade persona cookie. Design + test matrix:
`docs/implementation/06-family-facade.md`. The authorization boundary itself was
always schema-enforced and proven here; the facade reuses it unchanged.
