BEGIN;

-- =====================================================================
-- 0006: core.document lifecycle + integrity contract (week-4 step 3/4)
-- =====================================================================
-- Closes S1 defects D3 and D4:
--   D3  core.document had no status/version/supersedes column, so withdrawal
--       (retraction) was only expressible in metadata jsonb that no constraint
--       could enforce. Week-4 step 3 lists status as required.
--   D4  core.document accepted any media_type and did not validate storage_uri
--       (path traversal / raw-IP embedding possible).
--
-- Contract tests in scripts/lifeos_handoff.py (C4/C5) and
-- scripts/retraction_test.py (L4) assert these constraints; both flip from
-- "gap to be enforced by the API" to "enforced by schema" once this is applied.

-- ---- D3: lifecycle columns -------------------------------------------
ALTER TABLE core.document
    ADD COLUMN status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'superseded', 'withdrawn', 'archived')),
    ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    ADD COLUMN supersedes uuid REFERENCES core.document(id) ON DELETE SET NULL;

-- partial index so retraction sweeps and "what changed" queries are cheap
CREATE INDEX document_status_idx ON core.document(status)
    WHERE status <> 'active';

-- a document cannot supersede itself
ALTER TABLE core.document
    ADD CONSTRAINT document_no_self_supersede CHECK (supersedes <> id);

-- ---- D4a: media_type allowlist ----------------------------------------
-- Keep in sync with scripts/lifeos_handoff.py MEDIA. New types need a new
-- migration (checksummed), which is deliberate: media types are a contract.
ALTER TABLE core.document
    ADD CONSTRAINT document_media_type_check
    CHECK (media_type IS NULL OR media_type IN (
        'text/markdown',
        'text/plain',
        'text/csv',
        'application/json',
        'application/pdf',
        'image/png',
        'image/jpeg',
        'image/gif',
        'image/svg+xml',
        'application/octet-stream'
    ));

-- ---- D4b: storage_uri shape -------------------------------------------
-- Must be a scheme:// URI, must not contain path-traversal (..) segments,
-- and must not embed a raw IPv4 authority (leaks topology into canonical data).
ALTER TABLE core.document
    ADD CONSTRAINT document_storage_uri_valid
    CHECK (storage_uri ~ '^[a-z][a-z0-9+.\-]*://'
           AND storage_uri NOT LIKE '%..%'
           AND storage_uri !~ '://[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}');

COMMIT;
