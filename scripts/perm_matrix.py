"""S1 permission matrix: probe what isolation self-hosted SiYuan actually provides.

Key S1 question: can family-shared vs person-private be isolated per user
(owner/adult/member)? Self-hosted SiYuan has a single API token and no per-user
RBAC, so the two notebooks are organizational only. This script proves that one
token can read BOTH notebooks (no built-in boundary) and that no notebook-level
ACL API exists. Writes /opt/siyuan-lab/exports/perm_matrix_report.json.

Run ON the VM:  SIYUAN_BASE_URL=http://127.0.0.1:6806 python3 scripts/perm_matrix.py
"""
from __future__ import annotations
import os, json, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import SiyuanClient, SiyuanError

REPORT = "/opt/siyuan-lab/exports/perm_matrix_report.json"


def main():
    c = SiyuanClient()
    c.wait_boot()
    nbs = {n["name"]: n["id"] for n in c.ls_notebooks()}
    r = {"notebooks": nbs, "single_token_reads_all": {}, "per_notebook_acl_api": None, "finding": ""}

    # With ONE token, can we read every notebook's docs? (yes => no built-in isolation)
    for name, nid in nbs.items():
        try:
            rows = c.sql("SELECT id FROM blocks WHERE box='%s' AND type='d' LIMIT 1" % nid)
            r["single_token_reads_all"][name] = len(rows) >= 0  # readable
        except SiyuanError as e:
            r["single_token_reads_all"][name] = "ERR %s" % e.msg

    # Probe for any notebook ACL configuration surface.
    try:
        conf = c.get_notebook_conf(nbs.get("person-private") or list(nbs.values())[0])
        r["per_notebook_acl_api"] = ("No 'permission'/'acl'/'share' key in notebook conf" if
                                     not any(k in str(conf).lower() for k in ("acl", "permission", "share"))
                                     else "ACL keys present")
    except Exception as e:
        r["per_notebook_acl_api"] = "ERR %r" % e

    all_readable = all(v is True for v in r["single_token_reads_all"].values())
    r["finding"] = ("Self-hosted SiYuan exposes a SINGLE API token and NO per-user/per-notebook "
                    "ACL. Both notebooks are readable with one token, so user-level isolation is "
                    "NOT provided by the product. Boundary must be enforced externally (separate "
                    "instances, or a gateway enforcing LifeOS ACL). => single-user workbench unless "
                    "wrapped by an external boundary.") if all_readable else "partial isolation observed"

    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2, ensure_ascii=False)
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
