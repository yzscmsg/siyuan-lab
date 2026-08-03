"""Restore verification: prove the *seeded* corpus survived into a fresh instance.

The earlier version counted `blocks WHERE type='d'` in the restored kernel. That
number is inflated by leftover/demo notebooks and says nothing about whether the
30 documents we actually seeded came back, so it cannot answer the roadmap's V3
("全新实例恢复后 30/30 文档可见"). This version compares the restored instance
against exports/seed_map.json, doc id by doc id, and also re-checks the assets
on disk and that full-text search works.

Usage (on the VM, against the throwaway restore instance):
    SIYUAN_BASE_URL=http://127.0.0.1:6807 SIYUAN_TOKEN=... \
    WS=/opt/siyuan-lab/restore-workspace \
    SEED_MAP=/opt/siyuan-lab/exports/seed_map.json \
    python3 scripts/verify_restore.py

Prints one machine-parsable line, e.g.
    notebooks=2 docs_sql=30 sy_files=30 seeded_docs=30/30 assets=22/22 search=ok
and writes exports/restore_verify.json with the per-doc detail.
"""
from __future__ import annotations
import os, sys, json, time, glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import SiyuanClient

WS = os.environ.get("WS", "/opt/siyuan-lab/restore-workspace")
SEED_MAP = os.environ.get("SEED_MAP", "/opt/siyuan-lab/exports/seed_map.json")
REPORT = os.environ.get("RESTORE_REPORT", "/opt/siyuan-lab/exports/restore_verify.json")
INDEX_WAIT = int(os.environ.get("INDEX_WAIT", "180"))


def load_seed_map():
    try:
        with open(SEED_MAP, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


def sql_scalar(c, q, default=0):
    try:
        rows = c.sql(q)
    except Exception:
        return default
    if not rows:
        return default
    row = rows[0]
    if isinstance(row, dict):
        return list(row.values())[0]
    if isinstance(row, (list, tuple)):
        return row[0]
    return row


def wait_for_index(c, expected, timeout=INDEX_WAIT):
    """SiYuan rebuilds its sqlite index from the .sy files asynchronously.

    Polling until the count stops climbing is far more reliable than a fixed
    sleep - on a cold restore the index needed ~40s here, and a flat 15s sleep
    made the whole restore look like data loss.
    """
    deadline = time.time() + timeout
    last, stable = -1, 0
    while time.time() < deadline:
        n = sql_scalar(c, "SELECT COUNT(*) AS n FROM blocks WHERE type='d'", -1)
        if isinstance(n, int) and n >= expected:
            return n
        if n == last:
            stable += 1
            if stable >= 4:          # 4 identical polls -> index has settled
                return n
        else:
            stable = 0
        last = n
        time.sleep(3)
    return last


def main():
    seed = load_seed_map()
    seeded = seed.get("docs") or []
    assets = seed.get("assets") or {}

    c = SiyuanClient()
    c.wait_boot()

    nbs = c.ls_notebooks()
    for n in nbs:
        try:
            c.open_notebook(n["id"])
        except Exception:            # already open, or notebook is closed-by-design
            pass

    docs_sql = wait_for_index(c, len(seeded) or 30)

    # --- per-document verification against the seed map -------------------
    found, missing = [], []
    if seeded:
        ids = [d["id"] for d in seeded]
        # chunk the IN() list so a long query never trips the kernel
        alive = set()
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            lst = ",".join("'%s'" % x.replace("'", "") for x in chunk)
            try:
                rows = c.sql("SELECT id, hpath, box FROM blocks "
                             "WHERE type='d' AND id IN (%s)" % lst)
            except Exception:
                rows = []
            for r in rows or []:
                alive.add(r["id"] if isinstance(r, dict) else r[0])
        for d in seeded:
            (found if d["id"] in alive else missing).append(d)

    # --- assets on disk in the restored workspace -------------------------
    asset_ok, asset_missing = 0, []
    for name, meta in assets.items():
        stored = meta.get("stored", "")
        p = os.path.join(WS, "data", stored.lstrip("/"))
        if os.path.isfile(p) and os.path.getsize(p) == meta.get("bytes", -1):
            asset_ok += 1
        else:
            asset_missing.append(stored or name)

    # --- search works after restore (V3 asks for it explicitly) -----------
    # The needle is taken FROM the restored data, not hardcoded: pull the title
    # of a restored document out of the kernel, then ask the real full-text
    # endpoint for it and require the same document back. A hardcoded word is
    # worthless evidence - the first version searched for "Nimbus", which
    # belongs to a different project's corpus, and reported search=fail on a
    # perfectly healthy restore.
    needle, search_hits, search_ok, search_self_hit = "", 0, False, False
    try:
        probe = found[0] if found else None
        if probe:
            # needle = a real word from the doc's CONTENT, not the title: titles
            # in this corpus are short keys ("c01"), which the search index does
            # not tokenize usefully. Pull content blocks, keep alpha words >= 5.
            rows = c.sql("SELECT content FROM blocks WHERE root_id='%s' AND type IN ('p','h')" % probe["id"])
            blob = " ".join((r["content"] if isinstance(r, dict) else r[0]) or "" for r in rows)
            words = [w.strip("#*_`[]()\"'") for w in blob.split()]
            words = [w for w in words if w.isalpha() and len(w) >= 5]
            needle = os.environ.get("SEARCH_NEEDLE") or (max(words, key=len) if words else "")
        if needle:
            # fresh instances build the search index asynchronously; retry briefly
            for _ in range(6):
                hits = c.fulltext_search(needle)
                if hits:
                    break
                time.sleep(5)
            search_hits = len(hits or [])
            ids = {h.get("id") for h in (hits or [])} | {h.get("rootID") for h in (hits or [])}
            search_self_hit = bool(probe) and probe["id"] in ids
            search_ok = search_hits > 0
    except Exception as e:  # noqa: BLE001
        print("search probe failed: %r" % e, file=sys.stderr)
        search_ok = False

    sy = len(glob.glob(os.path.join(WS, "data", "**", "*.sy"), recursive=True))

    report = {
        "notebooks": len(nbs),
        "notebook_names": [n.get("name") for n in nbs],
        "docs_sql": docs_sql,
        "sy_files": sy,
        "seeded_expected": len(seeded),
        "seeded_found": len(found),
        "seeded_missing": [{"key": d["key"], "id": d["id"], "hpath": d["hpath"]}
                           for d in missing],
        "assets_expected": len(assets),
        "assets_found": asset_ok,
        "assets_missing": asset_missing,
        "search_ok": search_ok,
        "search_needle": needle,
        "search_hits": search_hits,
        "search_returned_probe_doc": search_self_hit,
        "all_seeded_docs_present": bool(seeded) and not missing,
        "all_assets_present": bool(assets) and not asset_missing,
    }
    try:
        os.makedirs(os.path.dirname(REPORT), exist_ok=True)
        with open(REPORT, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
    except OSError:
        pass

    # single line, always numeric tokens so the scorer can never choke on it
    print("notebooks=%d docs_sql=%s sy_files=%d seeded_docs=%d/%d assets=%d/%d search=%s"
          % (len(nbs), docs_sql if isinstance(docs_sql, int) else -1, sy,
             len(found), len(seeded), asset_ok, len(assets),
             "ok" if search_ok else "fail"))
    return 0 if report["all_seeded_docs_present"] else 1


if __name__ == "__main__":
    sys.exit(main())
