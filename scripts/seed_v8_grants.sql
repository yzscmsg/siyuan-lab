-- seed_v8_grants.sql -- V8 mobile-test publish scenario (idempotent).
--
-- Clears any leftover publish_grant rows, then lays down a clean, documented
-- scenario for the lab household so the family-view test surface has real
-- content to consume. This is TEST DATA for V8, not production publishing.
--
-- Scenario (all grants owned by the household owner, per the 0007 guard):
--   * household-wide on c01, c02, n06  -> every family member sees these
--   * person-scoped: Adult Lab  -> n07
--   * role-scoped:   role member -> n08  (Member Lab sees via role)
--   * n09 is intentionally LEFT UNGRANTED -> demonstrates default-deny (403)
--
-- Re-run any time; it resets to this known state.

BEGIN;

-- wipe previous test grants for a clean slate
DELETE FROM core.publish_grant;

-- resolve the lab household + its owner (guard requires granted_by = owner)
DO $$
DECLARE
    v_hh   uuid;
    v_owner uuid;
    v_adult uuid;
    v_member uuid;
    v_c01 uuid; v_c02 uuid; v_n06 uuid; v_n07 uuid; v_n08 uuid;
BEGIN
    SELECT id INTO v_hh FROM core.household WHERE name = 's1-lab-household' LIMIT 1;
    IF v_hh IS NULL THEN
        SELECT DISTINCT household_id INTO v_hh FROM core.document LIMIT 1;
    END IF;
    SELECT person_id INTO v_owner
      FROM core.household_member WHERE household_id = v_hh AND role = 'owner' LIMIT 1;
    SELECT p.id INTO v_adult
      FROM core.person p JOIN core.household_member m ON m.person_id = p.id
      WHERE m.household_id = v_hh AND m.role = 'adult' LIMIT 1;
    SELECT p.id INTO v_member
      FROM core.person p JOIN core.household_member m ON m.person_id = p.id
      WHERE m.household_id = v_hh AND m.role = 'member' LIMIT 1;

    SELECT id INTO v_c01 FROM core.document WHERE title='c01' AND household_id=v_hh LIMIT 1;
    SELECT id INTO v_c02 FROM core.document WHERE title='c02' AND household_id=v_hh LIMIT 1;
    SELECT id INTO v_n06 FROM core.document WHERE title='n06' AND household_id=v_hh LIMIT 1;
    SELECT id INTO v_n07 FROM core.document WHERE title='n07' AND household_id=v_hh LIMIT 1;
    SELECT id INTO v_n08 FROM core.document WHERE title='n08' AND household_id=v_hh LIMIT 1;

    -- household-wide (every member sees these)
    INSERT INTO core.publish_grant (document_id, household_id, grantee_household, access, granted_by, reason)
      SELECT d, v_hh, true, 'read', v_owner, 'v8: household shared'
      FROM unnest(array[v_c01, v_c02, v_n06]) AS t(d) WHERE d IS NOT NULL;

    -- person-scoped: Adult Lab -> n07
    IF v_adult IS NOT NULL AND v_n07 IS NOT NULL THEN
      INSERT INTO core.publish_grant (document_id, household_id, grantee_person_id, access, granted_by, reason)
        VALUES (v_n07, v_hh, v_adult, 'read', v_owner, 'v8: adult personal');
    END IF;

    -- role-scoped: member role -> n08
    IF v_n08 IS NOT NULL THEN
      INSERT INTO core.publish_grant (document_id, household_id, grantee_role, access, granted_by, reason)
        VALUES (v_n08, v_hh, 'member', 'read', v_owner, 'v8: member role');
    END IF;
END $$;

COMMIT;
