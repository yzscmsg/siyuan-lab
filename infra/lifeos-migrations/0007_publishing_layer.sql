BEGIN;

-- =====================================================================
-- 0007: LifeOS granular publishing layer (ADR-0006 / ADR-0009)
-- =====================================================================
-- Closes the "family consumption boundary" open item in the S1 roadmap
-- (family-lifeos roadmap §下一轮). Under the single-owner model the editable
-- SiYuan workspace is a PRIVATE admin console; family members are CONSUMERS
-- and must never hold a SiYuan credential. The family permission boundary
-- therefore lives in LifeOS, expressed here as a per-item / per-person /
-- per-role / per-household READ grant with DEFAULT-DENY semantics.
--
-- Design rules (carry the migration-0006 philosophy: the security boundary is
-- enforced by the schema, not trusted to the application layer):
--
--   1. DEFAULT DENY. A core.document with no row in core.publish_grant is
--      private to the owner console — only the owner can see it.
--   2. A family member may consume a document iff:
--        (a) the document is active (status = 'active'),
--        (b) their household is active,
--        (c) they are a CURRENT member of that household, and
--        (d) a live grant (not revoked, not expired) covers them, where
--            coverage = person scope | role scope | whole-household scope.
--      No scope silently overrides another; reducing access requires an
--      explicit revoke or expiry, never an implicit shadow.
--   3. PUBLISH IS OWNER-ONLY, enforced by a trigger (not just app code):
--      granted_by must be a current household owner, and a person-scoped grant
--      must target a current member of the same household. This is the
--      concrete DB-side expression of "family consumption via LifeOS
--      granular publishing; the editable SiYuan workspace is a private
--      administrator console."
--   4. Resolution lives in SQL (core.can_consume / core.published_to) so the
--      contract cannot drift between callers.

CREATE TABLE core.publish_grant (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id        uuid NOT NULL REFERENCES core.document(id) ON DELETE CASCADE,
    household_id       uuid NOT NULL REFERENCES core.household(id) ON DELETE CASCADE,

    -- exactly ONE of these three scopes is set (enforced by CHECK below)
    grantee_person_id  uuid REFERENCES core.person(id) ON DELETE CASCADE,
    grantee_role       text CHECK (grantee_role IN ('owner', 'adult', 'member')),
    grantee_household  boolean NOT NULL DEFAULT false,

    access             text NOT NULL DEFAULT 'read'
                          CHECK (access IN ('read', 'readwrite', 'admin')),
    granted_by         uuid REFERENCES core.person(id) ON DELETE SET NULL,
    granted_at         timestamptz NOT NULL DEFAULT now(),
    expires_at         timestamptz,                 -- NULL = no expiry
    revoked_at         timestamptz,                 -- NULL = not revoked
    reason             text,
    metadata           jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at         timestamptz NOT NULL DEFAULT now(),

    -- exactly one scope selected; cannot grant to all-three or none
    CONSTRAINT publish_grant_one_scope
        CHECK ((
            (grantee_person_id IS NOT NULL)::int +
            (grantee_role IS NOT NULL)::int +
            (grantee_household)::int
        ) = 1),
    -- a revoke must not predate the grant
    CONSTRAINT publish_grant_revoked_after_granted
        CHECK (revoked_at IS NULL OR revoked_at >= granted_at)
);

-- Idempotent upsert-by-scope: only one grant per (document, scope), so the
-- publish facade can re-publish without creating duplicate rows.
CREATE UNIQUE INDEX publish_grant_uniq_person
    ON core.publish_grant (document_id, grantee_person_id)
    WHERE grantee_person_id IS NOT NULL;
CREATE UNIQUE INDEX publish_grant_uniq_role
    ON core.publish_grant (document_id, grantee_role)
    WHERE grantee_role IS NOT NULL;
CREATE UNIQUE INDEX publish_grant_uniq_household
    ON core.publish_grant (document_id, household_id)
    WHERE grantee_household;

CREATE INDEX publish_grant_document_idx ON core.publish_grant (document_id);

-- ---------------------------------------------------------------------
-- Resolution helpers (STABLE so the planner can inline; the boundary lives
-- here, not in whichever caller happens to remember the rules).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.grant_is_live(g core.publish_grant)
RETURNS boolean
LANGUAGE sql IMMUTABLE
AS $$
    SELECT g.revoked_at IS NULL
       AND (g.expires_at IS NULL OR g.expires_at > now())
$$;

-- Current membership predicate: must be a member who has not left the household.
CREATE OR REPLACE FUNCTION core.is_current_member(hid uuid, pid uuid)
RETURNS boolean
LANGUAGE sql STABLE
AS $$
    SELECT EXISTS (
        SELECT 1 FROM core.household_member m
        WHERE m.household_id = hid
          AND m.person_id = pid
          AND (m.left_on IS NULL OR m.left_on > CURRENT_DATE)
    )
$$;

-- Can person `p_person` consume document `p_doc`? Default-deny: false unless
-- all four conditions hold. Parameter names are deliberately prefixed (p_doc /
-- p_person) so they can NEVER be shadowed by a table column named doc_id /
-- person_id inside the query -- the original names collided with columns in
-- the role-matching subquery and silently broke person+role scope matching.
CREATE OR REPLACE FUNCTION core.can_consume(p_doc uuid, p_person uuid)
RETURNS boolean
LANGUAGE sql STABLE
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM core.publish_grant g
        JOIN core.document d  ON d.id = g.document_id
        JOIN core.household h ON h.id = g.household_id
        WHERE g.document_id = p_doc
          AND d.status = 'active'
          AND h.status = 'active'
          AND core.grant_is_live(g)
          AND core.is_current_member(g.household_id, p_person)
          AND (
                g.grantee_person_id = p_person
             OR g.grantee_role = (
                    SELECT m.role FROM core.household_member m
                    WHERE m.household_id = g.household_id AND m.person_id = p_person
                    LIMIT 1)
             OR g.grantee_household
          )
    );
$$;

-- The feed a person may consume: active docs with a live matching grant.
-- Delegates to core.can_consume so the resolution rule has a SINGLE source of
-- truth (no duplicated, drift-prone predicate).
CREATE OR REPLACE FUNCTION core.published_to(p_person uuid)
RETURNS TABLE (document_id uuid, title text, category text, access text)
LANGUAGE sql STABLE
AS $$
    SELECT d.id, d.title, d.category, g.access
    FROM core.publish_grant g
    JOIN core.document d  ON d.id = g.document_id
    WHERE core.grant_is_live(g)
      AND core.can_consume(d.id, p_person)
    GROUP BY d.id, d.title, d.category, g.access
$$;

-- ---------------------------------------------------------------------
-- Owner-only publish guard. Enforced at the database level so the boundary
-- cannot be bypassed by a careless caller (mirrors migration 0006's
-- "constraint, not app-layer" approach).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.publish_grant_owner_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- the actor issuing the grant must be a CURRENT owner of the household
    IF NOT EXISTS (
        SELECT 1 FROM core.household_member m
        WHERE m.household_id = NEW.household_id
          AND m.person_id = NEW.granted_by
          AND m.role = 'owner'
          AND (m.left_on IS NULL OR m.left_on > CURRENT_DATE)
    ) THEN
        RAISE EXCEPTION 'publish denied: granted_by is not a current owner of the household';
    END IF;
    -- a person-scoped grant must target a CURRENT member of the same household
    IF NEW.grantee_person_id IS NOT NULL AND NOT core.is_current_member(
            NEW.household_id, NEW.grantee_person_id) THEN
        RAISE EXCEPTION 'publish denied: grantee is not a current member of the household';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER publish_grant_owner_guard_tg
    BEFORE INSERT OR UPDATE ON core.publish_grant
    FOR EACH ROW EXECUTE FUNCTION core.publish_grant_owner_guard();

COMMIT;
