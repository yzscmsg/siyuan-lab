# LifeOS family-consumption facade — real authentication (PoC-3)

- Status: **experimental; synthetic data only; not production-approved**
- Built: 2026-08-04
- Relates to: ADR-0006 (siyuan-lab) / ADR-0009 (family-lifeos), migration
  `0007` (publishing/authz boundary), migration `0008` (auth accounts),
  `scripts/family_facade.py`, roadmap §下一轮, supersedes the V8 test surface
  (`scripts/family_view.py`).

> **Safety notice:** ADR-0007 and `family-lifeos` ADR-0010 defer this custom
> facade. Do not expose it as a real-family-data service. V1 remains owner-only
> over VPN. The code is retained temporarily as PoC evidence and test material.

## Blocking findings from architecture review

The PoC must not be promoted without resolving and independently reviewing at
least the following:

1. The login path ends the redirect response before attempting to add the
   `Set-Cookie` header; correct session issuance is not established.
2. The session cookie uses `Path=/`, so it is sent beyond the `/family` surface
   on the shared origin.
3. The process listens on all interfaces and the documented direct HTTP route
   can bypass TLS and the intended edge boundary.
4. Document metadata is loaded before authorization denial, allowing title or
   existence information to cross the access boundary.
5. Database access shells into the PostgreSQL container rather than using a
   least-privilege application role and supported driver/API boundary.
6. Account lifecycle, person uniqueness, password work factor, lockout
   atomicity, security headers, path containment and session lifecycle require
   further design and testing.
7. Product migrations and identity logic belong in `family-lifeos`, not this
   lab repository.

Passing the existing smoke test does not close these findings because the test
oracle and implementation were produced together and several production
controls are outside its scope.

## Why this exists

The V8 family-view surface proved the **authorization** boundary end-to-end:
`core.can_consume(doc, person)` / `core.published_to(person)` from migration
`0007` enforce default-deny, owner-only publish, and per-item/per-person/per-role
read ACLs in SQL. But V8 authenticated with a **test-grade persona cookie** —
anyone who could reach the URL could pick any persona (`Owner`/`Adult`/`Member`).
That is fine for a controlled family trial; it is explicitly **not production
auth**.

This facade keeps the proven `0007` boundary and replaces **only the identity
layer**: a family member now signs in with a real username/password bound to a
`core.auth_account` (migration `0008`), and their `person_id` is fixed by a
server-signed session. Impersonation becomes impossible by construction.

## Components

| File | Role |
| --- | --- |
| `infra/lifeos-migrations/0008_auth_accounts.sql` | `core.auth_account` (person FK, username unique, PBKDF2 `pw_hash`, `failed_attempts`, `locked_until`, `disabled_at`, `session_version`) + trigger guard that the person is a current member of an active household. Mirrored to `family-lifeos/db/migrations/0008_auth_accounts.sql`. |
| `scripts/family_facade.py` | The facade: real `/login`, signed session, RLS via `can_consume`/`published_to`, audit, zero SiYuan reference. stdlib only. |
| `scripts/seed_facade_accounts.py` | LAB-ONLY idempotent account provisioning (PBKDF2 hashes). Not production account creation. |
| `scripts/facade_smoke_test.py` | Real-auth smoke test: login → per-persona feeds → grants/denials → **forged-session rejection** → **privilege-escalation denial** → audit → zero SiYuan. |
| `host/run_family_facade.sh` | Launcher on `:6902`; fails closed if `FAMILY_FACADE_SECRET` is unset. |
| `infra/compose/Caddyfile` | `/family` now reverse-proxies to `172.18.0.1:6902` (the facade); the V8 viewer `:6901` is retired as the edge target. |

## Security model

- **Passwords**: PBKDF2-HMAC-SHA256, 100k iterations, 16-byte random salt,
  computed in stdlib `hashlib`. Only the derived `pbkdf2_sha256$iters$salt$hash`
  is stored. Verification uses constant-time `hmac.compare_digest`.
- **Sessions**: stateless HMAC-SHA256-signed cookie (`sid = person_id.version.
  expiry_unix`).`signature`). Tampering, expiry, or malformed tokens are
  rejected (`verify_session` returns `None` → 303 to `/login`).
- **Per-account revocation without a session table**: bumping
  `auth_account.session_version` invalidates every prior cookie for that account
  (the cookie carries the version it was issued under). Rotating
  `FAMILY_FACADE_SECRET` revokes all sessions at once.
- **Brute-force lockout**: `failed_attempts` + `locked_until`; after
  `FAMILY_FACADE_MAX_FAIL` (default 5) consecutive failures the account locks
  for `FAMILY_FACADE_LOCK_SECONDS` (default 900). Failures do not distinguish
  "no such user" from "bad password" to avoid enumeration.
- **Cookie flags**: `HttpOnly`; `SameSite=Strict` (mitigates cross-site use);
  `Secure` when `FAMILY_FACADE_SECURE_COOKIE=1` (behind Caddy TLS in prod).
- **Fail-closed**: the facade refuses to start if `FAMILY_FACADE_SECRET` is
  unset — no signing secret means no trustworthy sessions.
- **Audit**: every login (success/failure, with reason) and every consume
  attempt is recorded in `audit.event` (`surface = 'prod-family-facade'`).
- **Zero SiYuan credentials**: the facade talks ONLY to `lifeos-pg` (via the
  `docker exec psql` transport, trust auth inside the container — no credential
  in this process) and never references the SiYuan kernel (`:6806`), the siyuan
  container, `/api/*`, or the API token. The `facade_smoke_test.py` source scan
  asserts this.

## Authorization is unchanged (reuse of migration 0007)

The facade never re-implements the access rule. It calls the same SQL functions
the V8 viewer did, but with the **authenticated** `person_id`:

- Feed: `core.published_to(person_id)`
- Single doc: `core.can_consume(doc_id, person_id)`

Default-deny, owner-only publish, revoke/expiry handling, and doc-status
gating all live in `0007` and are exercised identically. The only behavioral
change vs V8 is that `person_id` can no longer be chosen by the client.

## Deployment

```
# on the VM, with a real secret:
export FAMILY_FACADE_SECRET="$(openssl rand -hex 32)"
export FAMILY_FACADE_SECURE_COOKIE=1
python3 scripts/seed_facade_accounts.py     # LAB accounts (owner/adult/member)
./host/run_family_facade.sh                  # listens on :6902
# Caddy /family already points at :6902; reload caddy.
```

The family reaches the facade at `https://<host>/family` (Caddy terminates TLS
with its internal CA). Phones that sent SNI get the cert; automation clients
without SNI can hit `http://<host>:6902` directly (same process).

## Testing

`python3 scripts/facade_smoke_test.py` (on the VM) performs real `/login`
calls and asserts:

1. Anonymous requests redirect to `/login` (no anonymous access).
2. Owner feed = 3 household-wide items; adult = 4 (+ person-scoped n07);
   member = 4 (+ role-scoped n08).
3. Member is **denied** n07 (adult-personal) → default-deny page.
4. Nobody can open n09 (ungranted) → default-deny page.
5. A **forged/tampered** session cookie is rejected (redirect to `/login`).
6. A bad password yields no session.
7. Audit events (`family.login` + `family.consume`) are present.
8. The facade source contains zero SiYuan kernel/token references.

This is an identity-layer experiment corresponding to `v8_smoke_test.py`: it
adds username/password and impersonation-resistance checks but is not a
production security certification.

## Hardening notes (production TODO, not done here)

- **DB transport**: swap the single `_psql()` function for a real `psycopg`
  connection using a **least-privilege read role** (SELECT on `core.document`,
  `core.publish_grant`, `core.person`, `core.household_member`; EXECUTE on the
  functions; no superuser). The rest of the security model is unchanged.
- **Account lifecycle**: production account creation belongs to an owner admin
  flow / LifeOS admin console, not `seed_facade_accounts.py` (which is lab-only).
- **CSRF**: the session cookie is `SameSite=Strict`, which mitigates cross-site
  use of the login form; add a double-submit CSRF token if a state-changing
  POST surface is added beyond login/logout.
- **Edge rate-limiting**: the app enforces per-account lockout; add an edge
  throttle (Caddy/`fail2ban`) for distributed attempts.
- **MFA**: optional per-account TOTP for owner/admin accounts — out of scope
  for the initial family consumption surface.
