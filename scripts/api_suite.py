"""S1 API suite: create/read/update/export 5 docs, idempotency, error model.

Exercises the HTTP API the way LifeOS/n8n would: token auth, markdown create,
block update, markdown export. Records an error model (what SiYuan returns for
no-token / bad-notebook / duplicate-path) and two structural probes that matter
for an automation client:

  * idempotency of createDocWithMd on a repeated hpath        (defect D1)
  * whether a nested hpath silently materialises parent docs  (defect D7)

The scratch notebook is removed at the end. The first version left one behind on
every run - five orphaned "api-suite" notebooks with 32 doc blocks had piled up,
which is exactly the kind of noise that made raw doc counts useless as restore
evidence.

Run ON the VM:  python3 scripts/api_suite.py [--keep]
"""
from __future__ import annotations
import os, json, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import SiyuanClient, SiyuanError

REPORT = "/opt/siyuan-lab/exports/api_suite_report.json"
SCRATCH = "api-suite"


def doc_count(c, box):
    try:
        rows = c.sql("SELECT COUNT(*) AS n FROM blocks WHERE type='d' AND box='%s'" % box)
        return int(list(rows[0].values())[0]) if rows else 0
    except Exception:  # noqa: BLE001
        return -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true",
                    help="do not delete the scratch notebook (for manual inspection)")
    args = ap.parse_args()

    c = SiyuanClient()
    c.wait_boot()

    # --- clean up scratch notebooks left by earlier runs -------------------
    reclaimed = []
    for n in c.ls_notebooks():
        if n["name"] == SCRATCH:
            try:
                c.remove_notebook(n["id"])
                reclaimed.append(n["id"])
            except Exception as e:  # noqa: BLE001
                print("could not remove stale %s: %s" % (n["id"], e))
    if reclaimed:
        print("removed %d stale '%s' notebook(s)" % (len(reclaimed), SCRATCH))

    nb = c.create_notebook(SCRATCH)["id"]
    c.open_notebook(nb)
    r = {"scratch_notebook": nb, "stale_notebooks_reclaimed": reclaimed,
         "create": [], "read": {}, "update": {}, "export": {},
         "idempotency": {}, "hpath_parents": {}, "errors": {}}

    # create + read + update + export 5 docs
    for i in range(1, 6):
        path = "/doc%d" % i
        md = "# API Doc %d\n\nInitial paragraph for doc %d.\n" % (i, i)
        did = c.create_doc_with_md(nb, path, md)
        got = c.export_md_content(did)["content"]
        r["read"][did] = ("Initial paragraph for doc %d." % i) in got
        c.append_block(did, "Appended line %d via API." % i)
        got2 = c.export_md_content(did)["content"]
        r["update"][did] = ("Appended line %d via API." % i) in got2
        r["export"][did] = bool(got2.strip())
        r["create"].append(did)

    # --- D1: idempotency of a repeated hpath ------------------------------
    before = doc_count(c, nb)
    dup = c.create_doc_with_md(nb, "/doc1", "# API Doc 1\n\nInitial paragraph for doc 1.\n")
    after = doc_count(c, nb)
    r["idempotency"] = {
        "same_id_on_dup_path": dup == r["create"][0],
        "returned_id": dup,
        "original_id": r["create"][0],
        "doc_count_before": before,
        "doc_count_after": after,
        "duplicate_created": after > before,
        "note": "createDocWithMd is create-only. A repeated hpath yields a SECOND "
                "document with the same title, so any LifeOS/n8n writer must "
                "look up the id first and use updateBlock, or the retry of a "
                "failed webhook silently forks the note.",
    }

    # --- D7: does a nested hpath materialise parent documents? ------------
    p_before = doc_count(c, nb)
    child = c.create_doc_with_md(nb, "/deep/nested/leaf", "# Leaf\n\nbody\n")
    p_after = doc_count(c, nb)
    r["hpath_parents"] = {
        "child_id": child,
        "docs_created_for_3_level_path": p_after - p_before,
        "auto_parent_docs": max(0, (p_after - p_before) - 1),
        "note": "a 3-segment hpath creates the leaf plus one empty document per "
                "missing ancestor. Those placeholders are indistinguishable from "
                "real notes in an export, so the LifeOS ingester must skip "
                "zero-content documents or the canonical store gains phantoms.",
    }

    # --- error model ------------------------------------------------------
    bare = SiyuanClient(token="")
    try:
        bare.ls_notebooks()
        r["errors"]["no_token"] = "NO ERROR (unexpected)"
    except SiyuanError as e:
        r["errors"]["no_token"] = {"code": e.code, "msg": e.msg}
    except Exception as e:  # noqa: BLE001
        r["errors"]["no_token"] = "EXC %r" % e

    try:
        c.create_doc_with_md("99999999999999-zzzzzzz", "/x", "y")
        r["errors"]["bad_notebook"] = "NO ERROR (unexpected)"
    except SiyuanError as e:
        r["errors"]["bad_notebook"] = {"code": e.code, "msg": e.msg}

    # --- tear the scratch notebook down -----------------------------------
    if args.keep:
        r["cleanup"] = "kept on request"
    else:
        try:
            c.remove_notebook(nb)
            r["cleanup"] = "scratch notebook removed"
        except Exception as e:  # noqa: BLE001
            r["cleanup"] = "FAILED to remove scratch notebook: %s" % e

    ok = (all(r["read"].values()) and all(r["update"].values())
          and all(r["export"].values()) and len(r["create"]) == 5)
    r["pass"] = ok

    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2, ensure_ascii=False)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
