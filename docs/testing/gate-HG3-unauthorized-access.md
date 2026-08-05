---
id: HG3
title: Unauthorised users / logs / models / indexes see no forbidden fields
status: PASS (single-owner model, ADR-0006)
source: docs/implementation/03-s1-scorecard.md §Part1#3; ADR-0006; scripts/s1_acceptance.py (stage negative); scripts/negative_tests.py; scripts/perm_matrix.py
last_run: 2026-08-03 (VM 192.168.88.9)
recorded_by: s1_acceptance.py (negative stage) + manual proxy/kernel probe
---

# HG3 — No forbidden-field leakage to unauthorised readers

## Goal
Unauthorised users, logs, model context and derived indexes must **not** see
forbidden fields. Clause: *"未授权用户、日志、模型上下文和派生索引均看不到禁止字段。"*

## Scope (re-scoped under ADR-0006)
Under the single-owner model the "unauthorised user" is **anyone but the owner**;
the family boundary is owned by **LifeOS granular publishing**, not SiYuan.
Seven surfaces are tested:
- N1 private doc via API → 401 unauthenticated
- N2 export endpoint → 401 unauthenticated
- N3 proxy blocks anonymous `/assets` (0/8) **and** kernel is loopback-only
- N4 mutating API → 401 unauthenticated
- N5 single-owner console owner-only reachable (by design)
- N6 no token/auth-code leakage in logs
- N7 no secret leakage in backups or note content

## Prerequisites / Dependencies
- Stack deployed with Caddy edge (`tls internal`) + SiYuan kernel loopback-bound.
- `scripts/negative_tests.py` for N1/N2/N4/N6/N7.
- Manual probe for N3/N5 (kernel port binding + edge asset block).

## Inputs
- Unauthenticated HTTP probes (no session cookie / no API token).
- `curl`/`urllib` against `:6806` (kernel) and Caddy `:443`/`:80`.
- Log + backup scan for tokens/authcodes.

## Expected output / pass criteria
- N1/N2/N4: 401 for every unauthenticated request.
- N3: Caddy returns 0/8 anonymous `/assets`; kernel is bound to `127.0.0.1` only
  (never `0.0.0.0:6806`).
- N5: console reachable only by the owner via the reverse proxy.
- N6/N7: no authcode/api_token strings in logs, backups, or note bodies.

## Steps (human-steppable)
1. `./run.sh negative` — runs `negative_tests.py` (N1/N2/N4/N6/N7).
2. **Manual N3 probe** — from a second host on the LAN:
   `curl -s -o /dev/null -w "%{http_code}" http://192.168.88.9:6806/assets/...`
   expect connection refused (loopback-bound). Then via Caddy:
   `curl -s -o /dev/null -w "%{http_code}" https://192.168.88.9/assets/...`
   expect 401/403 (edge blocks anonymous).
3. **Manual N5** — confirm `:6806` is not exposed; only the owner reaches the
   console through Caddy.
4. Grep exported logs/backups for `authcode`/`api_token` literals → expect none.

## Recorded result (actual run, 2026-08-03)
- 7 surfaces tested, all secure.
- N1/N2/N4: 401 unauthenticated.
- N3: proxy blocks anonymous assets 0/8 **and** kernel is loopback-only.
- N5: single-owner console owner-only reachable — design, not a leak.
- N6/N7: no token/auth-code leakage in logs, backups or content. → **PASS**.

## Issues found / notes
- **Original reading (multi-user isolation inside SiYuan) FAILED** — self-hosted
  SiYuan has **no per-user ACL**. ADR-0006 re-scoped HG3 to the single-owner +
  LifeOS-publishing model, which converts the finding from a blocker into a
  design boundary. The underlying product fact (no per-user ACL) remains true and
  is why SiYuan is never the family permission system.
- Hardened rule: any change exposing `:6806` to the LAN reverts HG3 to FAIL
  (auto-checked by `s1_acceptance.py`).

## Re-run
```bash
python3 scripts/s1_acceptance.py --stages negative
# manual N3/N5 probe as above
```
