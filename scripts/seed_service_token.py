#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seed_service_token.py -- LAB ONLY: provision a scoped LifeOS Ingest API token.

Creates a row in core.service_token (migration 0009) for an automation/tool to
call scripts/lifeos_api.py. The raw token is printed ONCE and never stored; only
its sha256 hash lives in the DB. This is the documented way a tool obtains a
credential -- there is no UI and no hardcoded plaintext in any migration.

Usage (on the VM, against the lab DB):
  python3 scripts/seed_service_token.py --label n8n-lab --scope ingest
  python3 scripts/seed_service_token.py --label dify-rag --scope ingest --household <uuid>

The household is resolved from --household, else from LIFEOS_HOUSEHOLD env, else
from the first household that has a current owner (so the token is governed).
The token's owner_person_id is set to that household's current owner.

LAB-ONLY: do not run this against a real-family database. In production the
token is issued by the owner admin flow, not this seeder.
"""
import os
import sys
import argparse
import secrets
import hashlib
import subprocess

PG = {"container": "lifeos-pg", "db": "lifeos", "user": "lifeos"}


def _psql(query):
    cmd = ["docker", "exec", "-i", PG["container"], "psql",
           "-At", "-F", "\t", "-U", PG["user"], "-d", PG["db"]]
    out = subprocess.run(cmd, input=query.encode("utf-8"),
                         capture_output=True, timeout=20)
    if out.returncode != 0:
        return [], out.stderr.decode("utf-8", "replace")[:500]
    rows = []
    for line in out.stdout.decode("utf-8", "replace").splitlines():
        if line and line != "\\.":
            rows.append(tuple(line.split("\t")))
    return rows, None


def _q_str(s):
    return "'%s'" % str(s).replace("'", "''")


def resolve_household_and_owner(household_arg):
    if household_arg:
        rows, err = _psql(
            "SELECT h.id::text, m.person_id::text FROM core.household h "
            "JOIN core.household_member m ON m.household_id = h.id "
            "WHERE h.id = '%s' AND m.role = 'owner' "
            "AND (m.left_on IS NULL OR m.left_on > CURRENT_DATE) "
            "AND h.status = 'active' LIMIT 1;" % household_arg)
        if not rows:
            print("ERROR: no active household %s with a current owner" % household_arg,
                  file=sys.stderr)
            sys.exit(2)
        return rows[0][0], rows[0][1]
    # fall back to env / first household with an owner
    env_hh = os.environ.get("LIFEOS_HOUSEHOLD")
    if env_hh:
        return resolve_household_and_owner(env_hh)
    rows, err = _psql(
        "SELECT h.id::text, m.person_id::text FROM core.household h "
        "JOIN core.household_member m ON m.household_id = h.id "
        "WHERE m.role = 'owner' "
        "AND (m.left_on IS NULL OR m.left_on > CURRENT_DATE) "
        "AND h.status = 'active' LIMIT 1;")
    if not rows:
        print("ERROR: no household with a current owner found", file=sys.stderr)
        sys.exit(2)
    return rows[0][0], rows[0][1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="unique token label, e.g. n8n-lab")
    ap.add_argument("--scope", default="ingest",
                    help="comma-separated scopes (default: ingest)")
    ap.add_argument("--household", default=None, help="household uuid to scope to")
    ap.add_argument("--expires-days", type=int, default=0,
                    help="0 = no expiry")
    args = ap.parse_args()

    hid, owner = resolve_household_and_owner(args.household)
    raw = secrets.token_urlsafe(32)
    tok_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    scope = ",".join(s.strip() for s in args.scope.split(",") if s.strip())
    exp = ("now() + interval '%d days'" % args.expires_days) if args.expires_days else "NULL"

    rows, err = _psql(
        "INSERT INTO core.service_token (label, token_hash, scope, household_id, "
        "owner_person_id, created_by) VALUES (%s, '%s', '{%s}', '%s', '%s', '%s') "
        "ON CONFLICT (label) DO UPDATE SET token_hash = EXCLUDED.token_hash, "
        "scope = EXCLUDED.scope, household_id = EXCLUDED.household_id, "
        "owner_person_id = EXCLUDED.owner_person_id, revoked_at = NULL "
        "RETURNING id::text;" % (_q_str(args.label), tok_hash, scope,
                                 _q_str(hid), _q_str(owner), _q_str(owner)))
    if err:
        print("ERROR inserting token: %s" % err, file=sys.stderr)
        sys.exit(1)
    print("Service token '%s' provisioned (id=%s)." % (args.label, rows[0][0]))
    print("Household: %s   Owner: %s   Scope: %s" % (hid, owner, scope))
    print()
    print("RAW TOKEN (store securely; shown ONCE):")
    print("  %s" % raw)
    print()
    print("Use it as:  Authorization: Bearer %s" % raw)


if __name__ == "__main__":
    main()
