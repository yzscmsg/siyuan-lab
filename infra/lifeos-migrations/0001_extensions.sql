BEGIN;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS planning;
CREATE SCHEMA IF NOT EXISTS health;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE TABLE IF NOT EXISTS audit.schema_migration (
    version text PRIMARY KEY,
    filename text NOT NULL,
    sha256 char(64) NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);
COMMIT;
