#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v8_smoke_test.py -- automated smoke test for the V8 family-view surface.

This validates the MACHINE side of V8 (the surface works, the ADR-0006
boundary holds end-to-end through the Caddy edge). The HUMAN side -- 5 real
family tasks on a real phone -- lives in docs/implementation/05-v8-mobile-test.md
and must be run by a person; this script cannot replace it.

Run on the VM (or any host that can reach the Caddy edge):
    python3 scripts/v8_smoke_test.py [--base https://127.0.0.1/family]
"""

import sys
import ssl
import json
import urllib.request
import urllib.parse
import subprocess

# Default: hit the viewer directly over HTTP (no Caddy/TLS) to validate viewer
# logic + ADR-0006 boundary deterministically. The human phone ingress is the
# Caddy HTTPS route https://192.168.88.9/family (browsers accept the internal
# CA; the owner already reaches the SiYuan console the same way).
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:6900"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# known lab fixtures (see scripts/seed_v8_grants.sql + 0002/0007)
ADULT = "c9083aad-5db1-49dc-9afd-4a5f13d92b8c"
MEMBER = "7ee1bb39-b7f7-428e-8019-78c7feb4de11"
OWNER = "35d16bc5-58f6-4759-a64f-77a079e861d4"
DOC = {
    "n06_household": "71cef654-449a-4661-9a5a-01455b603986",
    "n07_adult":     "92893b09-cdb8-493c-93f7-a78660ae2cc7",
    "n08_member":    "61763ae1-c426-414e-97cc-41d2a8679dea",
    "n09_ungranted": "e4e6e89a-c295-41b4-9e25-543079d76e54",
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
        return None  # capture the 303 (with Set-Cookie) instead of following


_login_opener = urllib.request.build_opener(
    _NoRedirect(), urllib.request.HTTPSHandler(context=CTX))


def login(person_id):
    """POST /login but do NOT follow the 303; capture Set-Cookie manually
    (urllib's default opener discards Set-Cookie on redirect)."""
    data = urllib.parse.urlencode({"person": person_id}).encode()
    req = urllib.request.Request(BASE + "/login", data=data, method="POST")
    try:
        r = _login_opener.open(req, timeout=10)
        hdrs = r.headers
    except urllib.error.HTTPError as e:
        hdrs = e.headers
    c = hdrs.get("Set-Cookie", "")
    cookie = c.split(";")[0] if c else ""
    return cookie


def has(text, needle):
    return needle in text


def check(name, cond, detail=""):
    results[name] = {"pass": bool(cond), "detail": detail}
    print(("PASS " if cond else "FAIL ") + name + ((" -- " + detail) if detail else ""))


# 1. edge login page (no cookie)
st, body, _ = get("/")
check("edge_login_page_reachable", st == 200 and has(body, "LifeOS Family View"),
      "status=%s" % st)

# 2. Adult feed: household (c01,c02,n06) + adult personal (n07) = 4
cookie_a = login(ADULT)
st, body, _ = get("/", cookie_a)
check("adult_login_sets_cookie", bool(cookie_a), "cookie=%r" % cookie_a[:20])
check("adult_feed_shows_shared", st == 200 and has(body, "Your shared items"),
      "status=%s" % st)
# count occurrences of /doc?id= links
import re
adult_docs = set(re.findall(r"/doc\?id=([0-9a-f-]+)", body))
check("adult_sees_4_items", len(adult_docs) == 4,
      "items=%d %s" % (len(adult_docs), sorted(adult_docs)[:3]))

# 3. Adult can open n07 (person-scoped to adult)
st, body, _ = get("/doc?id=" + DOC["n07_adult"], cookie_a)
check("adult_can_open_personal_n07", st == 200 and not has(body, "not shared"),
      "status=%s" % st)

# 4. Adult CANNOT open n09 (ungranted -> default-deny, 200 denied page)
st, body, _ = get("/doc?id=" + DOC["n09_ungranted"], cookie_a)
check("adult_denied_ungranted_n09", st == 200 and has(body, "not shared"),
      "status=%s" % st)

# 5. Member feed: household (c01,c02,n06) + member role (n08) = 4
cookie_m = login(MEMBER)
st, body, _ = get("/", cookie_m)
member_docs = set(re.findall(r"/doc\?id=([0-9a-f-]+)", body))
check("member_sees_4_items", len(member_docs) == 4,
      "items=%d" % len(member_docs))
st, body, _ = get("/doc?id=" + DOC["n08_member"], cookie_m)
check("member_can_open_role_n08", st == 200 and not has(body, "not shared"),
      "status=%s" % st)

# 6. audit trail recorded (family.consume events exist)
out = subprocess.run(
    ["docker", "exec", "-i", "lifeos-pg", "psql", "-At", "-U", "lifeos",
     "-d", "lifeos", "-c",
     "SELECT count(*) FROM audit.event WHERE action='family.consume';"],
    capture_output=True, text=True)
try:
    audit_n = int((out.stdout or "0").strip().splitlines()[0])
except Exception:
    audit_n = -1
check("audit_trail_present", audit_n > 0, "family.consume events=%s" % audit_n)

# 7. boundary: the family surface must NEVER reference the SiYuan kernel/token.
#    Primary proof = the source code (the lab dir is named siyuan-lab, so we
#    exclude that and target only real kernel references). We strip the module
#    docstring and # comments so documentation prose ("NEVER references :6806")
#    is not mistaken for a real reference.
raw = subprocess.run(
    ["cat", "/opt/siyuan-lab/scripts/family_view.py"],
    capture_output=True, text=True).stdout
# drop the module docstring + # comments so documentation prose
# ("NEVER references :6806") is not mistaken for a real reference
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
# secondary: the running process cmdline must not pass a kernel port/token
ps = subprocess.run(["ps", "aux"], capture_output=True, text=True).stdout
fv_lines = [l for l in ps.splitlines()
            if "family_view.py" in l and "grep" not in l and "v8_smoke_test" not in l]
proc_bad = [l for l in fv_lines
            if ("6806" in l) or ("SIYUAN_ACCESS" in l.upper())
            or ("siyuan-poc" in l) or ("siyuan:6806" in l)]
check("zero_siyuan_kernel_reference_proc", len(proc_bad) == 0,
      "proc_lines=%d bad=%d" % (len(fv_lines), len(proc_bad)))

passed = sum(1 for v in results.values() if v["pass"])
total = len(results)
print("\n=== V8 smoke: %d/%d passed ===" % (passed, total))
print(json.dumps(results, indent=2))
sys.exit(0 if passed == total else 1)
