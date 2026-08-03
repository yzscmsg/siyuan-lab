BEGIN;

CREATE TABLE planning.focus_area (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES core.household(id) ON DELETE CASCADE,
    owner_person_id uuid REFERENCES core.person(id) ON DELETE SET NULL,
    name text NOT NULL,
    horizon text NOT NULL CHECK (horizon IN ('current','quarter','year','multi_year')),
    priority smallint NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','completed','archived')),
    rationale text,
    success_definition text,
    review_cadence text NOT NULL DEFAULT 'monthly',
    valid_from date NOT NULL DEFAULT current_date,
    valid_to date,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

CREATE TABLE planning.project (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES core.household(id) ON DELETE CASCADE,
    focus_area_id uuid REFERENCES planning.focus_area(id) ON DELETE SET NULL,
    owner_person_id uuid REFERENCES core.person(id) ON DELETE SET NULL,
    name text NOT NULL,
    description text,
    status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','planned','active','blocked','on_hold','completed','cancelled')),
    priority smallint NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    start_date date,
    target_date date,
    completed_date date,
    estimated_effort_hours numeric(10,2) CHECK (estimated_effort_hours IS NULL OR estimated_effort_hours >= 0),
    capacity_class text CHECK (capacity_class IN ('small','medium','large','programme')),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (target_date IS NULL OR start_date IS NULL OR target_date >= start_date)
);

CREATE TABLE planning.project_member (
    project_id uuid NOT NULL REFERENCES planning.project(id) ON DELETE CASCADE,
    person_id uuid NOT NULL REFERENCES core.person(id) ON DELETE RESTRICT,
    responsibility text NOT NULL DEFAULT 'contributor',
    allocation_percent numeric(5,2) CHECK (allocation_percent BETWEEN 0 AND 100),
    PRIMARY KEY (project_id, person_id)
);

CREATE TABLE planning.milestone (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES planning.project(id) ON DELETE CASCADE,
    name text NOT NULL,
    due_date date,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','in_progress','achieved','missed','cancelled')),
    sequence_no integer NOT NULL DEFAULT 0,
    achieved_at timestamptz,
    UNIQUE (project_id, sequence_no)
);

CREATE TABLE planning.task (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid REFERENCES planning.project(id) ON DELETE CASCADE,
    milestone_id uuid REFERENCES planning.milestone(id) ON DELETE SET NULL,
    assignee_person_id uuid REFERENCES core.person(id) ON DELETE SET NULL,
    parent_task_id uuid REFERENCES planning.task(id) ON DELETE CASCADE,
    title text NOT NULL,
    description text,
    status text NOT NULL DEFAULT 'todo' CHECK (status IN ('inbox','todo','doing','waiting','blocked','done','cancelled')),
    priority smallint NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    due_at timestamptz,
    scheduled_start_at timestamptz,
    scheduled_end_at timestamptz,
    effort_minutes integer CHECK (effort_minutes IS NULL OR effort_minutes >= 0),
    recurrence_rule text,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (scheduled_end_at IS NULL OR scheduled_start_at IS NULL OR scheduled_end_at >= scheduled_start_at)
);

CREATE TABLE planning.dependency (
    predecessor_project_id uuid NOT NULL REFERENCES planning.project(id) ON DELETE CASCADE,
    successor_project_id uuid NOT NULL REFERENCES planning.project(id) ON DELETE CASCADE,
    dependency_type text NOT NULL DEFAULT 'finish_to_start' CHECK (dependency_type IN ('finish_to_start','start_to_start','finish_to_finish','start_to_finish')),
    lag_days integer NOT NULL DEFAULT 0,
    PRIMARY KEY (predecessor_project_id, successor_project_id),
    CHECK (predecessor_project_id <> successor_project_id)
);

CREATE TABLE planning.capacity_period (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id uuid NOT NULL REFERENCES core.person(id) ON DELETE CASCADE,
    period_start date NOT NULL,
    period_end date NOT NULL,
    available_minutes integer NOT NULL CHECK (available_minutes >= 0),
    reserved_minutes integer NOT NULL DEFAULT 0 CHECK (reserved_minutes >= 0),
    notes text,
    UNIQUE (person_id, period_start, period_end),
    CHECK (period_end >= period_start)
);

CREATE TABLE planning.review (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id uuid NOT NULL REFERENCES core.household(id) ON DELETE CASCADE,
    review_type text NOT NULL CHECK (review_type IN ('weekly','monthly','quarterly','annual','project')),
    period_start date NOT NULL,
    period_end date NOT NULL,
    summary text,
    decisions jsonb NOT NULL DEFAULT '[]'::jsonb,
    risks jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid REFERENCES core.person(id) ON DELETE SET NULL,
    CHECK (period_end >= period_start)
);

CREATE INDEX planning_task_assignee_due_idx ON planning.task(assignee_person_id, due_at) WHERE status NOT IN ('done','cancelled');
CREATE INDEX planning_project_owner_status_idx ON planning.project(owner_person_id, status);

COMMIT;
