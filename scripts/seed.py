"""S1 seed: import the 20-doc corpus + create 10 native notes in SiYuan via API.

Creates the two experiment notebooks (family-shared, person-private), uploads the
two binary assets, rewrites asset links to the names SiYuan actually stores, then
creates every doc. Writes /opt/siyuan-lab/exports/seed_map.json so later stages
(export, backup/restore, scorecard) can verify by doc id.

Run ON the VM:  SIYUAN_BASE_URL=http://127.0.0.1:6806 python3 scripts/seed.py
"""
from __future__ import annotations
import os, json, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import SiyuanClient

CORPUS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "corpus")
EXPORTS = "/opt/siyuan-lab/exports"
MAP_PATH = os.path.join(EXPORTS, "seed_map.json")

ASSET_DIR = os.path.join(CORPUS, "assets")
EXPERIMENT_NOTEBOOKS = ("family-shared", "person-private")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--reset", action="store_true",
        help="delete the experiment notebooks first. createDocWithMd is NOT "
             "idempotent (recorded defect D1: same hpath -> duplicate doc), so a "
             "re-seed without --reset doubles the corpus.")
    args = ap.parse_args()

    c = SiyuanClient()
    c.wait_boot()
    os.makedirs(EXPORTS, exist_ok=True)

    if args.reset:
        for nb in c.ls_notebooks():
            if nb["name"] in EXPERIMENT_NOTEBOOKS:
                try:
                    c.remove_notebook(nb["id"])
                    print("reset: removed notebook %s (%s)" % (nb["name"], nb["id"]))
                except Exception as e:  # noqa: BLE001
                    print("reset: could not remove %s: %s" % (nb["name"], e))

    # --- notebooks ---
    existing = {n["name"]: n["id"] for n in c.ls_notebooks()}
    shared_id = existing.get("family-shared") or c.create_notebook("family-shared")["id"]
    private_id = existing.get("person-private") or c.create_notebook("person-private")["id"]
    c.open_notebook(shared_id)
    c.open_notebook(private_id)
    print("notebooks: family-shared=%s person-private=%s" % (shared_id, private_id))

    # --- upload every corpus attachment, remember the name SiYuan assigns ---
    repl = {}
    asset_map = {}
    for name in sorted(os.listdir(ASSET_DIR)):
        blob = open(os.path.join(ASSET_DIR, name), "rb").read()
        stored = c.upload_asset(name, blob)["succMap"][name]
        repl["assets/" + name] = stored
        asset_map[name] = {"stored": stored, "bytes": len(blob)}
    print("uploaded %d assets" % len(asset_map))

    seed_map = {"notebooks": {"family-shared": shared_id, "person-private": private_id},
                "assets": asset_map,
                "docs": []}

    # --- import 20 corpus docs into family-shared ---
    for i in range(1, 21):
        key = "c%02d" % i
        path = os.path.join(CORPUS, key + ".md")
        md = open(path, encoding="utf-8").read()
        for a, b in repl.items():
            md = md.replace(a, b)
        did = c.create_doc_with_md(shared_id, "/corpus/" + key, md)
        seed_map["docs"].append({"key": key, "id": did, "notebook": "family-shared",
                                 "kind": "corpus", "hpath": "/corpus/" + key})

    # --- create 10 native notes (split across the two notebooks) ---
    for i in range(1, 11):
        key = "n%02d" % i
        path = os.path.join(CORPUS, key + ".md")
        md = open(path, encoding="utf-8").read()
        for a, b in repl.items():
            md = md.replace(a, b)
        nb = "family-shared" if i <= 5 else "person-private"
        nb_id = shared_id if nb == "family-shared" else private_id
        did = c.create_doc_with_md(nb_id, "/native/" + key, md)
        seed_map["docs"].append({"key": key, "id": did, "notebook": nb,
                                 "kind": "native", "hpath": "/native/" + key})

    with open(MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(seed_map, f, indent=2, ensure_ascii=False)
    print("seeded %d docs, %d assets -> %s"
          % (len(seed_map["docs"]), len(asset_map), MAP_PATH))

    # the roadmap's population: 20 imported + 10 native, >=20 attachments
    live = c.sql("SELECT COUNT(*) AS n FROM blocks WHERE type='d'")
    print("kernel doc-block count: %s" % (live[0]["n"] if live else "?"))
    if len(seed_map["docs"]) != 30 or len(asset_map) < 20:
        print("WARN: expected 30 docs and >=20 assets")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
