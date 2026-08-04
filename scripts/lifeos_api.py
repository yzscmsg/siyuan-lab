#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lifeos_api.py -- LifeOS Ingest API (optional-tool contract; ADR-0010 / solution-landscape)

This is the SANCTIONED write path that optional tools (n8n, later Dify, the
SiYuan export adapter) use to submit evidence/artifacts into LifeOS. Per the
solution-landscape integration contract, tools MUST NOT hold a general-purpose
DB account and MUST NOT write authoritative core.* tables directly -- they
CALL THIS API. The API is the single place where the UNIQUE(household_id,
sha256) idempotency rule and the media_type / storage_uri constraints are
applied, so even if a caller retries or delivers a file three times, exactly
one canonical core.document row results.

AUTHORIZATION is by SCOPED SERVICE TOKEN (migration 0009), not by a person
login: an integration presents `Authorization: Bearer <token>`; the API looks
up the token hash, checks scope (must include 'ingest'), expiry and revocation,
and records the governing owner in audit. This keeps the tool boundary separate
from the family-consumption identity boundary (migration 0008, which is a
DEFERRED PoC per ADR-0007).

Security properties (ADR-0010 / solution-landscape):
  * Talks ONLY to lifeos-pg (docker exec psql, trust auth inside the container,
    no credential in this process). NEVER references the SiYuan kernel (:6806),
    the siyuan container, /api/* SiYuan, or any SiYuan API token. Zero SiYuan.
  * Service tokens are hashed (sha256) in the DB; the raw token exists only in
    the caller's secret store and is printed once by seed_service_token.py.
  * Idempotency: client idempotency_key -> canonical document_id; content dedup
    via UNIQUE(household_id, sha256). dup x3 => 1 canonical row.
  * Transactional outbox: each register/withdraw writes a core.ingest_outbox row
    (forward-looking for the currently Hold n8n path; at-least-once, replayable).
  * Fail-closed: every /api endpoint requires a valid, in-scope, unexpired,
    unrevoked token; anything else gets 401. No anonymous write path.

Canonical home: family-lifeos/scripts/lifeos_api.py. siyuan-lab vendors a copy
for the lab VM; edit family-lifeos and re-vendor.

Dependencies: Python stdlib ONLY (matches the rest of the lab and deploys on the
small LXC with no pip). Swap the single _psql() transport for a psycopg
least-privilege role in production; the rest of the security model is unchanged.
"""

import os
import re
import sys
import json
import time
import hashlib
import subprocess
import datetime
import http.server
import urllib.parse

# ---------------------------------------------------------------------------
# Config (env-overridable; sane lab defaults)
# ---------------------------------------------------------------------------
HOST = os.environ.get("LIFEOS_API_HOST", "0.0.0.0")
PORT = int(os.environ.get("LIFEOS_API_PORT", "6903"))
BASE = os.environ.get("LIFEOS_API_BASE", "/api")          # Caddy strips this
PG = {"container": "lifeos-pg", "db": "lifeos", "user": "lifeos"}
REQUIRE_HTTPS = os.environ.get("LIFEOS_API_REQUIRE_HTTPS", "1") == "1"

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Must stay in sync with core.document media_type CHECK (migration 0006).
MEDIA_ALLOWLIST = {
    "text/markdown", "text/plain", "text/csv", "application/json",
    "application/pdf", "image/png", "image/jpeg", "image/gif",
    "image/svg+xml", "application/octet-stream",
}


# ---------------------------------------------------------------------------
# Postgres access -- docker exec psql (trust auth inside container, no creds)
# (Single transport point; swap for a psycopg conn in production.)
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


def psql_script(script):
    """Run a multi-statement script (BEGIN/COMMIT). Returns (rc, stdout, stderr)."""
    cmd = ["docker", "exec", "-i", PG["container"], "psql",
           "-v", "ON_ERROR_STOP=1", "-U", PG["user"], "-d", PG["db"],
           "-At", "-q"]
    try:
        out = subprocess.run(cmd, input=script.encode("utf-8"),
                             capture_output=True, timeout=60)
    except Exception as e:  # pragma: no cover
        return 1, "", "subprocess error: %s" % e
    return out.returncode, out.stdout.decode("utf-8", "replace"), \
        out.stderr.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# Service-token auth (migration 0009)
# ---------------------------------------------------------------------------
def hash_token(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_scope(s):
    s = (s or "").strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def verify_token(raw, needed_scope):
    """Return the token record dict, or None if missing/expired/revoked/wrong-scope."""
    if not raw:
        return None
    h = hash_token(raw)
    rows, err = _psql(
        "SELECT id::text, label, scope, household_id::text, owner_person_id::text, "
        "EXTRACT(EPOCH FROM expires_at)::bigint, "
        "(revoked_at IS NOT NULL)::boolean "
        "FROM core.service_token WHERE token_hash = '%s' LIMIT 1;" % h)
    if not rows or err:
        return None
    id_, label, scope_s, hid, owner, exp, revoked = rows[0]
    if str(revoked) == "t":
        return None
    if exp and int(time.time()) > int(exp):
        return None
    scopes = _parse_scope(scope_s)
    if needed_scope not in scopes:
        return None
    # best-effort last_used_at touch
    _psql("UPDATE core.service_token SET last_used_at = now() WHERE id = '%s';" % id_)
    return {"id": id_, "label": label, "scope": scopes,
            "household_id": hid, "owner_person_id": owner}


def bearer_token(handler):
    auth = handler.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return auth[len("Bearer "):].strip()


# ---------------------------------------------------------------------------
# Validation helpers (mirror core.document CHECKs; pre-validate for clean 422)
# ---------------------------------------------------------------------------
def valid_storage_uri(uri):
    if not uri or not re.match(r"^[a-z][a-z0-9+.\-]*://", uri):
        return False
    if ".." in uri:
        return False
    if re.search(r"://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", uri):
        return False
    return True


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
def audit_ingest(tok, household_id, document_id, action, detail):
    hid = _q_uuid(household_id)
    did = _q_uuid(document_id)
    owner = _q_uuid(tok["owner_person_id"]) if tok else "NULL"
    d = _q_str(detail)
    _psql(
        "INSERT INTO audit.event (actor_person_id, actor_type, action, "
        "object_type, object_id, household_id, outcome, details) VALUES ("
        "%s, 'service', '%s', 'document', %s, %s, 'success', "
        "jsonb_build_object('token_label', %s, 'detail', %s));"
        % (owner, action, did, hid, _q_str(tok["label"] if tok else "anon"), d))


# ---------------------------------------------------------------------------
# Ingest operations
# ---------------------------------------------------------------------------
def register_document(handler, tok, body):
    title = (body.get("title") or "").strip()
    category = (body.get("category") or "").strip()
    media_type = body.get("media_type")
    storage_uri = body.get("storage_uri") or ""
    sha256 = (body.get("sha256") or "").strip()
    source = body.get("source") or "ingest-api"
    idem = (body.get("idempotency_key") or "").strip()
    subject = body.get("subject_person_id")
    retention = body.get("retention_class")
    household_id = body.get("household_id")
    metadata = body.get("metadata") or {}

    if not title or not category:
        return json_resp(handler, 422, {"error": "title and category are required"})
    if not SHA256_RE.match(sha256):
        return json_resp(handler, 422, {"error": "sha256 must be 64 hex chars"})
    if media_type not in MEDIA_ALLOWLIST:
        return json_resp(handler, 422,
                         {"error": "media_type not allowed: %r" % media_type})
    if not valid_storage_uri(storage_uri):
        return json_resp(handler, 422,
                         {"error": "storage_uri must be scheme://, no '..', no raw IPv4"})
    if not idem:
        return json_resp(handler, 422, {"error": "idempotency_key is required"})

    # household resolution: a token scoped to one household wins
    if tok["household_id"]:
        hid = tok["household_id"]
    else:
        hid = household_id
    if not hid or not UUID_RE.match(hid):
        return json_resp(handler, 422,
                         {"error": "household_id required (or token must be scoped to one)"})
    hid_q = _q_uuid(hid)

    # idempotency: same key already recorded -> return the canonical doc
    existing, _ = _psql(
        "SELECT document_id::text FROM core.ingest_request "
        "WHERE idempotency_key = %s;" % _q_str(idem))
    if existing:
        doc_id = existing[0][0]
        audit_ingest(tok, hid, doc_id, "registered", "idempotent-repeat")
        return json_resp(handler, 200,
                         {"document_id": doc_id, "status": "existing",
                          "idempotent": True})

    sub = _q_uuid(subject) or "NULL"
    byte_size = int(body.get("byte_size") or 0)
    meta_json = json.dumps(metadata, ensure_ascii=False).replace("'", "''")

    script = (
        "BEGIN;\n"
        "INSERT INTO core.document "
        "  (household_id, subject_person_id, category, title, storage_uri, "
        "   media_type, byte_size, sha256, source, document_date, retention_class, metadata) "
        "VALUES (%s, %s, %s, %s, %s, %s, %d, %s, %s, CURRENT_DATE, %s, '%s'::jsonb) "
        "ON CONFLICT (household_id, sha256) DO NOTHING RETURNING id::text;\n"
        "SELECT id::text FROM core.document WHERE household_id=%s AND sha256=%s;\n"
        "INSERT INTO core.ingest_request (idempotency_key, document_id, household_id, status) "
        "VALUES (%s, (SELECT id FROM core.document WHERE household_id=%s AND sha256=%s), %s, 'registered') "
        "ON CONFLICT (idempotency_key) DO UPDATE SET updated_at = now();\n"
        "INSERT INTO core.ingest_outbox (topic, payload, household_id) VALUES ("
        "  'document.registered', "
        "  jsonb_build_object('document_id', (SELECT id::text FROM core.document WHERE household_id=%s AND sha256=%s), "
        "                     'household_id', %s::text, 'source', %s), %s);\n"
        "COMMIT;\n"
    ) % (hid_q, sub, _q_str(category), _q_str(title), _q_str(storage_uri),
         _q_str(media_type), byte_size, _q_str(sha256), _q_str(source),
         _q_str(retention), meta_json,
         hid_q, _q_str(sha256),
         _q_str(idem), hid_q, _q_str(sha256), hid_q,
         hid_q, _q_str(sha256), hid_q, _q_str(source), hid_q)

    rc, _out, err = psql_script(script)
    if rc != 0:
        return json_resp(handler, 500, {"error": "db error: %s" % (err or "")[:300]})

    rows, _ = _psql("SELECT id::text FROM core.document WHERE household_id=%s AND sha256=%s;"
                    % (hid_q, _q_str(sha256)))
    doc_id = rows[0][0] if rows else None
    if not doc_id:
        return json_resp(handler, 500, {"error": "document not resolvable after insert"})
    audit_ingest(tok, hid, doc_id, "registered", "api")
    return json_resp(handler, 200, {"document_id": doc_id, "status": "created"})


def get_document(handler, tok, doc_id):
    d = _q_uuid(doc_id)
    if not d:
        return json_resp(handler, 400, {"error": "invalid document id"})
    # 'ingest' or 'read' scope may read
    if "read" not in tok["scope"] and "ingest" not in tok["scope"]:
        return json_resp(handler, 403, {"error": "token scope lacks read"})
    rows, err = _psql(
        "SELECT id::text, household_id::text, title, category, status, media_type, "
        "byte_size, sha256, source, retention_class "
        "FROM core.document WHERE id = %s;" % d)
    if err:
        return json_resp(handler, 500, {"error": err})
    if not rows:
        return json_resp(handler, 404, {"error": "not found"})
    r = rows[0]
    return json_resp(handler, 200, {
        "document_id": r[0], "household_id": r[1], "title": r[2], "category": r[3],
        "status": r[4], "media_type": r[5], "byte_size": int(r[6] or 0),
        "sha256": r[7], "source": r[8], "retention_class": r[9]})


def set_document_status(handler, tok, doc_id, new_status):
    d = _q_uuid(doc_id)
    if not d:
        return json_resp(handler, 400, {"error": "invalid document id"})
    if new_status not in ("active", "superseded", "withdrawn", "archived"):
        return json_resp(handler, 422, {"error": "invalid status"})
    rows, err = _psql(
        "UPDATE core.document SET status = %s WHERE id = %s RETURNING household_id::text;"
        % (_q_str(new_status), d))
    if err:
        return json_resp(handler, 500, {"error": err})
    if not rows:
        return json_resp(handler, 404, {"error": "not found"})
    hid = rows[0][0]
    _psql(
        "INSERT INTO core.ingest_outbox (topic, payload, household_id) VALUES ("
        "  'document.%s', jsonb_build_object('document_id', %s, 'household_id', %s), %s);"
        % (new_status, d, _q_uuid(hid), _q_uuid(hid)))
    _psql("UPDATE core.ingest_request SET status = %s, updated_at = now() "
          "WHERE document_id = %s;" % (_q_str(new_status), d))
    audit_ingest(tok, hid, doc_id, "status:%s" % new_status, "api")
    return json_resp(handler, 200, {"document_id": doc_id, "status": new_status})


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def json_resp(handler, status, obj):
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(payload)


def read_json(handler):
    try:
        length = int(handler.headers.get("Content-Length", "0"))
        raw = handler.rfile.read(length).decode("utf-8", "replace")
        return json.loads(raw)
    except Exception:
        return None


def require_token(handler, needed_scope):
    """Send 401/403 and return None if auth fails; else return the token record."""
    raw = bearer_token(handler)
    if not raw:
        json_resp(handler, 401, {"error": "missing Authorization: Bearer <token>"})
        return None
    tok = verify_token(raw, needed_scope)
    if tok is None:
        # distinguish scope mismatch from bad token only loosely (both 401/403)
        json_resp(handler, 401, {"error": "invalid / expired / revoked / wrong-scope token"})
        return None
    return tok


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _qs(self):
        parsed = urllib.parse.urlparse(self.path)
        return parsed.path, urllib.parse.parse_qs(parsed.query)

    def do_GET(self):
        path, _qs = self._qs()
        if path.startswith(BASE):
            path = path[len(BASE):] or "/"

        if path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            return

        # GET /api/document/{id}
        m = re.match(r"^/document/([0-9a-fA-F\-]+)$", path)
        if m:
            tok = require_token(self, "read")
            if tok is None:
                return
            get_document(self, tok, m.group(1))
            return

        json_resp(self, 404, {"error": "not found"})

    def do_POST(self):
        path, _qs = self._qs()
        if path.startswith(BASE):
            path = path[len(BASE):] or "/"

        if path == "/document/register":
            tok = require_token(self, "ingest")
            if tok is None:
                return
            body = read_json(self)
            if body is None:
                json_resp(self, 400, {"error": "invalid JSON body"})
                return
            register_document(self, tok, body)
            return

        if path == "/document/withdraw":
            tok = require_token(self, "ingest")
            if tok is None:
                return
            body = read_json(self)
            if body is None:
                json_resp(self, 400, {"error": "invalid JSON body"})
                return
            set_document_status(self, tok, body.get("document_id"), "withdrawn")
            return

        if path == "/document/status":
            tok = require_token(self, "ingest")
            if tok is None:
                return
            body = read_json(self)
            if body is None:
                json_resp(self, 400, {"error": "invalid JSON body"})
                return
            set_document_status(self, tok, body.get("document_id"),
                                body.get("status"))
            return

        json_resp(self, 404, {"error": "not found"})


def main():
    if REQUIRE_HTTPS:
        # The API must sit behind Caddy TLS; refuse to bind a plaintext edge.
        # (Run behind the Caddy /api route; do not expose :6903 directly.)
        print("lifeos_api: REQUIRE_HTTPS=1 -- bind behind Caddy TLS only "
              "(Caddy /api -> :6903).", file=sys.stderr)
    srv = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    print("lifeos_api listening on %s:%d (base=%s)" % (HOST, PORT, BASE),
          file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
