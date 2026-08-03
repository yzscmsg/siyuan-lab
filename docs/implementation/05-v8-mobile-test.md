# V8 — Mobile / Family-UX Test (human-only)

- Status: **protocol + test surface READY** (2026-08-03); the 5 tasks below must
  still be run by a real person on a real phone. The machine side is already
  verified by `scripts/v8_smoke_test.py` (11/11 pass).
- Unblocks: S1 scorecard **Features & family-UX** dimension (weight 15, currently
  UNSCORED). A clean V8 run can lift the score above the `adopt` threshold (80).
- Relates to: ADR-0006 (siyuan-lab) / ADR-0009 (family-lifeos), migration `0007`
  (publishing layer), `scripts/family_view.py` (the test surface).

## Why this is human-only

The 15 family-UX points measure **whether a real family actually uses the
system on a real phone** — portability, readability, and the default-deny
boundary experienced by a human. No script can substitute for that judgment,
which is exactly why the scorecard left the dimension unscored until V8.

What *can* be automated is the surface itself and its boundary: that is proven
by `v8_smoke_test.py` (login → feed → granted doc → default-deny doc → audit →
zero SiYuan kernel reference). This document is the **human execution plan**
on top of that surface.

## Test surface (what the family points their phone at)

A minimal, read-only "LifeOS Family View" is served at:

```
https://192.168.88.9/family
```

- Reached through the same Caddy TLS edge as the SiYuan admin console, but on a
  **separate route** — family consumption never touches the SiYuan kernel.
- Identity is **test-grade**: the opening page shows three buttons —
  **Owner Lab / Adult Lab / Member Lab** — and tapping one assumes that persona
  (a cookie). Anyone who can reach the URL can pick any persona. That is fine
  for a controlled family trial; it is explicitly **not** production auth.
- Content is rendered from the lab archive (the S1 export markdown), never from
  SiYuan. The viewer process only ever talks to `lifeos-pg`.

### Prerequisites / device notes
1. Phone on the **same LAN/WiFi** as `192.168.88.9` (the lab VM).
2. Open the URL in the phone browser. You will get a **certificate warning**
   (Caddy uses an internal CA) — this is expected for the lab; accept/continue.
   A real deployment would use a proper cert.
3. **No SiYuan app, account, or credential is needed** by any family member.
   That is the whole point of ADR-0006.
4. Seeded publish scenario (see `scripts/seed_v8_grants.sql`):
   - **Household-wide:** `c01`, `c02`, `n06` — every member sees these.
   - **Person-scoped (Adult):** `n07` — only Adult Lab sees it.
   - **Role-scoped (member):** `n08` — the Member role sees it.
   - **Ungranted:** `n09` — no family member sees it (default-deny).

## The 5 real-family tasks

Each task is performed on a real phone by the named persona. Record the
observation and a pass/fail against the stated expectation. The "proves" column
maps the task to a V-criterion / ADR-0006 property.

---

### Task 1 — Adult reads a household-shared note
- **Who:** Adult Lab (or any adult family member), on their phone.
- **Do:** Open `https://192.168.88.9/family`, tap **Adult Lab**, open
  **c01** (a household-shared note) from the list, and read it.
- **Expect:** The item appears in the feed, opens, and the markdown renders
  legibly on the phone screen (headings, lists, bold readable; no raw markup).
- **Proves:** Household-wide publishing works end-to-end, and phone rendering is
  usable (family-UX substance).
- **Pass if:** item found → opened → readable, unaided.

### Task 2 — Member reads a member-role item
- **Who:** Member Lab, on their phone.
- **Do:** Tap **Member Lab**, confirm **n08** (member-role scoped) is in the
  feed, open and read it.
- **Expect:** n08 is visible and readable for the Member; this is a non-owner,
  non-adult consuming scoped content.
- **Proves:** Role-based scope serves the right people without owner/adult
  involvement.
- **Pass if:** n08 visible to Member → opened → readable.

### Task 3 — Person-scoped granularity (Adult personal vs Member)
- **Who:** Adult Lab, then Member Lab, on their phones.
- **Do:** As Adult Lab, confirm **n07** is in your feed and read it. As Member
  Lab, confirm **n07 is NOT in your feed** (and opening its URL directly shows
  "not shared").
- **Expect:** n07 is visible only to Adult Lab; the Member sees it absent and is
  denied if they try the URL.
- **Proves:** Per-person scope is respected across personas — the boundary is
  real, not cosmetic.
- **Pass if:** Adult sees n07; Member does not see it and is denied on direct URL.

### Task 4 — Default-deny on an unshared item (n09)
- **Who:** Any non-owner persona, on their phone.
- **Do:** Look for **n09** in your feed (it should be absent). Optionally try to
  open `https://192.168.88.9/family/doc?id=<n09-id>` directly.
- **Expect:** n09 is not listed, and the direct URL shows "This item is not
  shared with you." No content leaks.
- **Proves:** The default-deny rule holds on the actual device — a document
  with no grant is private to the owner console, confirming the family
  permission boundary (ADR-0006/HG3).
- **Pass if:** n09 absent from feed AND direct URL is denied with no content.

### Task 5 — Separation: family consumes, never authors (no SiYuan)
- **Who:** Any family member, on their phone.
- **Do:** Confirm you have **no SiYuan app/login**, cannot reach the authoring
  workspace, and the only thing you can do here is *read* shared items (no
  edit/create). Also confirm there is no prompt for any SiYuan credential.
- **Expect:** The family view is read-only; the editable SiYuan workspace is
  invisible to you. You consume LifeOS-published content only.
- **Proves:** The single-owner model is real on the device — family members are
  consumers via LifeOS, never editors of SiYuan (the core ADR-0006 decision).
- **Pass if:** read-only confirmed, no SiYuan credential/app reachable.

---

## Grading rubric → 15 family-UX points

Each of Tasks 1–4 earns up to **3 points** (12 total); Task 5 earns up to
**3 points** (separation). Award per sub-criterion:

| Task | +1 completed unaided | +1 content rendered/read on phone | +1 boundary behaved as expected |
| --- | --- | --- | --- |
| 1 household read | | | n/a |
| 2 member-role read | | | n/a |
| 3 person granularity | | | Adult sees / Member denied |
| 4 default-deny n09 | | | absent + URL denied |
| 5 no-SiYuan separation | | | read-only, no creds |

- **Max:** 15/15 → S1 score becomes `68.9 + 15.0 = 83.9/90` → **93.2/100**,
  above the `adopt` threshold (80).
- **If Tasks 1–4 pass but Task 5 partial:** e.g. 12 + 2 = 14 → 82.9/90 → 92.1/100
  (still adopt).
- **If a family member cannot complete a read task unaided, or content is
  unreadable:** deduct and note the UX blocker — that is precisely the evidence
  S1 could not gather on its own, and the reason this dimension was held.

Record the raw observations (screenshots/notes) alongside the score; they are
the qualitative input the weighted number alone cannot capture.

## Re-running the automated surface check

The machine side is re-verifiable any time:

```bash
python3 scripts/v8_smoke_test.py            # direct HTTP viewer (default)
python3 scripts/v8_smoke_test.py https://192.168.88.9/family   # via Caddy edge
```

It asserts: login sets persona cookie, per-persona feeds show the right items,
granted docs open, the ungranted doc is denied, the audit trail records
`family.consume`, and the viewer source/process contains **zero** reference to
the SiYuan kernel (`:6806` / `/api/` / token).

## Safety / scope notes
- This surface is **V8 test scaffolding**, not the production PoC-3 facade
  (Week-9, real identity/RLS). Do not put real secrets or real family PII behind
  it; the lab fixtures are demo notes.
- The internal-CA cert warning is expected; a production rollout replaces it.
- The viewer binds `0.0.0.0:6900` on the lab host and is reached only through
  the Caddy `/family` route. Teardown: stop the viewer process and remove the
  `/family` block from the Caddyfile when the trial ends.
