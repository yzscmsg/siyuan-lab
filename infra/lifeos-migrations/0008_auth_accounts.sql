BEGIN;

-- =====================================================================
-- 0008: LifeOS family-consumption AUTH accounts (ADR-0006 / ADR-0009)
-- =====================================================================
-- This is the identity half of the production PoC-3 facade. Migration 0007
-- built the AUTHORIZATION boundary (per-item read grants, default-deny,
-- schema-enforced can_consume/published_to). This migration builds the
-- AUTHENTICATION boundary that 0007 implicitly assumed: a family member
-- logs in with a real credential and their person_id is FIXED by that login.
--
-- It REPLACES the V8 test surface's test-grade persona cookie, where anyone
-- who could reach the URL could assume any persona. Here, impersonation is
-- impossible by construction: the session cookie is HMAC-signed by the server
-- (FAMILY_FACADE_SECRET) and binds person_id; the facade never lets a client
-- choose who it is.
--
-- Design rules (mirror migration 0006/0007: the boundary is in the schema,
-- not trusted to the application layer):
--
--   1. An auth account is 1:1 with a core.person, and that person MUST be a
--      CURRENT member of an active household (trigger guard below). You cannot
--      have a login for a stranger or a departed member.
--   2. Passwords are PBKDF2-HMAC-SHA256 (100k iters) computed in the app
--      (stdlib hashlib); only the derived hash is stored. No plaintext, no
--      fast hash. Format: pbkdf2_sha256$<iters>$<salt_b64>$<hash_b64>.
--   3. Brute-force resistance: failed_attempts + locked_until. After
--      MAX_FAIL (app-side, default 5) consecutive failures the account is
--      locked for LOCK_SECONDS (default 900). The app enforces the lock; the
--      column is the durable record.
--   4. Revocation WITHOUT a session table: session_version is bumped on
--      disable / forced-logout. The signed session cookie carries the version
--      it was issued under; the facade rejects any cookie whose version no
--      longer matches the account's current version. This gives per-account
--      logout (rotation of FAMILY_FACADE_SECRET revokes everyone).
--   5. disabled_at supports owner-initiated account suspension.
--
-- This migration is SCHEMA ONLY. Account rows are provisioned by
-- scripts/seed_facade_accounts.py (lab) or the owner admin flow (prod) --
-- never by hard-coded plaintext in a migration.

CREATE TABLE IF NOT EXISTS core.auth_account (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id         uuid NOT NULL REFERENCES core.person(id) ON DELETE CASCADE,
    username          text NOT NULL UNIQUE,
    pw_hash           text NOT NULL,                 -- pbkdf2_sha256$iters$salt$hash
    failed_attempts   integer NOT NULL DEFAULT 0,
    locked_until      timestamptz,                   -- NULL = not locked
    last_login        timestamptz,
    last_fail         timestamptz,
    disabled_at       timestamptz,                   -- NULL = enabled
    session_version   integer NOT NULL DEFAULT 1,    -- bump to revoke live sessions
    created_at        timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT auth_account_username_len CHECK (char_length(username) >= 3)
);

CREATE INDEX IF NOT EXISTS auth_account_person_idx ON core.auth_account (person_id);

-- ---------------------------------------------------------------------
-- Guard: an account may only exist for a CURRENT member of an ACTIVE
-- household. Mirrors 0007's "constraint, not app-layer" philosophy.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.auth_account_member_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM core.household_member m
        JOIN core.household h ON h.id = m.household_id
        WHERE m.person_id = NEW.person_id
          AND (m.left_on IS NULL OR m.left_on > CURRENT_DATE)
          AND h.status = 'active'
    ) THEN
        RAISE EXCEPTION 'auth denied: person is not a current member of an active household';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS auth_account_member_guard_tg ON core.auth_account;
CREATE TRIGGER auth_account_member_guard_tg
    BEFORE INSERT OR UPDATE OF person_id ON core.auth_account
    FOR EACH ROW EXECUTE FUNCTION core.auth_account_member_guard();

COMMIT;
