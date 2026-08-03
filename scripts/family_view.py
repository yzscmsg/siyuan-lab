#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
family_view.py -- V8 TEST SURFACE for the LifeOS granular publishing layer.

This is a deliberately minimal, dependency-free (Python stdlib only) read-only
"family consumption" viewer. It is NOT the production PoC-3 facade (Week-9,
real identity/RLS). It exists so the V8 mobile test (5 real family tasks on a
real phone, human-only) has something executable to point a phone at.

Security boundary it demonstrates (ADR-0006 / ADR-0009):
  * It talks ONLY to the LifeOS canonical store (lifeos-pg) via `docker exec
    psql` (trust auth inside the container -- no credential in this process).
  * It NEVER references the SiYuan kernel (:6806), the siyuan container,
    /api/*, or the SiYuan API token. Family members consume LifeOS content
    with ZERO SiYuan credentials.
  * Authorization is enforced by the schema (core.can_consume / core.published_to
    from migration 0007), not by this app.

Identity is TEST-GRADE: a cookie selects one of the lab personas (Owner/Adult/
Member). Anyone who can reach the URL can assume any persona. That is fine for a
controlled family trial; it is explicitly NOT production auth. A banner states
this on every page.

Content is rendered from the lab archive on disk (the S1 export markdown),
resolved via core.document.metadata->>'export_relpath' under ARCHIVE_ROOT.
"""

import os
import re
import sys
import json
import html
import subprocess
import datetime
import http.server
import urllib.parse
from http.cookies import SimpleCookie

# ---------------------------------------------------------------------------
# Config (env-overridable; sane lab defaults)
# ---------------------------------------------------------------------------
HOST = os.environ.get("FAMILY_VIEW_HOST", "0.0.0.0")
PORT = int(os.environ.get("FAMILY_VIEW_PORT", "6900"))
BASE = os.environ.get("FAMILY_VIEW_BASE", "/family")      # path prefix Caddy strips
ARCHIVE_ROOT = os.environ.get("ARCHIVE_ROOT",
                              "/opt/siyuan-lab/exports/markdown")
HOUSEHOLD_NAME = os.environ.get("HOUSEHOLD_NAME", "s1-lab-household")
PG = {"container": "lifeos-pg", "db": "lifeos", "user": "lifeos"}
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

PERSONAS = {}   # id -> {"name":..,"role":..}
HOUSEHOLD_ID = None


# ---------------------------------------------------------------------------
# Postgres access -- docker exec psql (trust auth inside container, no creds)
# ---------------------------------------------------------------------------
def _q_uuid(v):
    """Safely quote a validated uuid for inline SQL. Returns None if invalid."""
    if not isinstance(v, str) or not UUID_RE.match(v):
        return None
    return "'%s'" % v


def _q_str(s):
    """Safely single-quote an arbitrary string literal for inline SQL."""
    return "'%s'" % str(s).replace("'", "''")


def _psql(query):
    """Run a psql query, return list of row-tuples (tab-separated, -At)."""
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
    return rows[0][0] in ("t", "true", "T")


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
        "'{\"surface\":\"v8-family-view\"}'::jsonb);" % (pid, d, hid, oc))


# ---------------------------------------------------------------------------
# Minimal, safe markdown -> HTML (enough for the lab notes)
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
    # prevent path traversal: relpath must stay under ARCHIVE_ROOT
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
# Cookie persona
# ---------------------------------------------------------------------------
def get_person_id(handler):
    c = SimpleCookie()
    c.load(handler.headers.get("Cookie", ""))
    v = c.get("person")
    if not v:
        return None
    pid = v.value
    if pid in PERSONAS:
        return pid
    return None


def set_person_cookie(handler, pid):
    handler.send_header("Set-Cookie",
                        "person=%s; Path=/; HttpOnly; Max-Age=86400" % pid)


# ---------------------------------------------------------------------------
# HTML page helpers
# ---------------------------------------------------------------------------
BANNER = ('<div class="banner">V8 TEST SURFACE &mdash; not production auth. '
          'Anyone who can reach this URL may assume any persona. '
          'Family content is served by LifeOS, never SiYuan.</div>')

PAGE_CSS = """
<style>
  body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;
       background:#f6f7f9;color:#1c1e21;}
  .banner{background:#fff3cd;color:#7a5b00;padding:8px 14px;font-size:13px;
          border-bottom:1px solid #ffe69c;}
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
  pre{background:#f0f2f5;padding:12px;border-radius:8px;overflow:auto;}
  code{background:#f0f2f5;padding:1px 4px;border-radius:4px;}
  .denied{color:#b3261e;}
</style>
"""


def page(handler, title, body_inner, persona_name=None):
    nav = ""
    if persona_name:
        nav = ('<div class="meta">Viewing as <b>%s</b> &middot; '
               '<a href="%s/logout">switch person</a></div>' %
               (html.escape(persona_name), BASE))
    html_doc = ("<!doctype html><html><head><meta name=viewport "
                "content='width=device-width,initial-scale=1'><title>%s</title>"
                "%s</head><body>%s<div class='wrap'>%s%s</div></body></html>"
                % (html.escape(title), PAGE_CSS, BANNER, nav, body_inner))
    payload = html_doc.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


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
        # strip BASE prefix (Caddy handle_path already strips it, but be safe)
        if path.startswith(BASE):
            path = path[len(BASE):] or "/"

        if path == "/healthz":
            self.send_response(200); self.send_header("Content-Type", "text/plain")
            self.end_headers(); self.wfile.write(b"ok"); return

        pid = get_person_id(self)
        if not pid:
            self._login_page()
            return

        name = PERSONAS[pid]["name"]
        if path == "/" or path == "":
            self._feed(pid, name)
        elif path == "/logout":
            self.send_response(303)
            self.send_header("Set-Cookie", "person=; Path=/; Max-Age=0")
            self.send_header("Location", BASE + "/")
            self.end_headers()
        elif path == "/doc":
            self._doc(pid, name, qs.get("id", [""])[0])
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        path, qs = self._qs()
        if path.startswith(BASE):
            path = path[len(BASE):] or "/"
        if path == "/login":
            length = int(self.headers.get("Content-Length", "0"))
            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
            chosen = form.get("person", [""])[0]
            if chosen in PERSONAS:
                self.send_response(303)
                set_person_cookie(self, chosen)
                self.send_header("Location", BASE + "/")
                self.end_headers()
            else:
                self.send_response(400); self.end_headers()
        else:
            self.send_response(404); self.end_headers()

    # ---- pages ----
    def _login_page(self):
        cards = []
        for pid, p in PERSONAS.items():
            cards.append(
                "<form method=post action='%s/login'>"
                "<input type=hidden name=person value='%s'>"
                "<button class='btn'>%s <span class='role'>%s</span></button>"
                "</form>" % (BASE, pid, html.escape(p["name"]),
                             html.escape(p["role"])))
        body = ("<h1>LifeOS Family View</h1>"
                "<p class='meta'>Choose a family member to see what LifeOS "
                "shares with them. This is the V8 test surface.</p>"
                + "".join(cards))
        page(self, "LifeOS Family View", body)

    def _feed(self, pid, name):
        docs, err = published_to(pid)
        if err:
            page(self, "Error", "<div class='card denied'>DB error: %s</div>" % html.escape(err))
            return
        if not docs:
            body = ("<h1>Your shared items</h1>"
                    "<div class='card'>Nothing is shared with %s yet.</div>"
                    % html.escape(name))
            page(self, "Your shared items", body, name)
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
                "<p class='meta'>%d item(s) LifeOS shares with %s.</p>%s"
                % (len(docs), html.escape(name), "".join(items)))
        page(self, "Your shared items", body, name)

    def _doc(self, pid, name, doc_id):
        if not UUID_RE.match(doc_id or ""):
            self.send_response(400); self.end_headers(); return
        allowed = can_consume(doc_id, pid)
        meta = doc_meta(doc_id)
        title = (meta or {}).get("title") or "Document"
        if not allowed:
            audit_consume(pid, doc_id, HOUSEHOLD_ID, False)
            body = ("<h1>%s</h1><div class='card denied'>"
                    "This item is <b>not shared</b> with %s. "
                    "LifeOS denied access (default-deny boundary).</div>"
                    "<p><a href='%s/'>&larr; back to your items</a></p>"
                    % (html.escape(title), html.escape(name), BASE))
            page(self, title, body, name)
            return
        text, err = read_archive((meta or {}).get("rel"))
        if err:
            body = ("<h1>%s</h1><div class='card denied'>Could not load: %s</div>"
                    "<p><a href='%s/'>&larr; back</a></p>"
                    % (html.escape(title), html.escape(err), BASE))
            page(self, title, body, name)
            return
        audit_consume(pid, doc_id, HOUSEHOLD_ID, True)
        body = ("<h1>%s</h1><p class='meta'>%s &middot; shared with %s via LifeOS</p>"
                "<div class='card'>%s</div>"
                "<p><a href='%s/'>&larr; back to your items</a></p>"
                % (html.escape(title), html.escape((meta or {}).get("category", "")),
                    html.escape(name), render_markdown(text), BASE))
        page(self, title, body, name)


def main():
    load_household_and_personas()
    if not PERSONAS:
        print("ERROR: no personas loaded from LifeOS store", file=sys.stderr)
        sys.exit(1)
    srv = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    print("family_view listening on %s:%d (personas: %s)"
          % (HOST, PORT, ", ".join(p["name"] for p in PERSONAS.values())),
          file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
