#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seed_facade_accounts.py -- LAB-ONLY provisioning of core.auth_account rows.

This is NOT production account creation. In production the owner creates
accounts through an admin flow (or the LifeOS admin console). This script exists
so the production facade (scripts/family_facade.py) has real, password-protected
accounts to authenticate against during the PoC, mirroring how seed_v8_grants.sql
lays down TEST publish grants.

It is idempotent: re-running only inserts accounts that do not already exist
(ON CONFLICT username DO NOTHING). The PBKDF2 parameters MUST match
scripts/family_facade.py (PBKDF2_ITERS = 100000).

Run ON the VM:  python3 scripts/seed_facade_accounts.py
"""

import os
import sys
import base64
import hashlib
import secrets
import subprocess

CT = "lifeos-pg"
DB = "lifeos"
DBUSER = "lifeos"
HOUSEHOLD_NAME = os.environ.get("HOUSEHOLD_NAME", "s1-lab-household")
PBKDF2_ITERS = 100000   # MUST match scripts/family_facade.py

# LAB credentials (documented; not production). Override per-account with env:
#   FACADE_LAB_OWNER_PASS / FACADE_LAB_ADULT_PASS / FACADE_LAB_MEMBER_PASS
LAB_ACCOUNTS = [
    ("Owner Lab",  "owner",  os.environ.get("FACADE_LAB_OWNER_PASS",  "lab-owner-2026")),
    ("Adult Lab",  "adult",  os.environ.get("FACADE_LAB_ADULT_PASS",  "lab-adult-2026")),
    ("Member Lab", "member", os.environ.get("FACADE_LAB_MEMBER_PASS", "lab-member-2026")),
]


def hash_password(pw, iters=PBKDF2_ITERS):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, iters)
    return "pbkdf2_sha256$%d$%s$%s" % (
        iters, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def lit(s):
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"


def psql(sql):
    out = subprocess.run(
        ["docker", "exec", "-i", CT, "psql", "-At", "-U", DBUSER, "-d", DB, "-c", sql],
        capture_output=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError("psql failed: %s" % out.stderr.decode("utf-8", "replace")[:400])
    lines = [l.strip() for l in out.stdout.decode("utf-8", "replace").splitlines() if l.strip()]
    return lines


def resolve_person(name):
    rows = psql("SELECT id::text FROM core.person WHERE legal_name = %s LIMIT 1;" % lit(name))
    return rows[0] if rows else None


def main():
    print("== seed_facade_accounts (LAB ONLY) ==")
    created, existing = [], []
    for legal_name, username, password in LAB_ACCOUNTS:
        person_id = resolve_person(legal_name)
        if not person_id:
            print("  SKIP %-12s -> person '%s' not found" % (username, legal_name))
            continue
        pw_hash = hash_password(password)
        # ON CONFLICT (username) DO NOTHING keeps this idempotent across reseeds.
        sql = (
            "INSERT INTO core.auth_account (person_id, username, pw_hash) "
            "VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING "
            "RETURNING id;"
            % (lit(person_id), lit(username), lit(pw_hash)))
        try:
            rows = psql(sql)
        except RuntimeError as e:
            print("  ERROR %-12s -> %s" % (username, e))
            continue
        if rows:
            created.append((username, password))
            print("  CREATED %-12s (person %s)" % (username, legal_name))
        else:
            existing.append(username)
            print("  EXISTS  %-12s (left unchanged)" % username)
    print("\nSummary: %d created, %d already present." % (len(created), len(existing)))
    if created:
        print("\nLAB CREDENTIALS (use only on the test surface):")
        for username, password in created:
            print("  %-10s / %s" % (username, password))
    if existing:
        print("\nPre-existing (passwords not shown; re-run does not overwrite):")
        for username in existing:
            print("  %-10s (unchanged)" % username)
    print("\nNext: start the facade and point Caddy /family at it, then log in.")


if __name__ == "__main__":
    main()
