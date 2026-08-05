---
id: V8
title: Family viewing UX on a real phone (5 tasks)
status: PASS (15/15)
source: docs/implementation/05-v8-mobile-test.md; scripts/v8_smoke_test.py (pre-human automated, 11/11); seed_v8_grants.sql
last_run: 2026-08-04 (human, real-family phone over LAN)
recorded_by: human observation (owner) + automated smoke
---

# V8 — Family viewing UX (human mobile test)

## Goal
Confirm the **family consumption surface** actually works for a non-technical
family member on a real phone: correct per-persona feeds, contents render,
navigation is usable. This is the feature/UX dimension that, once passed,
flips the S1 verdict from `trial` to `adopt`.

## Scope
- Surface: `family_view.py` viewer reached via Caddy `/family` (test-grade
  persona cookie — **not** production auth; see ADR-0007 facade deferral).
- Per-persona feed matrix from `seed_v8_grants.sql`:
  - household-wide: c01 / c02 / n06
  - adult personal: n07
  - member-role: n08
  - n09: **un granted → default-deny (shown to no one)**

## Prerequisites / Dependencies
- Stack deployed; Caddy `/family` → viewer `:6901` (legacy) / `:6902` (facade).
- `seed_v8_grants.sql` applied; `lifeos-pg` up.
- A real phone on the LAN + the three test personas (Owner / Adult / Member).

## Inputs
- Three persona cookies / logins (Owner, Adult, Member Lab).
- Phone browser hitting `https://<host>/family`.
- 5 tasks: open each persona; verify feed contents; navigate between docs.

## Expected output / pass criteria
- **Owner** sees: c01, c02, n06.
- **Adult** sees: c01, c02, n06, **n07**.
- **Member** sees: c01, c02, n06, **n08**.
- **n09 shown to no one** (default-deny holds on-device).
- Contents render; navigation works unaided.
- 5/5 tasks → **15/15**.

## Steps (human-steppable)
1. On the phone, open `https://<host>/family` as **Owner**; record visible docs
   → expect c01/c02/n06.
2. Switch to **Adult**; expect c01/c02/n06/**n07**.
3. Switch to **Member**; expect c01/c02/n06/**n08**.
4. Confirm **n09** is absent in all three personas.
5. Open a doc in each persona; confirm rendering + back-navigation works.
6. (Optional automated pre-check) `python3 scripts/v8_smoke_test.py` → 11/11.

## Recorded result (actual run, 2026-08-04)
Human phone run, observed matrix exactly matched the seed:
- Owner → c01/n06/c02
- Member → n08/c01/n06/c02
- Adult → c07(=n07)/n06/c02/n07
- n09 absent everywhere; contents render; navigation OK.
→ **5/5 tasks → 15/15 → S1 83.9/90 ADOPT**.

## Issues found / notes
- The persona cookie is **test-grade** — anyone reaching the URL could assume any
  persona. Production identity is the deferred facade (ADR-0007), not this
  surface. The V8 PASS validates the *viewing experience*, not the auth boundary.
- ADR-0007 explicitly defers the custom facade; the family pilot stays gated
  behind G2 (qualified NAS) in the wider roadmap.

## Re-run
```bash
# automated pre-check (VM):
python3 scripts/v8_smoke_test.py
# human phone run: follow Steps 1-5 above
```
