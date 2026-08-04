#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
family_facade.py -- PRODUCTION LifeOS family-consumption facade (PoC-3).

This REPLACES the V8 test surface (scripts/family_view.py), which authenticated
with a TEST-GRADE persona cookie: anyone who could reach the URL could assume
any persona. Here a family member logs in with a real username/password bound
to a core.auth_account (migration 0008); their person_id is FIXED by the signed
session and can never be chosen by the client. Impersonation is impossible by
construction.

AUTHORIZATION is still enforced entirely by the schema (migration 0007):
  core.can_consume(doc, person) / core.published_to(person) -- default-deny,
  owner-only publish trigger. The facade only ever queries those functions using
  the AUTHENTICATED person_id. (The V8 viewer proved the boundary end-to-end;
  this facade keeps the same boundary and swaps only the identity layer.)

Security properties (ADR-0006 / ADR-0009):
  * Talks ONLY to lifeos-pg (docker exec psql, trust auth inside the container,
    no credential in this process). NEVER references the SiYuan kernel (:6806),
    the siyuan container, /api/*, or the SiYuan API token. Zero SiYuan creds.
  * Session cookie is HMAC-SHA256 signed (server secret from env
    FAMILY_FACADE_SECRET -- REQUIRED, fail-closed if unset). Payload:
    person_id.version.expiry_unix. Any tampering is rejected.
  * Per-account revocation WITHOUT a session table: bump the account's
    session_version -> every prior signed cookie becomes invalid. (Rotating
    FAMILY_FACADE_SECRET revokes all sessions at once.)
  * Brute-force lockout: failed_attempts + locked_until (app-enforced; the
    column is the durable record).
  * Cookie flags: HttpOnly; Secure when FAMILY_FACADE_SECURE_COOKIE=1 (prod,
    behind Caddy TLS); SameSite=Strict (mitigates cross-site use).
  * Audit: every login (success/failure) and every consume attempt is recorded
    in audit.event.

Dependencies: Python stdlib ONLY (matches the rest of the lab and deploys on
the small LXC with no pip). The single DB transport is _psql(); swap that one
function for a real psycopg connection with a least-privilege read role in
production, and the rest of the security model is unchanged.
"""

import os
import re
import sys
import json
import html
import time
import hmac
import base64
import hashlib
import secrets
import subprocess
import datetime
import http.server
import urllib.parse
from http.cookies import SimpleCookie

# ---------------------------------------------------------------------------
# Config (env-overridable; sane lab defaults)
# ---------------------------------------------------------------------------
HOST = os.environ.get("FAMILY_FACADE_HOST", "0.0.0.0")
PORT = int(os.environ.get("FAMILY_FACADE_PORT", "6902"))
BASE = os.environ.get("FAMILY_FACADE_BASE", "/family")        # Caddy strips this
ARCHIVE_ROOT = os.environ.get("ARCHIVE_ROOT",
                              "/opt/siyuan-lab/exports/markdown")
HOUSEHOLD_NAME = os.environ.get("HOUSEHOLD_NAME", "s1-lab-household")
PG = {"container": "lifeos-pg", "db": "lifeos", "user": "lifeos"}

# Required. Fail-closed if absent: a facade with no signing secret cannot issue
# trustworthy sessions, so it must not start.
SECRET = os.environ.get("FAMILY_FACADE_SECRET", "")
SESSION_TTL = int(os.environ.get("FAMILY_FACADE_SESSION_TTL", "28800"))   # 8h
SECURE_COOKIE = os.environ.get("FAMILY_FACADE_SECURE_COOKIE", "0") == "1"
MAX_FAIL = int(os.environ.get("FAMILY_FACADE_MAX_FAIL", "5"))
LOCK_SECONDS = int(os.environ.get("FAMILY_FACADE_LOCK_SECONDS", "900"))   # 15m
PBKDF2_ITERS = 100000     # MUST match scripts/seed_facade_accounts.py

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

PERSONAS = {}   # id -> {"name":..,"role":..}   (populated for display only)
HOUSEHOLD_ID = None


# ---------------------------------------------------------------------------
# Crypto: PBKDF2 password hashing + HMAC session signing (stdlib only)
# ---------------------------------------------------------------------------
def hash_password(pw, iters=PBKDF2_ITERS):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, iters)
    return "pbkdf2_sha256$%d$%s$%s" % (
        iters, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(pw, stored):
    try:
        algo, iters_s, salt_b64, hash_b64 = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        iters = int(iters_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except Exception:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, iters)
    return hmac.compare_digest(dk, expected)


def sign_session(person_id, version, ttl=SESSION_TTL):
    expiry = int(time.time()) + ttl
    payload = "%s.%d.%d" % (person_id, version, expiry)
    sig = hmac.new(SECRET.encode(), payload.encode(), "sha256").hexdigest()
    return "%s.%s" % (payload, sig)


def verify_session(token):
    """Return (person_id, version, expiry) or None if invalid/expired/tampered."""
    if not token or token.count(".") != 3:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = hmac.new(SECRET.encode(), payload.encode(), "sha256").hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        person_id, version_s, expiry_s = payload.split(".")
        version = int(version_s)
        expiry = int(expiry_s)
    except ValueError:
        return None
    if int(time.time()) > expiry:
        return None
    if not UUID_RE.match(person_id):
        return None
    return (person_id, version, expiry)


# ---------------------------------------------------------------------------
# Postgres access -- docker exec psql (trust auth inside container, no creds)
# (Single transport point; swap for a real psycopg conn in production.)
# ---------------------------------------------------------------------------
def _q_uuid(v):
    if not isinstance(v, str) or not UUID_RE.match(v):
        return None
    return "'%s'" % v


def _q_str(s):
    return "'%s'" % str(s).replace("'", "''")


def _psql(query):
    cmd = ["docker", "exec", "-i", PG["container"], "psql",
           "-At", "-F", "\t", "-U", PG["user"], "-d", PG["db"]]
    try:
        out = subprocess.run(cmd, input=query.encode("utf-8"),
                             capture_output=True, timeout=20)
    except Exception as e:  # pragma: no cover
        return [], "subprocess error: %s" % e
    if out.returncode != 0:
        return [], out.stderr.decode("utf-8", "replace")[:500]
    rows = []
    for line in out.stdout.decode("utf-8", "replace").splitlines():
        line = line.rstrip("\n")
        if line == "\\." or line == "":
            continue
        rows.append(tuple(line.split("\t")))
    return rows, None


def load_household_and_personas():
    global PERSONAS, HOUSEHOLD_ID
    rows, err = _psql(
        "SELECT id, name FROM core.household WHERE name = %s LIMIT 1;"
        % _q_str(HOUSEHOLD_NAME))
    if not rows:
        rows, _ = _psql("SELECT DISTINCT household_id::text, 'lab' "
                        "FROM core.document LIMIT 1;")
    if rows:
        HOUSEHOLD_ID = rows[0][0]
    if HOUSEHOLD_ID:
        hid = _q_uuid(HOUSEHOLD_ID)
        prows, _ = _psql(
            "SELECT p.id::text, p.legal_name, m.role "
            "FROM core.person p JOIN core.household_member m "
            "ON m.person_id = p.id WHERE m.household_id = %s "
            "ORDER BY m.role, p.legal_name;" % hid)
        for pid, name, role in prows:
            PERSONAS[pid] = {"name": name, "role": role or "member"}


# ---------------------------------------------------------------------------
# Account / identity (migration 0008)
# ---------------------------------------------------------------------------
def lookup_account(username):
    u = _q_str(username)
    rows, err = _psql(
        "SELECT person_id::text, pw_hash, failed_attempts, "
        "EXTRACT(EPOCH FROM locked_until)::bigint, "
        "(disabled_at IS NOT NULL)::boolean, session_version "
        "FROM core.auth_account WHERE username = %s LIMIT 1;" % u)
    if not rows or err:
        return None
    person_id, pw_hash, fa, lu, disabled, ver = rows[0]
    return {
        "person_id": person_id,
        "pw_hash": pw_hash,
        "failed_attempts": int(fa or 0),
        "locked_until": int(lu) if lu else None,
        "disabled": str(disabled) == "t",
        "session_version": int(ver or 1),
    }


def lookup_account_by_person(person_id):
    pid = _q_uuid(person_id)
    if not pid:
        return None
    rows, err = _psql(
        "SELECT (disabled_at IS NOT NULL)::boolean, session_version "
        "FROM core.auth_account WHERE person_id = %s LIMIT 1;" % pid)
    if not rows or err:
        return None
    disabled, ver = rows[0]
    return {"disabled": str(disabled) == "t", "session_version": int(ver or 1)}


def person_is_active_member(person_id):
    pid = _q_uuid(person_id)
    if not pid:
        return False
    rows, err = _psql(
        "SELECT EXISTS(SELECT 1 FROM core.household_member m "
        "JOIN core.household h ON h.id = m.household_id "
        "WHERE m.person_id = %s AND (m.left_on IS NULL OR m.left_on > CURRENT_DATE) "
        "AND h.status = 'active')" % pid)
    return bool(rows and str(rows[0][0]) == "t")


def person_name(person_id):
    pid = _q_uuid(person_id)
    if not pid:
        return None
    rows, _ = _psql("SELECT legal_name FROM core.person WHERE id = %s;" % pid)
    return rows[0][0] if rows else None


def person_household(person_id):
    pid = _q_uuid(person_id)
    if not pid:
        return None
    rows, _ = _psql(
        "SELECT household_id::text FROM core.household_member "
        "WHERE person_id = %s LIMIT 1;" % pid)
    return rows[0][0] if rows else None


def register_fail(username, acct):
    new_fails = acct["failed_attempts"] + 1
    if new_fails >= MAX_FAIL:
        _psql(
            "UPDATE core.auth_account SET failed_attempts = %d, last_fail = now(), "
            "locked_until = now() + interval '%d seconds' WHERE username = %s"
            % (new_fails, LOCK_SECONDS, _q_str(username)))
    else:
        _psql(
            "UPDATE core.auth_account SET failed_attempts = %d, last_fail = now() "
            "WHERE username = %s" % (new_fails, _q_str(username)))


def try_login(username, password):
    """Authenticate. Returns a signed session token string, or None.
    Failure reasons are intentionally NOT distinguished to avoid username
    enumeration. All outcomes are audited."""
    acct = lookup_account(username)
    now = int(time.time())
    if acct is None:
        audit_login(None, username, False, "no_such_account")
        return None
    if acct["disabled"]:
        audit_login(acct["person_id"], username, False, "disabled")
        return None
    if acct["locked_until"] and now < acct["locked_until"]:
        audit_login(acct["person_id"], username, False, "locked")
        return None
    if not verify_password(password, acct["pw_hash"]):
        register_fail(username, acct)
        audit_login(acct["person_id"], username, False, "bad_password")
        return None
    _psql(
        "UPDATE core.auth_account SET failed_attempts = 0, last_login = now(), "
        "locked_until = NULL WHERE username = %s;" % _q_str(username))
    audit_login(acct["person_id"], username, True, "ok")
    return sign_session(acct["person_id"], acct["session_version"])


def get_session(handler):
    """Resolve the authenticated person_id from the signed session cookie, or
    None. Re-checks account state (disabled / revocation / membership) so a
    bumped session_version or a disabled account invalidates live cookies."""
    c = SimpleCookie()
    c.load(handler.headers.get("Cookie", ""))
    v = c.get("sid")
    if not v:
        return None
    parsed = verify_session(v.value)
    if not parsed:
        return None
    person_id, version, _ = parsed
    acct = lookup_account_by_person(person_id)
    if not acct:
        return None
    if acct["disabled"]:
        return None
    if acct["session_version"] != version:     # revoked -> session invalid
        return None
    if not person_is_active_member(person_id):
        return None
    return person_id


def revoke_session(person_id):
    """Bump session_version so all current cookies for this account expire."""
    pid = _q_uuid(person_id)
    if pid:
        _psql("UPDATE core.auth_account SET session_version = session_version + 1 "
              "WHERE person_id = %s;" % pid)


# ---------------------------------------------------------------------------
# Authorization (migration 0007) -- unchanged boundary, authenticated person
# ---------------------------------------------------------------------------
def published_to(person_id):
    pid = _q_uuid(person_id)
    if not pid:
        return [], "bad person id"
    rows, err = _psql(
        "SELECT document_id::text, title, category, access "
        "FROM core.published_to(%s);" % pid)
    if err:
        return [], err
    return [(r[0], r[1], r[2], r[3]) for r in rows], None


def can_consume(doc_id, person_id):
    d = _q_uuid(doc_id)
    p = _q_uuid(person_id)
    if not d or not p:
        return False
    rows, err = _psql("SELECT core.can_consume(%s, %s);" % (d, p))
    if err or not rows:
        return False
    return str(rows[0][0]) in ("t", "true", "T")


def doc_meta(doc_id):
    d = _q_uuid(doc_id)
    if not d:
        return None
    rows, err = _psql(
        "SELECT title, category, metadata->>'export_relpath' "
        "FROM core.document WHERE id = %s;" % d)
    if not rows:
        return None
    return {"title": rows[0][0], "category": rows[0][1], "rel": rows[0][2]}


def audit_consume(person_id, doc_id, household_id, ok):
    pid = _q_uuid(person_id)
    d = _q_uuid(doc_id)
    hid = _q_uuid(household_id)
    if not (pid and d and hid):
        return
    oc = _q_str("success" if ok else "denied")
    _psql(
        "INSERT INTO audit.event (actor_person_id, actor_type, action, "
        "object_type, object_id, household_id, outcome, details) VALUES ("
        "%s, 'user', 'family.consume', 'document', %s, %s, %s, "
        "'{\"surface\":\"prod-family-facade\"}'::jsonb);" % (pid, d, hid, oc))


def audit_login(person_id, username, ok, reason):
    pid = _q_uuid(person_id) if person_id else "NULL"
    hid = _q_uuid(person_household(person_id)) if person_id else "NULL"
    u = _q_str(username)
    oc = _q_str("success" if ok else "denied")
    rs = _q_str(reason)
    _psql(
        "INSERT INTO audit.event (actor_person_id, actor_type, action, "
        "object_type, household_id, outcome, details) VALUES ("
        "%s, 'user', 'family.login', 'auth_account', %s, %s, "
        "jsonb_build_object('username', %s, 'reason', %s));"
        % (pid, hid, oc, u, rs))


# ---------------------------------------------------------------------------
# Minimal, safe markdown -> HTML (mirrors scripts/family_view.py; kept separate
# so the production facade has no import coupling to the V8 test surface)
# ---------------------------------------------------------------------------
def render_markdown(text):
    out = []
    lines = text.split("\n")
    i = 0
    in_list = False
    in_code = False
    code_buf = []

    def inline(s):
        s = html.escape(s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", s)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)",
                   r'<a href="\1">\2</a>', s)
        return s

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            if not in_code:
                in_code = True
                code_buf = []
            else:
                in_code = False
                if in_list:
                    out.append("</ul>"); in_list = False
                out.append("<pre><code>%s</code></pre>" %
                           html.escape("\n".join(code_buf)))
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue
        if line.strip() == "":
            if in_list:
                out.append("</ul>"); in_list = False
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            if in_list:
                out.append("</ul>"); in_list = False
            lvl = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lvl, inline(m.group(2)), lvl))
            i += 1
            continue
        if re.match(r"^[-*]\s+", line):
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append("<li>%s</li>" % inline(re.sub(r"^[-*]\s+", "", line)))
            i += 1
            continue
        if in_list:
            out.append("</ul>"); in_list = False
        out.append("<p>%s</p>" % inline(line))
        i += 1
    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("<pre><code>%s</code></pre>" %
                   html.escape("\n".join(code_buf)))
    return "\n".join(out)


def read_archive(relpath):
    if not relpath:
        return None, "document has no archive path"
    full = os.path.normpath(os.path.join(ARCHIVE_ROOT, relpath))
    if not full.startswith(os.path.normpath(ARCHIVE_ROOT)):
        return None, "invalid archive path"
    if not os.path.isfile(full):
        return None, "archive file missing: %s" % relpath
    try:
        with open(full, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, "read error: %s" % e


# ---------------------------------------------------------------------------
# Cookie / redirect helpers
# ---------------------------------------------------------------------------
def session_cookie_header(value, clear=False):
    parts = ["sid=%s" % value, "Path=/", "HttpOnly", "SameSite=Strict"]
    if SECURE_COOKIE:
        parts.append("Secure")
    parts.append("Max-Age=%d" % (0 if clear else SESSION_TTL))
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# HTML page helpers
# ---------------------------------------------------------------------------
BANNER = ('<div class="banner ok">PRODUCTION family surface &mdash; authenticated. '
          'You are identified by your login; you cannot view content another '
          'member is not shared. Content is served by LifeOS, never SiYuan.</div>')

PAGE_CSS = """
<style>
  body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;
       background:#f6f7f9;color:#1c1e21;}
  .banner{background:#e6f4ea;color:#14532d;padding:8px 14px;font-size:13px;
          border-bottom:1px solid #b7e1c4;}
  .banner.err{background:#fce8e6;color:#7a271a;border-bottom-color:#f5c6c0;}
  .wrap{max-width:720px;margin:0 auto;padding:18px;}
  h1{font-size:22px;} h2{font-size:18px;} h3{font-size:16px;}
  a{color:#1a73e8;text-decoration:none;} a:hover{text-decoration:underline;}
  .card{background:#fff;border:1px solid #e3e6ea;border-radius:10px;
        padding:14px 16px;margin:10px 0;}
  .role{display:inline-block;font-size:11px;padding:2px 8px;border-radius:10px;
        background:#eef;color:#335;}
  .meta{color:#888;font-size:12px;}
  .btn{display:block;width:100%;box-sizing:border-box;padding:14px;margin:8px 0;
       font-size:16px;border:1px solid #dadce0;border-radius:10px;background:#fff;
       cursor:pointer;text-align:left;}
  .loginbtn{background:#1a73e8;color:#fff;border-color:#1a73e8;}
  pre{background:#f0f2f5;padding:12px;border-radius:8px;overflow:auto;}
  code{background:#f0f2f5;padding:1px 4px;border-radius:4px;}
  .denied{color:#b3261e;}
  label{display:block;font-size:13px;margin:10px 0 4px;color:#444;}
  input[type=text],input[type=password]{width:100%;box-sizing:border-box;
       padding:12px;border:1px solid #dadce0;border-radius:8px;font-size:15px;}
  .err{color:#b3261e;font-size:13px;margin:8px 0;}
</style>
"""


def page(handler, status, title, body_inner, headers=None):
    html_doc = ("<!doctype html><html><head><meta name=viewport "
                "content='width=device-width,initial-scale=1'><title>%s</title>"
                "%s</head><body>%s<div class='wrap'>%s</div></body></html>"
                % (html.escape(title), PAGE_CSS, BANNER, body_inner))
    payload = html_doc.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "same-origin")
    if headers:
        for k, v in headers.items():
            handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(payload)


def redirect(handler, loc):
    handler.send_response(303)
    handler.send_header("Location", loc)
    handler.end_headers()


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _qs(self):
        parsed = urllib.parse.urlparse(self.path)
        return parsed.path, urllib.parse.parse_qs(parsed.query)

    def do_GET(self):
        path, qs = self._qs()
        if path.startswith(BASE):
            path = path[len(BASE):] or "/"

        if path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            return

        if path == "/login":
            self._login_page()
            return

        if path == "/logout":
            pid = get_session(self)
            if pid:
                revoke_session(pid)          # invalidate this + any other live cookie
            self.send_response(303)
            self.send_header("Set-Cookie", session_cookie_header("", clear=True))
            self.send_header("Location", BASE + "/login")
            self.end_headers()
            return

        pid = get_session(self)
        if not pid:
            redirect(self, BASE + "/login")
            return

        name = person_name(pid) or "member"
        if path == "/" or path == "":
            self._feed(pid, name)
        elif path == "/doc":
            self._doc(pid, name, qs.get("id", [""])[0])
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path, qs = self._qs()
        if path.startswith(BASE):
            path = path[len(BASE):] or "/"
        if path == "/login":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                form = urllib.parse.parse_qs(
                    self.rfile.read(length).decode("utf-8", "replace"))
            except Exception:
                self.send_response(400); self.end_headers(); return
            uname = (form.get("username", [""])[0] or "").strip()
            pw = form.get("password", [""])[0] or ""
            token = try_login(uname, pw)
            if token:
                redirect(self, BASE + "/")
                # attach cookie on the 303
                self.send_header("Set-Cookie", session_cookie_header(token))
            else:
                self._login_page(error="Invalid username or password, "
                                       "or the account is locked.")
        else:
            self.send_response(404); self.end_headers()

    # ---- pages ----
    def _login_page(self, error=None):
        err_html = ('<div class="err">%s</div>' % html.escape(error)) if error else ""
        body = (
            "<h1>LifeOS Family &mdash; Sign in</h1>"
            "<p class='meta'>Family members sign in to see what LifeOS shares "
            "with them. Your identity is fixed by your login.</p>"
            + err_html +
            "<form method=post action='%s/login'>"
            "<label>Username</label>"
            "<input type=text name=username autocomplete=username required>"
            "<label>Password</label>"
            "<input type=password name=password autocomplete=current-password required>"
            "<button class='btn loginbtn' type=submit>Sign in</button>"
            "</form>" % BASE)
        page(self, 200, "LifeOS Family - Sign in", body)

    def _feed(self, pid, name):
        docs, err = published_to(pid)
        if err:
            page(self, 200, "Error",
                 "<div class='card denied'>DB error: %s</div>" % html.escape(err))
            return
        nav = ("<div class='meta'>Signed in as <b>%s</b> &middot; "
               "<a href='%s/logout'>sign out</a></div>" % (html.escape(name), BASE))
        if not docs:
            body = ("<h1>Your shared items</h1>"
                    "<div class='card'>Nothing is shared with you yet.</div>")
            page(self, 200, "Your shared items", nav + body)
            return
        items = []
        for doc_id, title, category, access in docs:
            items.append(
                "<a class='card' href='%s/doc?id=%s'>"
                "<div><b>%s</b></div>"
                "<div class='meta'>%s &middot; access: %s</div>"
                "</a>" % (BASE, doc_id, html.escape(title or "(untitled)"),
                          html.escape(category or ""), html.escape(access or "")))
        body = ("<h1>Your shared items</h1>"
                "<p class='meta'>%d item(s) LifeOS shares with you.</p>%s"
                % (len(docs), "".join(items)))
        page(self, 200, "Your shared items", nav + body)

    def _doc(self, pid, name, doc_id):
        if not UUID_RE.match(doc_id or ""):
            self.send_response(400); self.end_headers(); return
        allowed = can_consume(doc_id, pid)
        meta = doc_meta(doc_id)
        title = (meta or {}).get("title") or "Document"
        if not allowed:
            audit_consume(pid, doc_id, person_household(pid) or HOUSEHOLD_ID, False)
            body = ("<h1>%s</h1><div class='card denied'>"
                    "This item is <b>not shared</b> with you. "
                    "LifeOS denied access (default-deny boundary).</div>"
                    "<p><a href='%s/'>&larr; back to your items</a></p>"
                    % (html.escape(title), BASE))
            page(self, 200, title, body)
            return
        text, err = read_archive((meta or {}).get("rel"))
        if err:
            body = ("<h1>%s</h1><div class='card denied'>Could not load: %s</div>"
                    "<p><a href='%s/'>&larr; back</a></p>"
                    % (html.escape(title), html.escape(err), BASE))
            page(self, 200, title, body)
            return
        audit_consume(pid, doc_id, person_household(pid) or HOUSEHOLD_ID, True)
        body = ("<h1>%s</h1><p class='meta'>%s &middot; shared with you via LifeOS</p>"
                "<div class='card'>%s</div>"
                "<p><a href='%s/'>&larr; back to your items</a></p>"
                % (html.escape(title), html.escape((meta or {}).get("category", "")),
                   render_markdown(text), BASE))
        page(self, 200, title, body)


def main():
    if not SECRET:
        print("FATAL: FAMILY_FACADE_SECRET is not set. Refusing to start "
              "(a facade without a signing secret cannot issue trustworthy "
              "sessions).", file=sys.stderr)
        sys.exit(1)
    load_household_and_personas()
    if not HOUSEHOLD_ID:
        print("ERROR: no household loaded from LifeOS store", file=sys.stderr)
        sys.exit(1)
    srv = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    print("family_facade listening on %s:%d (household=%s, secure_cookie=%s)"
          % (HOST, PORT, HOUSEHOLD_NAME, SECURE_COOKIE), file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
