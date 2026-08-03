BEGIN;

CREATE TABLE health.profile (
    person_id uuid PRIMARY KEY REFERENCES core.person(id) ON DELETE CASCADE,
    blood_type text,
    biological_sex_at_birth text,
    preferred_language text,
    emergency_notes text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE health.provider (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    provider_type text,
    organisation text,
    phone text,
    email text,
    address text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE health.encounter (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id uuid NOT NULL REFERENCES core.person(id) ON DELETE CASCADE,
    provider_id uuid REFERENCES health.provider(id) ON DELETE SET NULL,
    encounter_type text NOT NULL,
    started_at timestamptz NOT NULL,
    ended_at timestamptz,
    location text,
    reason text,
    summary text,
    source_document_id uuid REFERENCES core.document(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE TABLE health.condition (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id uuid NOT NULL REFERENCES core.person(id) ON DELETE CASCADE,
    name text NOT NULL,
    code_system text,
    code text,
    clinical_status text NOT NULL DEFAULT 'active' CHECK (clinical_status IN ('active','recurrence','relapse','inactive','remission','resolved','unknown')),
    verification_status text NOT NULL DEFAULT 'unconfirmed' CHECK (verification_status IN ('unconfirmed','provisional','differential','confirmed','refuted','entered_in_error')),
    onset_date date,
    resolved_date date,
    severity text,
    notes text,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    CHECK (resolved_date IS NULL OR onset_date IS NULL OR resolved_date >= onset_date)
);

CREATE TABLE health.allergy (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id uuid NOT NULL REFERENCES core.person(id) ON DELETE CASCADE,
    substance text NOT NULL,
    reaction text,
    severity text,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive','resolved','entered_in_error')),
    first_observed date,
    notes text,
    recorded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE health.medication (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id uuid NOT NULL REFERENCES core.person(id) ON DELETE CASCADE,
    name text NOT NULL,
    dose text,
    route text,
    frequency text,
    indication text,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('planned','active','on_hold','completed','stopped','unknown')),
    start_date date,
    end_date date,
    prescriber_provider_id uuid REFERENCES health.provider(id) ON DELETE SET NULL,
    notes text,
    CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);

CREATE TABLE health.observation (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id uuid NOT NULL REFERENCES core.person(id) ON DELETE CASCADE,
    encounter_id uuid REFERENCES health.encounter(id) ON DELETE SET NULL,
    observed_at timestamptz NOT NULL,
    category text NOT NULL,
    name text NOT NULL,
    code_system text,
    code text,
    value_numeric numeric,
    value_text text,
    unit text,
    reference_low numeric,
    reference_high numeric,
    interpretation text,
    source_document_id uuid REFERENCES core.document(id) ON DELETE SET NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (value_numeric IS NOT NULL OR value_text IS NOT NULL)
);

CREATE TABLE health.procedure (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id uuid NOT NULL REFERENCES core.person(id) ON DELETE CASCADE,
    encounter_id uuid REFERENCES health.encounter(id) ON DELETE SET NULL,
    provider_id uuid REFERENCES health.provider(id) ON DELETE SET NULL,
    name text NOT NULL,
    performed_at timestamptz,
    outcome text,
    notes text,
    source_document_id uuid REFERENCES core.document(id) ON DELETE SET NULL
);

CREATE TABLE health.immunisation (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id uuid NOT NULL REFERENCES core.person(id) ON DELETE CASCADE,
    vaccine text NOT NULL,
    administered_at timestamptz,
    dose_number text,
    lot_number text,
    provider_id uuid REFERENCES health.provider(id) ON DELETE SET NULL,
    status text NOT NULL DEFAULT 'completed',
    source_document_id uuid REFERENCES core.document(id) ON DELETE SET NULL
);

CREATE TABLE health.care_plan (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id uuid NOT NULL REFERENCES core.person(id) ON DELETE CASCADE,
    title text NOT NULL,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','on_hold','completed','cancelled')),
    start_date date,
    end_date date,
    goals jsonb NOT NULL DEFAULT '[]'::jsonb,
    instructions text,
    owner_provider_id uuid REFERENCES health.provider(id) ON DELETE SET NULL,
    CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);

CREATE TABLE health.consent (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id uuid NOT NULL REFERENCES core.person(id) ON DELETE CASCADE,
    granted_to_person_id uuid REFERENCES core.person(id) ON DELETE CASCADE,
    scope text NOT NULL,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked','expired')),
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz,
    revoked_at timestamptz,
    notes text,
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

CREATE INDEX health_encounter_person_time_idx ON health.encounter(person_id, started_at DESC);
CREATE INDEX health_observation_person_time_idx ON health.observation(person_id, observed_at DESC);
CREATE INDEX health_condition_person_status_idx ON health.condition(person_id, clinical_status);

COMMIT;
