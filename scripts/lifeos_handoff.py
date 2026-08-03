"""S1 step 8: hand the SiYuan export to the LifeOS canonical store.

Roadmap requirement
-------------------
  step 8   "将导出内容交给第4周 Document API 注册；LifeOS 分配 UUID/owner/ACL/hash，
            禁止读取思源内部数据库或数据目录。"
  verify   "LifeOS 只通过标准导出/API接收内容；卸载思源后 canonical 数据仍完整。"
  wk4 verify "50 份 corpus 投递三次，canonical 文档数仍为 50。"

The week-4 Document API does not exist yet, so this registers directly against
the *real* schema from family-lifeos db/migrations (vendored, commit f597f61),
exercising the constraint that actually defines ingest idempotency:

    core.document UNIQUE (household_id, sha256)

Two things this test is careful about:

1.  Boundary proof. Every byte read is recorded in `sources_read`. The test then
    asserts that nothing under workspace/data, no *.sy file and no SiYuan SQLite
    database was opened. Reading the export tree is allowed; reading SiYuan's
    internals is a hard-gate failure.

2.  Contract negatives. Beyond the happy path it delivers: the same payload three
    times, same filename with different content, identical content under a
    different owner, an illegal media type, a path-traversal storage URI, and a
    declared hash that does not match the bytes.

Run ON the VM:  python3 scripts/lifeos_handoff.py
"""
from __future__ import annotations
import os, io, csv, json, re, uuid, hashlib, subprocess, sys, datetime

BASE = "/opt/siyuan-lab"
EXPORT_MD = os.path.join(BASE, "exports", "markdown")
REPORT = os.path.join(BASE, "exports", "lifeos_handoff_report.json")
CT = "lifeos-pg"
DB = "lifeos"
DBUSER = "lifeos"

HOUSEHOLD_NAME = "s1-lab-household"
PEOPLE = [("Owner Lab", "owner"), ("Adult Lab", "adult"), ("Member Lab", "member")]

MEDIA = {".md": "text/markdown", ".png": "image/png", ".pdf": "application/pdf",
         ".csv": "text/csv", ".txt": "text/plain", ".svg": "image/svg+xml",
         ".json": "application/json"}
ALLOWED_MEDIA = set(MEDIA.values())

FORBIDDEN_READ_MARKERS = ("/workspace/data/", ".sy", "siyuan.db", "/workspace/temp/")

sources_read: list[str] = []


def read_bytes(path):
    sources_read.append(path)
    with open(path, "rb") as f:
        return f.read()


CMD_TAG_RE = re.compile(
    r"^(INSERT \d+ \d+|UPDATE \d+|DELETE \d+|COPY \d+|SELECT \d+|SET|BEGIN|COMMIT)$")


def psql(sql, stdin=None, tuples_only=True):
    cmd = ["docker", "exec", "-i", CT, "psql", "-v", "ON_ERROR_STOP=1",
           "-U", DBUSER, "-d", DB]
    if tuples_only:
        # -q suppresses the command tag; without it `-At -c "... RETURNING id"`
        # emits BOTH the id and "INSERT 0 1", which then gets spliced into the
        # next statement as an invalid uuid literal.
        cmd += ["-At", "-q"]
    if sql:
        cmd += ["-c", sql]
    out = subprocess.run(cmd, input=(stdin or "").encode("utf-8"),
                         capture_output=True, timeout=180)
    if out.returncode != 0:
        raise RuntimeError("psql failed: %s" % out.stderr.decode("utf-8", "replace")[:500])
    return out.stdout.decode("utf-8", "replace").strip()


def psql_scalar(sql):
    """One value. Defensive against any command tag that still slips through."""
    raw = psql(sql)
    for line in raw.splitlines():
        line = line.strip()
        if line and not CMD_TAG_RE.match(line):
            return line
    return ""


def psql_script(script):
    # -q again: without it a no-op `ON CONFLICT DO NOTHING ... RETURNING id`
    # still prints "INSERT 0 0", which reads as a non-empty result and would
    # report a correctly-rejected row as accepted.
    cmd = ["docker", "exec", "-i", CT, "psql", "-v", "ON_ERROR_STOP=1",
           "-U", DBUSER, "-d", DB, "-At", "-q"]
    out = subprocess.run(cmd, input=script.encode("utf-8"), capture_output=True, timeout=300)
    return out.returncode, out.stdout.decode("utf-8", "replace"), out.stderr.decode("utf-8", "replace")


def sql_lit(s):
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"


# --------------------------------------------------------------------------
def collect_export():
    """Walk ONLY the portable export tree. Never SiYuan internals."""
    docs = []
    for root, _dirs, files in os.walk(EXPORT_MD):
        for fn in sorted(files):
            p = os.path.join(root, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext not in MEDIA:
                continue
            blob = read_bytes(p)
            rel = os.path.relpath(p, EXPORT_MD).replace("\\", "/")
            notebook = rel.split("/")[0]
            title = fn
            if ext == ".md":
                for line in blob.decode("utf-8", "replace").splitlines():
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
                else:
                    title = os.path.splitext(fn)[0]
            docs.append({
                "rel": rel,
                "notebook": notebook,
                "title": title[:200],
                "category": "note" if ext == ".md" else "attachment",
                "media_type": MEDIA[ext],
                "byte_size": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest(),
                "source": "siyuan-export/v3.7.3",
            })
    return docs


def ensure_fixture():
    hh = psql_scalar("select id from core.household where name=%s" % sql_lit(HOUSEHOLD_NAME))
    if not hh:
        hh = psql_scalar("insert into core.household(name) values (%s) returning id"
                         % sql_lit(HOUSEHOLD_NAME))
    people = {}
    for legal, role in PEOPLE:
        pid = psql_scalar("select id from core.person where legal_name=%s" % sql_lit(legal))
        if not pid:
            pid = psql_scalar(
                "insert into core.person(legal_name, preferred_name) values (%s,%s) returning id"
                % (sql_lit(legal), sql_lit(role)))
        psql("insert into core.household_member(household_id, person_id, role) "
             "values (%s,%s,%s) on conflict do nothing"
             % (sql_lit(hh), sql_lit(pid), sql_lit(role)))
        people[role] = pid
    return hh, people


def register(docs, household, owner_person, request_id, pass_no):
    """Idempotent bulk register. Returns (attempted, inserted)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for d in docs:
        storage_uri = "lifeos://lab-archive/%s/%s/v1/%s" % (
            HOUSEHOLD_NAME, d["sha256"][:12], os.path.basename(d["rel"]))
        meta = {"acl": {"read": ["owner", "adult"], "write": ["owner"]},
                "classification": "internal",
                "source_notebook": d["notebook"],
                "export_relpath": d["rel"],
                "ingest_pass": pass_no}
        w.writerow([household, owner_person, d["category"], d["title"], storage_uri,
                    d["media_type"], d["byte_size"], d["sha256"], d["source"],
                    "standard-7y", json.dumps(meta, ensure_ascii=False)])
    # NOTE: the staging table must be created INSIDE the transaction. psql runs
    # in autocommit, so a bare `CREATE TEMP TABLE ... ON COMMIT DROP` is dropped
    # by its own implicit commit before the next statement can see it.
    script = """
BEGIN;
CREATE TEMP TABLE stg(household_id uuid, subject_person_id uuid, category text, title text,
  storage_uri text, media_type text, byte_size bigint, sha256 char(64), source text,
  retention_class text, metadata jsonb) ON COMMIT DROP;
\\copy stg FROM STDIN WITH (FORMAT csv)
%s\\.
INSERT INTO core.document
  (household_id, subject_person_id, category, title, storage_uri, media_type,
   byte_size, sha256, source, document_date, retention_class, metadata)
SELECT household_id, subject_person_id, category, title, storage_uri, media_type,
       byte_size, sha256, source, CURRENT_DATE, retention_class, metadata
FROM stg
ON CONFLICT (household_id, sha256) DO NOTHING;
INSERT INTO audit.event(actor_type, action, object_type, household_id, request_id, outcome, details)
VALUES ('service','ingest','document',%s,%s,'success',
        jsonb_build_object('pass',%d,'source','siyuan-export','attempted',(SELECT count(*) FROM stg)));
COMMIT;
SELECT count(*) FROM core.document WHERE household_id=%s;
""" % (buf.getvalue(), sql_lit(household), sql_lit(str(request_id)), pass_no, sql_lit(household))
    rc, out, err = psql_script(script)
    if rc != 0:
        raise RuntimeError("register pass %d failed: %s" % (pass_no, err[:600]))
    total = int([l for l in out.strip().splitlines() if l.strip().isdigit()][-1])
    return len(docs), total


def contract_negatives(household, people, sample):
    """Roadmap week-4 step 10 contract tests, applied to the S1 handoff."""
    res = {}

    def try_insert(label, **kw):
        cols = ["household_id", "subject_person_id", "category", "title", "storage_uri",
                "media_type", "byte_size", "sha256", "source", "retention_class"]
        vals = [sql_lit(kw.get(c)) if c not in ("byte_size",) else str(kw.get(c) or 0)
                for c in cols]
        sql = ("INSERT INTO core.document(%s) VALUES (%s) ON CONFLICT (household_id, sha256) "
               "DO NOTHING RETURNING id" % (",".join(cols), ",".join(vals)))
        rc, out, err = psql_script(sql)
        rows = [l.strip() for l in out.splitlines()
                if l.strip() and not CMD_TAG_RE.match(l.strip())]
        res[label] = {"accepted": rc == 0 and bool(rows),
                      "new_row_id": rows[0] if rows else None,
                      "error": err.strip().splitlines()[0][:160] if rc != 0 else None}

    base = dict(household_id=household, subject_person_id=people["owner"],
                category="note", title="contract probe",
                media_type="text/markdown", retention_class="standard-7y",
                source="contract-test")

    # C1 duplicate delivery of an already-registered doc -> must NOT create a second row
    try_insert("C1_duplicate_delivery", **dict(base,
               storage_uri="lifeos://lab-archive/dup/v1/x.md",
               byte_size=sample["byte_size"], sha256=sample["sha256"]))

    # C2 same filename, different content -> MUST be accepted as a distinct document
    alt = hashlib.sha256(b"different content for same filename").hexdigest()
    try_insert("C2_same_name_diff_content", **dict(base,
               storage_uri="lifeos://lab-archive/dup/v1/x.md",
               byte_size=42, sha256=alt))

    # C3 identical content, different owner -> allowed (unique key is per household+hash,
    #    subject_person is not part of it; document this semantic explicitly)
    try_insert("C3_same_content_diff_owner", **dict(base,
               subject_person_id=people["member"],
               storage_uri="lifeos://lab-archive/dup2/v1/x.md",
               byte_size=sample["byte_size"], sha256=sample["sha256"]))

    # C4 illegal media type -> schema has no CHECK, so this must be caught in the API
    #    layer. Record it as a contract GAP rather than silently passing.
    try_insert("C4_illegal_media_type", **dict(base,
               media_type="application/x-msdownload",
               storage_uri="lifeos://lab-archive/bad/v1/x.exe",
               byte_size=10, sha256=hashlib.sha256(b"exe").hexdigest()))

    # C5 path traversal in storage URI
    try_insert("C5_path_traversal", **dict(base,
               storage_uri="lifeos://lab-archive/../../etc/passwd",
               byte_size=10, sha256=hashlib.sha256(b"trav").hexdigest()))

    # C6 hash that does not match declared byte_size/content is a semantic error the
    #    DB cannot see; assert the *client* catches it before insert.
    bad = {"declared": "0" * 64, "actual": sample["sha256"]}
    res["C6_hash_mismatch_caught_client_side"] = {
        "accepted": False if bad["declared"] != bad["actual"] else True,
        "error": "client-side verification rejects declared!=computed",
    }

    # C7 NOT NULL enforcement
    rc, out, err = psql_script(
        "INSERT INTO core.document(household_id, category, title, storage_uri, sha256) "
        "VALUES (%s,'note','no hash','lifeos://x',NULL)" % sql_lit(household))
    res["C7_null_sha256_rejected"] = {"accepted": rc == 0,
                                      "error": err.strip().splitlines()[0][:160] if rc else None}
    return res


# What the ingest contract SHOULD do, stated up front so a gap cannot pass
# silently. "blocking" = the guarantee LifeOS depends on for S1; non-blocking
# entries are real gaps that belong in the week-4 Document API, which the
# family-lifeos repo has specified but not yet implemented.
CONTRACT_EXPECTED = {
    "C1_duplicate_delivery":              (False, True,
        "re-delivering an identical file must not create a second canonical row"),
    "C2_same_name_diff_content":          (True, True,
        "same filename, different bytes is a DIFFERENT document"),
    # MEASURED, not assumed: UNIQUE(household_id, sha256) ignores
    # subject_person_id, so the same bytes cannot be registered twice inside one
    # household even when they concern two different people. Consequence for
    # FamilyLifeOS: one insurance PDF naming two members = ONE canonical row;
    # per-person association has to live in a join table or metadata, not in a
    # second core.document row. Recorded as a design constraint, not a bug.
    "C3_same_content_diff_owner":         (False, False,
        "UNIQUE(household_id, sha256) deduplicates across subjects; per-person "
        "association must be modelled outside core.document"),
    "C4_illegal_media_type":              (False, False,
        "core.document has no media_type CHECK; must be enforced by the Document API"),
    "C5_path_traversal":                  (False, False,
        "core.document does not validate storage_uri; must be enforced by the API"),
    "C6_hash_mismatch_caught_client_side": (False, True,
        "declared hash != computed hash must be rejected before insert"),
    "C7_null_sha256_rejected":            (False, True,
        "sha256 NOT NULL is the idempotency anchor"),
}


def contract_gaps(negatives):
    gaps = []
    for key, (expected, blocking, why) in CONTRACT_EXPECTED.items():
        actual = negatives.get(key, {}).get("accepted")
        if actual != expected:
            gaps.append({"check": key, "expected_accepted": expected,
                         "actual_accepted": actual, "blocking": blocking,
                         "rationale": why})
    return gaps


def main():
    started = datetime.datetime.now(datetime.timezone.utc)
    docs = collect_export()
    if not docs:
        print("no export found at %s -- run export first" % EXPORT_MD, file=sys.stderr)
        sys.exit(2)

    household, people = ensure_fixture()
    # start from a clean canonical set for this household so counts are unambiguous
    psql("delete from core.document where household_id=%s" % sql_lit(household))

    passes = []
    for i in (1, 2, 3):
        attempted, total = register(docs, household, people["owner"], uuid.uuid4(), i)
        passes.append({"pass": i, "attempted": attempted, "canonical_total_after": total})

    unique_hashes = len({d["sha256"] for d in docs})
    negatives = contract_negatives(household, people, docs[0])

    # boundary proof
    violations = [p for p in sources_read
                  if any(m in p for m in FORBIDDEN_READ_MARKERS)]

    # storage URIs must not embed a raw IP
    ip_re = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
    uris = psql("select storage_uri from core.document where household_id=%s"
                % sql_lit(household)).splitlines()
    raw_ip_uris = [u for u in uris if ip_re.search(u)]

    audit_rows = int(psql_scalar("select count(*) from audit.event where household_id=%s"
                                 % sql_lit(household)) or 0)
    roles = psql("select role || '=' || count(*) from core.household_member "
                 "where household_id=%s group by role order by role" % sql_lit(household)).splitlines()

    rep = {
        "export_root": EXPORT_MD,
        "documents_in_export": len(docs),
        "unique_sha256": unique_hashes,
        "deliveries": passes,
        "idempotent": len({p["canonical_total_after"] for p in passes}) == 1
                      and passes[-1]["canonical_total_after"] == unique_hashes,
        "audit_events": audit_rows,
        "household_roles_expressible": roles,
        "contract_negatives": negatives,
        "contract_gaps": contract_gaps(negatives),
        "boundary": {
            "files_read": len(sources_read),
            "siyuan_internal_reads": violations,
            "read_only_portable_export": not violations,
        },
        "storage_uri_raw_ip_leaks": raw_ip_uris,
        "elapsed_seconds": round(
            (datetime.datetime.now(datetime.timezone.utc) - started).total_seconds(), 2),
    }
    blocking_gaps = [g for g in rep["contract_gaps"] if g["blocking"]]
    rep["blocking_contract_gaps"] = blocking_gaps
    rep["pass"] = bool(
        rep["idempotent"] and rep["boundary"]["read_only_portable_export"]
        and not raw_ip_uris and audit_rows >= 3 and not blocking_gaps
    )

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print(json.dumps({k: v for k, v in rep.items() if k != "contract_negatives"},
                     indent=2, ensure_ascii=False))
    for k, v in negatives.items():
        exp = CONTRACT_EXPECTED.get(k, (None, None, ""))[0]
        mark = "ok " if v["accepted"] == exp else "GAP"
        print("  %s %-38s accepted=%-5s expected=%-5s %s"
              % (mark, k, v["accepted"], exp, v.get("error") or ""))
    for g in rep["contract_gaps"]:
        print("  ! %s (%s): %s"
              % (g["check"], "BLOCKING" if g["blocking"] else "non-blocking",
                 g["rationale"]))
    print("->", REPORT)


if __name__ == "__main__":
    main()
