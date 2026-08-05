#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =====================================================================
# TEST SCRIPT METADATA  (format: docs/testing/README.md)
#   gate:      NONE - this is the DEFERRED PoC facade (ADR-0007), synthetic data only
#   goal:      prove real-auth login + signed session + schema boundary with identity
#   inputs:    running family_facade.py (:6902); lab accounts from seed_facade_accounts.py
#   expected:  anon -> /login redirect; valid login -> signed cookie + feed; forged
#              session rejected; privilege-escalation (member opens owner doc) denied
#   deps:      core.auth_account (migration 0008); FAMILY_FACADE_SECRET set
#   run:       python3 scripts/facade_smoke_test.py [--base http://127.0.0.1:6902]
#   issues:    DEFERRED PoC - NOT a production identity/real-data boundary. Do NOT feed
#              it real family data. See ADR-0007. Zero SiYuan reference by construction.
# =====================================================================
"""
facade_smoke_test.py -- automated smoke test for the DEFERRED PoC family facade (synthetic data only).

Unlike scripts/v8_smoke_test.py (which assumed a test-grade persona cookie),
this authenticates with REAL credentials via POST /login and proves:

  1. Unauthenticated requests are redirected to /login (no anonymous access).
  2. A valid login yields a signed session cookie; the feed + docs render.
  3. The schema authorization boundary still holds with authenticated identity:
       - owner sees household-wide (c01,c02,n06) = 3
       - adult sees those + person-scoped n07 = 4, and CAN open n07
       - member sees those + role-scoped n08 = 4, and CAN open n08
       - member CANNOT open n07 (adult-personal) -> default-deny page
       - nobody can open n09 (ungranted) -> default-deny page
  4. A FORGED/tampered session cookie is rejected (redirect to /login) --
     the core fix over the V8 test surface: you cannot impersonate.
  5. Audit trail records logins + consumes.
  6. The facade source contains ZERO SiYuan kernel/token references (the
     boundary proof, same method as v8_smoke_test.py).

Run ON the VM (or any host that can reach the facade):
    python3 scripts/facade_smoke_test.py [--base http://127.0.0.1:6902]
"""

import os
import sys
import ssl
import json
import re
import urllib.request
import urllib.parse
import subprocess

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:6902"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# Lab credentials created by scripts/seed_facade_accounts.py (override via env).
OWNER_U = os.environ.get("FACADE_LAB_OWNER_USER", "owner")
OWNER_P = os.environ.get("FACADE_LAB_OWNER_PASS", "lab-owner-2026")
ADULT_U = os.environ.get("FACADE_LAB_ADULT_USER", "adult")
ADULT_P = os.environ.get("FACADE_LAB_ADULT_PASS", "lab-adult-2026")
MEMBER_U = os.environ.get("FACADE_LAB_MEMBER_USER", "member")
MEMBER_P = os.environ.get("FACADE_LAB_MEMBER_PASS", "lab-member-2026")


def _pg_one(sql):
    try:
        out = subprocess.run(
            ["docker", "exec", "-i", "lifeos-pg", "psql", "-At", "-U", "lifeos",
             "-d", "lifeos", "-c", sql],
            capture_output=True, text=True, timeout=10)
        line = (out.stdout or "").strip().splitlines()
        return line[0] if line else None
    except Exception:
        return None


def _lookup_person(name):
    return _pg_one("SELECT id FROM core.person WHERE legal_name='%s' LIMIT 1" % name)


def _lookup_doc(title):
    return _pg_one("SELECT id FROM core.document WHERE title='%s' LIMIT 1" % title)


DOC = {
    "n06_household": _lookup_doc("n06") or "8205f92d-89dd-43d5-a1f3-add10628e472",
    "n07_adult":     _lookup_doc("n07") or "5f1ad6c8-ed7d-4cc0-8bc1-f458972daf37",
    "n08_member":    _lookup_doc("n08") or "403de9a2-f690-44d3-85eb-09f4178aadb8",
    "n09_ungranted": _lookup_doc("n09") or "479d0e24-57ad-4576-9f25-42fb2a9d7425",
}

results = {}


def get(path, cookie=None):
    req = urllib.request.Request(BASE + path)
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        r = urllib.request.urlopen(req, context=CTX, timeout=10)
        return r.status, r.read().decode("utf-8", "replace"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.headers


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_login_opener = urllib.request.build_opener(
    _NoRedirect(), urllib.request.HTTPSHandler(context=CTX))


def login(username, password):
    """POST /login, do NOT follow the 303, capture Set-Cookie sid manually."""
    data = urllib.parse.urlencode(
        {"username": username, "password": password}).encode()
    req = urllib.request.Request(BASE + "/login", data=data, method="POST")
    try:
        r = _login_opener.open(req, timeout=10)
        hdrs = r.headers
    except urllib.error.HTTPError as e:
        hdrs = e.headers
    c = hdrs.get("Set-Cookie", "")
    return c.split(";")[0] if c else ""   # "sid=PAYLOAD.SIG"


def has(text, needle):
    return needle in text


def check(name, cond, detail=""):
    results[name] = {"pass": bool(cond), "detail": detail}
    print(("PASS " if cond else "FAIL ") + name + ((" -- " + detail) if detail else ""))


def feed_ids(body):
    return set(re.findall(r"/doc\?id=([0-9a-f-]+)", body))


# 1. unauthenticated access is redirected to /login
st, body, _ = get("/")
check("anon_redirected_to_login", st in (303, 302) or "Sign in" in body,
      "status=%s" % st)

# 2. owner login + feed (household-wide only = 3)
cookie_o = login(OWNER_U, OWNER_P)
check("owner_login_sets_session", bool(cookie_o), "cookie=%r" % cookie_o[:24])
st, body, _ = get("/", cookie_o)
check("owner_feed_renders", st == 200 and has(body, "Your shared items"), "status=%s" % st)
owner_docs = feed_ids(body)
check("owner_sees_3_household_items", len(owner_docs) == 3,
      "items=%d" % len(owner_docs))

# 3. owner can open a household doc, cannot open ungranted n09
st, body, _ = get("/doc?id=" + DOC["n06_household"], cookie_o)
check("owner_can_open_household_n06", st == 200 and not has(body, "not shared"), "status=%s" % st)
st, body, _ = get("/doc?id=" + DOC["n09_ungranted"], cookie_o)
check("owner_denied_ungranted_n09", st == 200 and has(body, "not shared"), "status=%s" % st)

# 4. adult login + feed (4) + can open person-scoped n07
cookie_a = login(ADULT_U, ADULT_P)
st, body, _ = get("/", cookie_a)
adult_docs = feed_ids(body)
check("adult_sees_4_items", len(adult_docs) == 4, "items=%d" % len(adult_docs))
st, body, _ = get("/doc?id=" + DOC["n07_adult"], cookie_a)
check("adult_can_open_personal_n07", st == 200 and not has(body, "not shared"), "status=%s" % st)

# 5. member login + feed (4) + can open role-scoped n08, CANNOT open n07
cookie_m = login(MEMBER_U, MEMBER_P)
st, body, _ = get("/", cookie_m)
member_docs = feed_ids(body)
check("member_sees_4_items", len(member_docs) == 4, "items=%d" % len(member_docs))
st, body, _ = get("/doc?id=" + DOC["n08_member"], cookie_m)
check("member_can_open_role_n08", st == 200 and not has(body, "not shared"), "status=%s" % st)
st, body, _ = get("/doc?id=" + DOC["n07_adult"], cookie_m)
check("member_denied_adult_personal_n07", st == 200 and has(body, "not shared"),
      "status=%s" % st)

# 6. bad password is rejected (no session cookie)
bad = login(OWNER_U, "wrong-password")
check("bad_password_rejected", not bad, "cookie=%r" % bad[:24])

# 7. FORGED session cookie is rejected (tamper the signature)
if cookie_o and cookie_o.startswith("sid="):
    token = cookie_o[len("sid="):]
    payload, sig = token.rsplit(".", 1)
    forged = "sid=" + payload + "." + ("0" if sig[-1] != "0" else "1")  # flip last sig char
    st, body, _ = get("/", forged)
    # rejected -> redirected to login (no authenticated feed)
    check("forged_session_rejected", st in (303, 302) and "Your shared items" not in body,
          "status=%s" % st)
else:
    check("forged_session_rejected", False, "no owner cookie to tamper")

# 8. audit trail recorded (login + consume events)
out = subprocess.run(
    ["docker", "exec", "-i", "lifeos-pg", "psql", "-At", "-U", "lifeos",
     "-d", "lifeos", "-c",
     "SELECT count(*) FROM audit.event WHERE action IN ('family.login','family.consume');"],
    capture_output=True, text=True)
try:
    audit_n = int((out.stdout or "0").strip().splitlines()[0])
except Exception:
    audit_n = -1
check("audit_trail_present", audit_n > 0, "login+consume events=%s" % audit_n)

# 9. zero SiYuan kernel/token reference in the facade source
raw = subprocess.run(
    ["cat", "/opt/siyuan-lab/scripts/family_facade.py"],
    capture_output=True, text=True).stdout
code_lines = []
in_doc = False
for ln in raw.splitlines():
    if '"""' in ln:
        in_doc = not in_doc
        continue
    if in_doc:
        continue
    if ln.lstrip().startswith("#"):
        continue
    code_lines.append(ln)
code = "\n".join(code_lines)
forbidden = ["6806", "SIYUAN_ACCESS", "siyuan-poc", "siyuan:6806", "/api/"]
leaks = [f for f in forbidden if f.lower() in code.lower()]
check("zero_siyuan_kernel_reference_source", len(leaks) == 0,
      "forbidden_tokens_found=%s" % leaks)

passed = sum(1 for v in results.values() if v["pass"])
total = len(results)
print("\n=== facade smoke: %d/%d passed ===" % (passed, total))
print(json.dumps(results, indent=2))
sys.exit(0 if passed == total else 1)
