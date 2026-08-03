"""Hard gate 4: deletion / retraction must propagate.

  "删除/撤回能传播；不会留下用户不可见但 AI 仍可检索的副本。"

This is the gate nobody notices until it fails: a user deletes a note, the note
disappears from the UI, and a stale copy keeps answering RAG queries forever.

The test deletes a real document in SiYuan and then chases the deletion through
every layer that could retain it:

  L1  SiYuan block index   /api/query/sql must stop returning the doc
  L2  SiYuan filesystem    the .sy file must be gone from workspace/data
  L3  portable export      re-export must no longer emit the .md
  L4  LifeOS canonical     reconciliation must mark the row withdrawn
  L5  orphan sweep         no asset referenced *only* by the deleted doc may
                           remain reachable in the export handed to RAG

L4 exposes a real schema gap: core.document (migration 0002) has no status /
version / supersedes column, so withdrawal has to be expressed in metadata.
That gap is reported rather than papered over -- week 4 step 3 lists status as a
required canonical field.

Run ON the VM:  python3 scripts/retraction_test.py
"""
from __future__ import annotations
import os, sys, json, time, subprocess, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import SiyuanClient  # noqa: E402

BASE = "/opt/siyuan-lab"
EXPORT_MD = os.path.join(BASE, "exports", "markdown")
SEED_MAP = os.path.join(BASE, "exports", "seed_map.json")
REPORT = os.path.join(BASE, "exports", "retraction_report.json")
CT = "lifeos-pg"
HOUSEHOLD_NAME = "s1-lab-household"


def psql(sql):
    out = subprocess.run(
        ["docker", "exec", "-i", CT, "psql", "-At", "-U", "lifeos", "-d", "lifeos", "-c", sql],
        capture_output=True, timeout=120)
    return out.returncode, out.stdout.decode("utf-8", "replace").strip(), \
        out.stderr.decode("utf-8", "replace")


def lit(s):
    return "'" + str(s).replace("'", "''") + "'"


def main():
    c = SiyuanClient()
    c.wait_boot()
    seed = json.load(open(SEED_MAP, encoding="utf-8"))

    # choose a corpus doc that owns an attachment, so the orphan sweep is meaningful
    target = None
    for d in seed["docs"]:
        if d["key"] == "c10":          # medical-report.pdf
            target = d
            break
    target = target or seed["docs"][0]

    rep = {"target": target, "layers": {}}

    # ---- capture pre-state ----
    pre_rows = c.sql("SELECT id FROM blocks WHERE root_id='%s' LIMIT 1" % target["id"])
    exp_rel = os.path.join(target["notebook"], target["hpath"].lstrip("/") + ".md")
    exp_path = os.path.join(EXPORT_MD, exp_rel)
    pre_export_exists = os.path.exists(exp_path)
    pre_sha = None
    if pre_export_exists:
        pre_sha = hashlib.sha256(open(exp_path, "rb").read()).hexdigest()

    rc, canon_before, _ = psql(
        "select count(*) from core.document d join core.household h on h.id=d.household_id "
        "where h.name=%s and d.sha256=%s" % (lit(HOUSEHOLD_NAME), lit(pre_sha or "")))
    rep["pre_state"] = {
        "indexed_in_siyuan": bool(pre_rows),
        "present_in_export": pre_export_exists,
        "export_sha256": pre_sha,
        "canonical_rows": canon_before,
    }

    # ---- perform the deletion the way a family member would ----
    t0 = time.time()
    try:
        c._post("/api/filetree/removeDocByID", {"id": target["id"]})
        removed_via = "removeDocByID"
    except Exception:  # noqa: BLE001
        c._post("/api/filetree/removeDoc",
                {"notebook": seed["notebooks"][target["notebook"]],
                 "path": "/" + target["id"] + ".sy"})
        removed_via = "removeDoc"
    time.sleep(6)   # let the kernel reindex
    rep["deleted_via"] = removed_via
    rep["delete_seconds"] = round(time.time() - t0, 2)

    # ---- L1 block index ----
    post_rows = c.sql("SELECT id FROM blocks WHERE root_id='%s' LIMIT 1" % target["id"])
    rep["layers"]["L1_siyuan_index"] = {
        "still_returns_doc": bool(post_rows), "pass": not post_rows}

    # ---- L2 filesystem ----
    hits = []
    for root, _d, files in os.walk(os.path.join(BASE, "workspace", "data")):
        for fn in files:
            if fn.startswith(target["id"]):
                hits.append(os.path.join(root, fn).replace(BASE, ""))
    rep["layers"]["L2_siyuan_filesystem"] = {"residual_files": hits, "pass": not hits}

    # ---- L3 portable export ----
    # Re-export into a SEPARATE report file. The first version let this run
    # overwrite exports/export_report.json, so the scorer read a post-deletion
    # export as the export stage's evidence and marked V1 as 29/30 data loss
    # when nothing had actually been lost.
    env = dict(os.environ)
    env["EXPORT_REPORT"] = os.path.join(BASE, "exports", "export_report_post_retraction.json")
    ex = subprocess.run([sys.executable, os.path.join(BASE, "scripts", "export_md.py")],
                        capture_output=True, timeout=600, env=env)
    post_export_exists = os.path.exists(exp_path)
    post_export_size = os.path.getsize(exp_path) if post_export_exists else None
    rep["layers"]["L3_portable_export"] = {
        "still_exported": post_export_exists,
        "residual_bytes": post_export_size,
        "reexport_rc": ex.returncode,
        "report": env["EXPORT_REPORT"],
        "pass": not post_export_exists}

    # ---- L4 LifeOS canonical reconciliation ----
    # rebuild the set of hashes still present in the export, then withdraw anything
    # canonical that the export no longer vouches for.
    # is there a first-class status column? (migration 0006 adds it)
    rc3, cols, _e = psql(
        "select column_name from information_schema.columns "
        "where table_schema='core' and table_name='document'")
    schema_gap = "status" not in cols.split()

    live = set()
    for root, _d, files in os.walk(EXPORT_MD):
        for fn in files:
            p = os.path.join(root, fn)
            live.add(hashlib.sha256(open(p, "rb").read()).hexdigest())
    hh_rc, hh, _ = psql("select id from core.household where name=%s" % lit(HOUSEHOLD_NAME))
    withdrawn = 0
    if hh:
        rc, out, err = psql(
            "select sha256 from core.document where household_id=%s" % lit(hh))
        canon = [h for h in out.splitlines() if h.strip()]
        gone = [h for h in canon if h not in live]
        for h in gone:
            if schema_gap:
                # legacy path: no status column, express in metadata jsonb
                rc2, _o, _e = psql(
                    "update core.document set metadata = metadata || "
                    "jsonb_build_object('status','withdrawn','withdrawn_at', now()::text) "
                    "where household_id=%s and sha256=%s" % (lit(hh), lit(h)))
            else:
                # first-class lifecycle column (migration 0006): status is now
                # constrained and queryable, not a free-form jsonb flag
                rc2, _o, _e = psql(
                    "update core.document set status='withdrawn', version=version, "
                    "metadata = metadata || jsonb_build_object('withdrawn_at', now()::text) "
                    "where household_id=%s and sha256=%s" % (lit(hh), lit(h)))
            if rc2 == 0:
                withdrawn += 1
            psql("insert into audit.event(actor_type, action, object_type, household_id, outcome, details) "
                 "values ('service','withdraw','document',%s,'success',"
                 "jsonb_build_object('sha256',%s,'reason','absent from portable export'))"
                 % (lit(hh), lit(h)))
        rep["layers"]["L4_lifeos_canonical"] = {
            "canonical_rows": len(canon),
            "absent_from_export": len(gone),
            "withdrawn": withdrawn,
            "status_column_exists": not schema_gap,
            "expressed_in": "metadata->>'status'" if schema_gap else "core.document.status",
            "pass": withdrawn == len(gone),
        }
    else:
        rep["layers"]["L4_lifeos_canonical"] = {
            "pass": False, "error": "household fixture missing; run lifeos_handoff first"}

    # ---- L5 orphan sweep: assets reachable but no longer referenced ----
    referenced = set()
    for root, _d, files in os.walk(EXPORT_MD):
        for fn in files:
            if fn.endswith(".md"):
                txt = open(os.path.join(root, fn), encoding="utf-8", errors="ignore").read()
                for tok in txt.replace("(", " ").replace(")", " ").split():
                    if "assets/" in tok:
                        referenced.add(os.path.basename(tok.strip("<>\"'")))
    asset_dir = os.path.join(EXPORT_MD, "assets")
    on_disk = set(os.listdir(asset_dir)) if os.path.isdir(asset_dir) else set()
    orphans = sorted(on_disk - referenced)
    rep["layers"]["L5_orphan_assets"] = {
        "assets_on_disk": len(on_disk), "referenced": len(referenced),
        "orphans": orphans[:20], "orphan_count": len(orphans),
        # orphans in the export are what RAG would still ingest
        "pass": len(orphans) == 0,
    }

    rep["hard_gate_4_pass"] = all(v.get("pass") for v in rep["layers"].values())
    rep["notes"] = []
    if schema_gap:
        rep["notes"].append(
            "core.document has no status/version/supersedes column; week-4 step 3 "
            "lists status as required. Withdrawal is currently only expressible in "
            "metadata jsonb, which no constraint can enforce.")
    if rep["layers"]["L5_orphan_assets"]["orphan_count"]:
        rep["notes"].append(
            "Deleting a note leaves its attachment in the export tree. SiYuan does "
            "not garbage-collect assets on doc delete; the export step must sweep "
            "unreferenced assets before handing anything to RAG.")

    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print(json.dumps(rep, indent=2, ensure_ascii=False)[:3000])
    print("->", REPORT)


if __name__ == "__main__":
    main()
