BEGIN;

-- =====================================================================
-- 0009: LifeOS Ingest API authorization + safe-write outbox
--       (optional-tool contract; ADR-0010 / solution-landscape)
-- =====================================================================
-- The Ingest API (scripts/lifeos_api.py) is the DOCUMENTED path through
-- which optional tools (n8n, later Dify, the SiYuan export adapter) submit
-- evidence/artifacts to LifeOS. Per the solution-landscape integration
-- contract, tools MUST NOT hold a general-purpose DB account and MUST NOT
-- write authoritative core.* tables directly -- they submit through this
-- API, which is the single sanctioned write path.
--
-- This migration adds:
--   1. core.service_token -- scoped, hashed credentials for automation /
--      integration callers. Only the sha256 hash is stored; the raw token
--      lives only in the caller's secret store (printed once by
--      scripts/seed_service_token.py). Each token is SCOPED (e.g. 'ingest')
--      and GOVERNED by an owner (a current household owner); expiry and
--      revocation are supported.
--   2. core.ingest_outbox -- a transactional outbox so the API can announce
--      'document.registered' / 'document.withdrawn' to downstream consumers
--      (n8n, Dify) without the API itself performing those side effects.
--      Written in the same transaction as the core.document insert, giving
--      at-least-once, replayable delivery for the (currently Hold) n8n path.
--   3. core.ingest_request -- client-supplied idempotency key -> canonical
--      document_id, so a retried / delivered-twice call returns the SAME doc
--      and never creates a second canonical row.
--
-- Design rules (mirror 0006/0007/0008: the boundary is in the schema):
--   * A service token is owned ONLY by a current owner of the household it is
--     scoped to (or, if household_id IS NULL, a current owner of an active
--     household). Enforced by a trigger, not app code.
--   * Content-level idempotency stays in core.document UNIQUE(household_id,
--     sha256); ingest_request adds the caller's own key on top.
--
-- AUTHORITY NOTE: this migration is CANONICAL in family-lifeos. siyuan-lab
-- vendors a copy for the lab VM only; edit family-lifeos and re-vendor.

-- ---- 1. service_token -------------------------------------------------
CREATE TABLE IF NOT EXISTS core.service_token (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    label           text NOT NULL UNIQUE,
    token_hash      char(64) NOT NULL,            -- sha256 of the raw token
    scope           text[] NOT NULL DEFAULT '{ingest}',
    household_id    uuid REFERENCES core.household(id) ON DELETE CASCADE,
    owner_person_id uuid NOT NULL REFERENCES core.person(id) ON DELETE RESTRICT,
    created_by      uuid REFERENCES core.person(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_used_at    timestamptz,
    expires_at      timestamptz,
    revoked_at      timestamptz,
    CONSTRAINT service_token_scope_nonempty
        CHECK (array_length(scope, 1) > 0),
    CONSTRAINT service_token_revoked_after_created
        CHECK (revoked_at IS NULL OR revoked_at >= created_at),
    CONSTRAINT service_token_expires_after_created
        CHECK (expires_at IS NULL OR expires_at >= created_at)
);

CREATE INDEX IF NOT EXISTS service_token_hash_idx
    ON core.service_token (token_hash);
CREATE INDEX IF NOT EXISTS service_token_household_idx
    ON core.service_token (household_id);

CREATE OR REPLACE FUNCTION core.service_token_owner_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.household_id IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM core.household_member m
            WHERE m.household_id = NEW.household_id
              AND m.person_id = NEW.owner_person_id
              AND m.role = 'owner'
              AND (m.left_on IS NULL OR m.left_on > CURRENT_DATE)
        ) THEN
            RAISE EXCEPTION 'service_token denied: owner_person_id is not a current owner of the scoped household';
        END IF;
    ELSE
        IF NOT EXISTS (
            SELECT 1 FROM core.household_member m
            JOIN core.household h ON h.id = m.household_id
            WHERE m.person_id = NEW.owner_person_id
              AND m.role = 'owner'
              AND (m.left_on IS NULL OR m.left_on > CURRENT_DATE)
              AND h.status = 'active'
        ) THEN
            RAISE EXCEPTION 'service_token denied: owner_person_id is not a current owner of an active household';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS service_token_owner_guard_tg ON core.service_token;
CREATE TRIGGER service_token_owner_guard_tg
    BEFORE INSERT OR UPDATE OF owner_person_id, household_id ON core.service_token
    FOR EACH ROW EXECUTE FUNCTION core.service_token_owner_guard();

-- ---- 2. ingest_outbox (transactional, for downstream consumers) --------
CREATE TABLE IF NOT EXISTS core.ingest_outbox (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    topic        text NOT NULL,
    payload      jsonb NOT NULL,
    household_id uuid REFERENCES core.household(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz
);

CREATE INDEX IF NOT EXISTS ingest_outbox_pending_idx
    ON core.ingest_outbox (created_at) WHERE processed_at IS NULL;

-- ---- 3. ingest_request (idempotency key -> canonical document) ----------
CREATE TABLE IF NOT EXISTS core.ingest_request (
    idempotency_key text PRIMARY KEY,
    document_id     uuid NOT NULL REFERENCES core.document(id) ON DELETE CASCADE,
    household_id    uuid NOT NULL REFERENCES core.household(id) ON DELETE CASCADE,
    status          text NOT NULL DEFAULT 'registered'
                     CHECK (status IN ('registered', 'withdrawn', 'archived')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ingest_request_doc_idx
    ON core.ingest_request (document_id);

COMMIT;
