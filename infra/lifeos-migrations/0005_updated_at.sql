BEGIN;

CREATE OR REPLACE FUNCTION core.set_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER household_updated_at BEFORE UPDATE ON core.household
FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER person_updated_at BEFORE UPDATE ON core.person
FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER focus_area_updated_at BEFORE UPDATE ON planning.focus_area
FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER project_updated_at BEFORE UPDATE ON planning.project
FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER task_updated_at BEFORE UPDATE ON planning.task
FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TABLE audit.restore_drill (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    backup_reference text NOT NULL,
    result text NOT NULL CHECK (result IN ('running','passed','failed')),
    verified_by uuid REFERENCES core.person(id) ON DELETE SET NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb
);

COMMIT;
