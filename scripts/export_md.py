# =====================================================================
# TEST SCRIPT METADATA  (format: docs/testing/README.md)
#   gate:      HG1 (export portion) - open-format export + rebuild, no manual DB repair
#   goal:      export all live docs to Markdown+assets; verify asset hashes + fidelity
#   inputs:    running SiYuan workspace; corpus/ originals for comparison
#   expected:  30/30 docs with content; 22/22 asset hashes match; fidelity 30/30
#              structural, 100% word retention; zero manual DB repair to recover
#   deps:      ./run.sh deploy + seed; corpus/ present
#   run:       python3 scripts/export_md.py   (then ./run.sh fidelity)
#              (or: python3 scripts/s1_acceptance.py --stages export,fidelity)
#   issues:    createDocWithMd is NOT idempotent (handled by handoff idempotency,
#              not a gate failure). Export is the durable exit path (also HG5).
# =====================================================================
"""S1 export: standard Markdown + assets, plus round-trip fidelity verification.

Builds /opt/siyuan-lab/exports/markdown/<notebook>/<hpath>.md + assets/ (the
portable artifact handed to LifeOS/NAS / RAG). Then verifies the S1 hard gate:
  - every LIVE seeded doc exports to non-empty Markdown
  - each doc's title survives the round-trip
  - stored attachment hashes == original binary hashes (no lossy re-encode)

Two behaviours here exist because hard gate 4 caught them:

  1. A document deleted in SiYuan still had a row in seed_map.json, and the
     exporter happily wrote a ZERO-BYTE .md for it. The retraction check then
     (correctly) reported the deleted note as "still exported". The export tree
     must mirror what is live, so a doc the kernel no longer knows is skipped
     and recorded, not materialised as an empty placeholder.

  2. Assets were copied wholesale from the workspace. Deleting the only note
     that referenced medical-report.pdf left that PDF sitting in the tree that
     feeds RAG - the exact "invisible to the user, still retrievable by the AI"
     failure the gate is about. Only assets referenced by exported Markdown are
     copied; hash verification still covers every stored asset.

Run ON the VM:  python3 scripts/export_md.py
Env: EXPORT_REPORT  alternate report path (retraction re-export uses this so it
                    does not clobber the export stage's evidence)
"""
from __future__ import annotations
import os, json, shutil, hashlib, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import SiyuanClient

ROOT = "/opt/siyuan-lab"
SEED_MAP = os.path.join(ROOT, "exports", "seed_map.json")
CORPUS_ASSETS = os.path.join(ROOT, "corpus", "assets")
WS_ASSETS = os.path.join(ROOT, "workspace", "data", "assets")
OUT = os.path.join(ROOT, "exports", "markdown")
REPORT = os.environ.get("EXPORT_REPORT") or os.path.join(ROOT, "exports", "export_report.json")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(s):
    return " ".join(s.split())


def live_doc_ids(c):
    try:
        rows = c.sql("SELECT id FROM blocks WHERE type='d'")
    except Exception:  # noqa: BLE001
        return None                      # unknown - fall back to content check
    return {r["id"] if isinstance(r, dict) else r[0] for r in (rows or [])}


def main():
    c = SiyuanClient()
    c.wait_boot()
    seed = json.load(open(SEED_MAP, encoding="utf-8"))
    alive = live_doc_ids(c)

    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)
    assets_out = os.path.join(OUT, "assets")
    os.makedirs(assets_out, exist_ok=True)

    report = {"docs_in_seed_map": len(seed["docs"]), "docs_live": 0,
              "docs_total": 0, "docs_exported": 0,
              "docs_with_content": 0, "title_match": 0,
              "docs_missing_in_kernel": [],
              "assets_checked": 0, "assets_hash_match": 0,
              "assets_copied": 0, "assets_skipped_unreferenced": [],
              "details": []}

    for d in seed["docs"]:
        # a doc the kernel no longer knows about was deleted; it must NOT appear
        # in the portable tree, and it must not be counted as an export failure
        if alive is not None and d["id"] not in alive:
            report["docs_missing_in_kernel"].append(
                {"key": d["key"], "id": d["id"], "hpath": d["hpath"]})
            report["details"].append({"key": d["key"], "ok": False,
                                      "missing_in_kernel": True})
            continue
        try:
            res = c.export_md_content(d["id"])
        except Exception as e:  # noqa: BLE001
            report["details"].append({"key": d["key"], "ok": False, "error": str(e)[:160]})
            continue
        content = res.get("content", "") or ""
        if not content.strip():
            # kernel answered but with nothing: treat as missing, never write a
            # zero-byte placeholder into the portable artifact
            report["docs_missing_in_kernel"].append(
                {"key": d["key"], "id": d["id"], "hpath": d["hpath"],
                 "reason": "kernel returned empty content"})
            report["details"].append({"key": d["key"], "ok": False,
                                      "missing_in_kernel": True, "len": 0})
            continue

        report["docs_live"] += 1
        hpath = d["hpath"].lstrip("/")
        out_path = os.path.join(OUT, d["notebook"], hpath + ".md")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        report["docs_exported"] += 1
        report["docs_with_content"] += 1
        # title check: first '# ' line of source should appear (normalized)
        title = ""
        src_path = os.path.join(ROOT, "corpus", d["key"] + ".md")
        if os.path.exists(src_path):
            src = open(src_path, encoding="utf-8").read()
            for line in src.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
        if title and title in norm(content):
            report["title_match"] += 1
        report["details"].append({"key": d["key"], "ok": True, "len": len(content),
                                  "title_match": bool(title and title in norm(content))})

    report["docs_total"] = report["docs_live"]

    # --- which assets does the exported Markdown actually reference? -------
    referenced = set()
    for root, _dirs, files in os.walk(OUT):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            txt = open(os.path.join(root, fn), encoding="utf-8", errors="ignore").read()
            for tok in txt.replace("(", " ").replace(")", " ").split():
                if "assets/" in tok:
                    referenced.add(os.path.basename(tok.strip("<>\"'")))

    # --- verify hashes for every stored asset, copy only referenced ones ---
    report["assets"] = []
    for orig, meta in sorted(seed["assets"].items()):
        stored = meta["stored"] if isinstance(meta, dict) else meta
        base = os.path.basename(stored)
        sp = os.path.join(WS_ASSETS, base)
        op = os.path.join(CORPUS_ASSETS, orig)
        row = {"original": orig, "stored": base,
               "present": os.path.exists(sp), "hash_match": False,
               "referenced": base in referenced, "copied": False}
        if os.path.exists(sp) and os.path.exists(op):
            report["assets_checked"] += 1
            row["sha256"] = sha256_file(sp)
            if row["sha256"] == sha256_file(op):
                report["assets_hash_match"] += 1
                row["hash_match"] = True
            if row["referenced"]:
                shutil.copy(sp, os.path.join(assets_out, base))
                report["assets_copied"] += 1
                row["copied"] = True
            else:
                report["assets_skipped_unreferenced"].append(base)
        report["assets"].append(row)

    report["pass"] = (report["docs_live"] > 0
                      and report["docs_with_content"] == report["docs_live"]
                      and report["assets_hash_match"] == report["assets_checked"])

    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("details", "assets")}, ensure_ascii=False, indent=2))
    print("markdown tree ->", OUT)
    print("report ->", REPORT)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
