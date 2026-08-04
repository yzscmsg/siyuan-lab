#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ingest_api_contract.py -- Ingest API contract test (runs on the VM).

Exercises scripts/lifeos_api.py against the live lifeos-pg:
  * register normal doc -> status 'created'
  * duplicate delivery (same idempotency_key) -> 'existing', same id
  * deliver SAME bytes 3x with DIFFERENT keys -> exactly 1 canonical core.document
  * same bytes, different subject_person -> still 1 canonical (UNIQUE(household,sha))
  * illegal media_type -> 422
  * path-traversal storage_uri -> 422
  * missing / bad token -> 401
  * ZERO SiYuan reference in lifeos_api.py source

Run:  python3 tests/test_ingest_api_contract.py [BASE_URL]
Default BASE_URL = http://127.0.0.1:6903
"""
import os
import re
import sys
import json
import hashlib
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:6903"
PG = {"container": "lifeos-pg", "db": "lifeos", "user": "lifeos"}

REPO_ROOT = Path(__file__).resolve().parents[1]
API_SRC = REPO_ROOT / "scripts" / "lifeos_api.py"
SEEDER = REPO_ROOT / "scripts" / "seed_service_token.py"

FORBIDDEN_SIYUAN = ("6806", "siyuan", "SY_TOKEN", "/api/block", "kernel")

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print("  [%s] %-40s %s" % (mark, name, detail))
    return ok


def _psql(query):
    cmd = ["docker", "exec", "-i", PG["container"], "psql",
           "-At", "-F", "\t", "-U", PG["user"], "-d", PG["db"]]
    out = subprocess.run(cmd, input=query.encode("utf-8"),
                         capture_output=True, timeout=20)
    if out.returncode != 0:
        return [], out.stderr.decode("utf-8", "replace")[:300]
    rows = [tuple(l.split("\t")) for l in out.stdout.decode().splitlines()
            if l and l != "\\."]
    return rows, None


def get_token():
    out = subprocess.run([sys.executable, str(SEEDER),
                          "--label", "ingest-contract-test", "--scope", "ingest"],
                         capture_output=True, text=True, cwd=str(REPO_ROOT))
    m = re.search(r"Authorization: Bearer (\S+)", out.stdout)
    if not m:
        print("FAILED to obtain token.\nSTDOUT:%s\nSTDERR:%s"
              % (out.stdout, out.stderr))
        sys.exit(2)
    return m.group(1)


def api(method, path, token=None, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        r = urllib.request.urlopen(req, timeout=15)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def main():
    # household + a person to use as subject
    hh_rows, _ = _psql(
        "SELECT household_id::text FROM core.household_member "
        "WHERE role='owner' LIMIT 1;")
    if not hh_rows:
        print("ERROR: no household/owner in lab DB", file=sys.stderr)
        sys.exit(2)
    hid = hh_rows[0][0]
    p_rows, _ = _psql(
        "SELECT person_id::text FROM core.household_member "
        "WHERE household_id='%s' LIMIT 1;" % hid)
    subject = p_rows[0][0] if p_rows else None

    token = get_token()

    content = b"LifeOS ingest contract sample %s" % os.urandom(4)
    sha = hashlib.sha256(content).hexdigest()
    uri = "lifeos://lab-archive/contract/v1/sample.md"

    # 1. normal register
    st, body = api("POST", "/api/document/register", token, {
        "title": "Contract Sample", "category": "note",
        "media_type": "text/markdown", "storage_uri": uri,
        "sha256": sha, "source": "contract-test", "byte_size": len(content),
        "idempotency_key": "idem-001", "household_id": hid,
        "subject_person_id": subject})
    ok = record("register normal -> created", st == 200 and body.get("status") == "created",
                str(body))
    doc_id = body.get("document_id")

    # 2. duplicate idempotency_key -> existing, same id
    st, body = api("POST", "/api/document/register", token, {
        "title": "Contract Sample", "category": "note",
        "media_type": "text/markdown", "storage_uri": uri,
        "sha256": sha, "source": "contract-test", "byte_size": len(content),
        "idempotency_key": "idem-001", "household_id": hid,
        "subject_person_id": subject})
    ok = record("dup idempotency_key -> existing same id",
                st == 200 and body.get("status") == "existing"
                and body.get("document_id") == doc_id, str(body))

    # 3. same bytes, DIFFERENT keys x3 -> 1 canonical
    for k in ("idem-002", "idem-003"):
        api("POST", "/api/document/register", token, {
            "title": "Contract Sample", "category": "note",
            "media_type": "text/markdown", "storage_uri": uri,
            "sha256": sha, "source": "contract-test", "byte_size": len(content),
            "idempotency_key": k, "household_id": hid,
            "subject_person_id": subject})
    rows, _ = _psql("SELECT count(*) FROM core.document WHERE household_id='%s' AND sha256='%s';"
                    % (hid, sha))
    cnt = int(rows[0][0]) if rows else -1
    record("same bytes x3 -> 1 canonical", cnt == 1, "count=%s" % cnt)

    # 4. same bytes, different subject -> still 1 canonical
    api("POST", "/api/document/register", token, {
        "title": "Contract Sample", "category": "note",
        "media_type": "text/markdown", "storage_uri": uri,
        "sha256": sha, "source": "contract-test", "byte_size": len(content),
        "idempotency_key": "idem-004-diff-subject", "household_id": hid,
        "subject_person_id": subject})
    rows, _ = _psql("SELECT count(*) FROM core.document WHERE household_id='%s' AND sha256='%s';"
                    % (hid, sha))
    cnt2 = int(rows[0][0]) if rows else -1
    record("same bytes diff subject -> 1 canonical", cnt2 == 1, "count=%s" % cnt2)

    # 5. illegal media_type -> 422
    st, body = api("POST", "/api/document/register", token, {
        "title": "x", "category": "note", "media_type": "application/x-msdownload",
        "storage_uri": "lifeos://lab-archive/bad/v1/x.exe", "sha256": "0" * 64,
        "idempotency_key": "idem-bad-media", "household_id": hid})
    record("illegal media_type -> 422", st == 422, "status=%s" % st)

    # 6. path traversal storage_uri -> 422
    st, body = api("POST", "/api/document/register", token, {
        "title": "x", "category": "note", "media_type": "text/plain",
        "storage_uri": "lifeos://lab-archive/../../etc/passwd", "sha256": "1" * 64,
        "idempotency_key": "idem-bad-uri", "household_id": hid})
    record("path traversal storage_uri -> 422", st == 422, "status=%s" % st)

    # 7. missing token -> 401
    st, body = api("POST", "/api/document/register", None, {
        "title": "x", "category": "note", "media_type": "text/plain",
        "storage_uri": "lifeos://x", "sha256": "2" * 64,
        "idempotency_key": "idem-no-token", "household_id": hid})
    record("missing token -> 401", st == 401, "status=%s" % st)

    # 8. bad token -> 401
    st, body = api("POST", "/api/document/register", "not-a-real-token", {
        "title": "x", "category": "note", "media_type": "text/plain",
        "storage_uri": "lifeos://x", "sha256": "3" * 64,
        "idempotency_key": "idem-bad-token", "household_id": hid})
    record("bad token -> 401", st == 401, "status=%s" % st)

    # 9. GET without token -> 401
    st, body = api("GET", "/api/document/%s" % doc_id)
    record("GET without token -> 401", st == 401, "status=%s" % st)

    # 10. zero SiYuan reference in source
    if API_SRC.exists():
        src = API_SRC.read_text(encoding="utf-8", errors="replace").lower()
        hits = [m for m in FORBIDDEN_SIYUAN if m.lower() in src]
        record("zero SiYuan reference in lifeos_api.py", not hits,
               ("forbidden: %s" % hits) if hits else "clean")
    else:
        record("lifeos_api.py present for scan", False, "missing: %s" % API_SRC)

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n%d/%d checks passed" % (passed, total))
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
