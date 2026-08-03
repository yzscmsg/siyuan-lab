BEGIN;

CREATE TABLE core.household (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    default_timezone text NOT NULL DEFAULT 'Asia/Singapore',
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE core.person (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_name text NOT NULL,
    preferred_name text,
    date_of_birth date,
    timezone text NOT NULL DEFAULT 'Asia/Singapore',
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive','deceased')),
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE core.household_member (
    household_id uuid NOT NULL REFERENCES core.household(id) ON DELETE CASCADE,
    person_id uuid NOT NULL REFERENCES core.person(id) ON DELETE RESTRICT,
    role text NOT NULL DEFAULT 'member',
    joined_on date,
    left_on date,
    PRIMARY KEY (household_id, person_id),
    CHECK (left_on IS NULL OR joined_on IS NULL OR left_on >= joined_on)
);

CREATE TABLE core.contact_point (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id uuid NOT NULL REFERENCES core.person(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('email','phone','address','messaging','other')),
    label text,
    value text NOT NULL,
    is_primary boolean NOT NULL DEFAULT false,
    valid_from date,
    valid_to date,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX contact_one_primary_per_kind
ON core.contact_point(person_id, kind) WHERE is_primary;

CREATE TABLE core.tag (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES core.household(id) ON DELETE CASCADE,
    name text NOT NULL,
    color_token text,
    UNIQUE (household_id, name)
);

CREATE TABLE core.document (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES core.household(id) ON DELETE CASCADE,
    subject_person_id uuid REFERENCES core.person(id) ON DELETE SET NULL,
    category text NOT NULL,
    title text NOT NULL,
    storage_uri text NOT NULL,
    media_type text,
    byte_size bigint CHECK (byte_size IS NULL OR byte_size >= 0),
    sha256 char(64) NOT NULL,
    source text,
    document_date date,
    retention_class text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid REFERENCES core.person(id) ON DELETE SET NULL,
    UNIQUE (household_id, sha256)
);

CREATE TABLE core.external_identifier (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id uuid REFERENCES core.person(id) ON DELETE CASCADE,
    system_name text NOT NULL,
    identifier_type text NOT NULL,
    identifier_hash text NOT NULL,
    last4 text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (system_name, identifier_type, identifier_hash)
);

CREATE TABLE audit.event (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    actor_person_id uuid REFERENCES core.person(id) ON DELETE SET NULL,
    actor_type text NOT NULL DEFAULT 'user',
    action text NOT NULL,
    object_type text NOT NULL,
    object_id uuid,
    household_id uuid REFERENCES core.household(id) ON DELETE SET NULL,
    request_id uuid,
    source_ip inet,
    outcome text NOT NULL DEFAULT 'success',
    details jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX audit_event_object_idx ON audit.event(object_type, object_id, occurred_at DESC);
CREATE INDEX audit_event_household_idx ON audit.event(household_id, occurred_at DESC);

COMMIT;
