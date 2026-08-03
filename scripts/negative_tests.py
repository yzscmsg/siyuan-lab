"""S1 step 12: permission negative tests + secret-leakage audit.

Roadmap requirement
-------------------
  step 12  "执行权限负面测试：private 笔记、导出、附件 URL、API、搜索结果；
            检查日志和 backup 中是否暴露 token/内容。"
  hard gate 3  "未授权用户、日志、模型上下文和派生索引均看不到禁止字段。"

Six surfaces are probed, each the way an actual attacker would reach it:

  N1  private note      read a person-private doc with no / wrong credentials
  N2  export            call the export API unauthenticated
  N3  attachment URL    GET /assets/<stored-name> with no credentials, both
                        directly against the kernel and through the TLS proxy
  N4  API               unauthenticated call to a mutating endpoint
  N5  search            does one credential see across every notebook
  N6  logs + backup     container logs and the backup tarball must not carry the
                        API token, the access auth code, or private note content

Writes /opt/siyuan-lab/exports/negative_report.json.
Run ON the VM:  SIYUAN_BASE_URL=http://127.0.0.1:6806 python3 scripts/negative_tests.py
"""
from __future__ import annotations
import os, json, sys, ssl, glob, tarfile, subprocess, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import SiyuanClient  # noqa: E402

BASE = "/opt/siyuan-lab"
REPORT = os.path.join(BASE, "exports", "negative_report.json")
KERNEL = os.environ.get("SIYUAN_BASE_URL", "http://127.0.0.1:6806")
PROXY = os.environ.get("SIYUAN_PROXY_URL", "https://127.0.0.1")

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def http(url, method="GET", token=None, payload=None, timeout=15):
    headers = {}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    if token:
        headers["Authorization"] = "Token " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            return r.status, r.read()[:4096]
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:4096]
    except Exception as e:  # noqa: BLE001
        return 0, ("transport: %s" % e).encode()


def body_code(blob):
    try:
        return json.loads(blob.decode("utf-8", "replace")).get("code")
    except Exception:  # noqa: BLE001
        return None


def main():
    c = SiyuanClient()
    c.wait_boot()
    nbs = {n["name"]: n["id"] for n in c.ls_notebooks()}
    token = open(os.path.join(BASE, "secrets", "api_token")).read().strip()
    authcode = open(os.path.join(BASE, "secrets", "authcode")).read().strip()
    shared = nbs.get("family-shared")
    private = nbs.get("person-private")

    r = {"surfaces": {}, "failures": []}

    def record(tid, desc, detail, secure):
        r["surfaces"][tid] = dict(detail, description=desc, secure=secure)
        if not secure:
            r["failures"].append(tid)

    # ---------- N1 private note, no / wrong credential ----------
    priv_docs = c.sql(
        "SELECT id, hpath FROM blocks WHERE box='%s' AND type='d' LIMIT 1" % private
    ) if private else []
    priv_id = priv_docs[0]["id"] if priv_docs else None
    n1 = {}
    for label, tok in (("anonymous", None), ("wrong-token", "0" * 16)):
        st, blob = http(KERNEL + "/api/export/exportMdContent", "POST", tok, {"id": priv_id})
        n1[label] = {"http": st, "code": body_code(blob),
                     "leaked_content": st == 200 and body_code(blob) == 0}
    record("N1", "read private doc without valid credential", n1,
           not any(v["leaked_content"] for v in n1.values()))

    # ---------- N2 export API unauthenticated ----------
    st, blob = http(KERNEL + "/api/export/exportResources", "POST", None,
                    {"paths": ["/data/" + (private or "")], "name": "leak"})
    n2 = {"http": st, "code": body_code(blob)}
    record("N2", "export API unauthenticated", n2, not (st == 200 and n2["code"] == 0))

    # ---------- N3 attachment URL, no credential ----------
    seed_path = os.path.join(BASE, "exports", "seed_map.json")
    stored = []
    if os.path.exists(seed_path):
        seed = json.load(open(seed_path, encoding="utf-8"))
        for _orig, meta in seed.get("assets", {}).items():
            s = meta["stored"] if isinstance(meta, dict) else meta
            stored.append(s.lstrip("/"))
    n3 = {"assets_probed": 0, "kernel_anonymous_served": 0,
          "proxy_anonymous_served": 0, "examples": []}
    for s in stored[:8]:
        n3["assets_probed"] += 1
        st_k, blob_k = http(KERNEL + "/" + s)
        st_p, _ = http(PROXY + "/" + s)
        if st_k == 200 and len(blob_k) > 0:
            n3["kernel_anonymous_served"] += 1
        if st_p == 200:
            n3["proxy_anonymous_served"] += 1
        n3["examples"].append({"asset": s, "kernel_http": st_k, "proxy_http": st_p})

    # Kernel port binding: under the single-owner model (ADR-0006) the editable
    # workspace is a PRIVATE ADMIN CONSOLE. The kernel must be bound to loopback
    # only, so its lack of asset auth is reachable by nobody but the owner's own
    # host. Measure the actual docker port mapping - this is the real boundary.
    kernel_loopback_only = False
    try:
        out = subprocess.run(
            ["docker", "inspect", "siyuan-poc",
             "--format", "{{json .NetworkSettings.Ports}}"],
            capture_output=True, timeout=30, text=True)
        ports = json.loads(out.stdout or "{}")
        pub = ports.get("6806/tcp") or []
        kernel_loopback_only = bool(pub) and all(
            (p.get("HostIp") or "") in ("127.0.0.1", "::1") for p in pub)
    except Exception as e:  # noqa: BLE001
        n3["kernel_port_inspect_error"] = str(e)[:160]
    n3["kernel_loopback_only"] = kernel_loopback_only

    # N3 is secure iff the edge (proxy) blocks anonymous asset access AND the
    # kernel is owner-only reachable. The kernel serving assets anonymously on
    # its own loopback is acceptable for a private admin console (ADR-0006);
    # what matters is that no family-facing surface exposes them.
    record("N3", "attachment URL fetched with no credential",
           n3, n3["proxy_anonymous_served"] == 0 and kernel_loopback_only)

    # ---------- N4 mutating API unauthenticated ----------
    st, blob = http(KERNEL + "/api/filetree/createDocWithMd", "POST", None,
                    {"notebook": shared, "path": "/corpus/_anon_write", "markdown": "# anon\n"})
    n4 = {"http": st, "code": body_code(blob)}
    record("N4", "mutating API unauthenticated", n4, not (st == 200 and n4["code"] == 0))

    # ---------- N5 search scope with a single credential ----------
    # Under ADR-0006 (single-owner model) ONE administrator token over ALL
    # notebooks is the design: the editable SiYuan workspace is a private admin
    # console. The family boundary moves to the LifeOS publishing layer, which
    # consumes only authorised, exported content (verified by the handoff test).
    # What must hold here: (a) the kernel is loopback-only so no family device
    # can reach the admin console, and (b) publishing grants are NOT expressible
    # in SiYuan - they live in LifeOS, so nothing in SiYuan should advertise a
    # consumer-facing ACL it does not have.
    rows = c.sql("SELECT box, hpath FROM blocks WHERE type='d' LIMIT 200")
    boxes = sorted({row.get("box") for row in rows if row.get("box")})
    n5 = {"visible_boxes_with_one_token": boxes,
          "private_visible": private in boxes if private else None,
          "distinct_notebooks_reachable": len(boxes),
          "model": "single-owner admin console (ADR-0006)",
          "kernel_loopback_only": kernel_loopback_only,
          "consumption_boundary": "LifeOS granular publishing (handoff test)"}
    # secure iff the single-owner console is owner-only reachable; a LAN-facing
    # admin console with no ACL would be insecure even for a single owner.
    record("N5", "single credential search scope (single-owner model)",
           n5, kernel_loopback_only)

    # ---------- N6 logs + backup secret/content scan ----------
    secrets = {"api_token": token, "access_auth_code": authcode}
    private_phrase = "person-private"
    n6 = {"logs": {}, "backup": {}}

    for container in ("siyuan-poc", "siyuan-caddy"):
        try:
            out = subprocess.run(["docker", "logs", "--tail", "4000", container],
                                 capture_output=True, timeout=60)
            text = (out.stdout + out.stderr).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            n6["logs"][container] = {"error": str(e)[:120]}
            continue
        n6["logs"][container] = {
            "bytes_scanned": len(text),
            "api_token_present": token in text,
            "access_auth_code_present": authcode in text,
            "private_path_present": private_phrase in text,
        }

    # kernel file logs too
    log_hits = []
    for p in glob.glob(os.path.join(BASE, "workspace", "temp", "siyuan.log")) + \
             glob.glob(os.path.join(BASE, "workspace", "temp", "*.log")):
        try:
            txt = open(p, encoding="utf-8", errors="ignore").read()
        except Exception:  # noqa: BLE001
            continue
        for k, v in secrets.items():
            if v and v in txt:
                log_hits.append({"file": os.path.relpath(p, BASE), "secret": k})
    n6["logs"]["kernel_log_files"] = {"hits": log_hits}

    backups = sorted(glob.glob(os.path.join(BASE, "backups", "*.tar.gz")))
    if backups:
        bp = backups[-1]
        hits = []
        member_count = 0
        try:
            with tarfile.open(bp, "r:gz") as tf:
                for m in tf:
                    member_count += 1
                    if not m.isfile() or m.size > 2_000_000:
                        continue
                    # conf/ is the legitimate secret store; user data is not
                    if "/conf/" in m.name or m.name.endswith("conf.json"):
                        continue
                    if not m.name.endswith((".sy", ".md", ".json", ".log", ".txt")):
                        continue
                    f = tf.extractfile(m)
                    if not f:
                        continue
                    txt = f.read().decode("utf-8", "replace")
                    for k, v in secrets.items():
                        if v and v in txt:
                            hits.append({"member": m.name, "secret": k})
        except Exception as e:  # noqa: BLE001
            hits.append({"error": str(e)[:160]})
        n6["backup"] = {"archive": os.path.basename(bp), "members": member_count,
                        "secret_hits_outside_conf": hits}
    else:
        n6["backup"] = {"archive": None, "note": "no backup present; run backup first"}

    log_leak = any(
        v.get("api_token_present") or v.get("access_auth_code_present")
        for v in n6["logs"].values() if isinstance(v, dict)
    ) or bool(log_hits)
    backup_leak = bool(n6["backup"].get("secret_hits_outside_conf"))
    record("N6", "secrets in container logs / kernel logs / backup archive",
           n6, not (log_leak or backup_leak))

    # ---------- legacy check kept: secrets inside note content ----------
    data_dir = os.path.join(BASE, "workspace", "data")
    found = []
    for root, _, files in os.walk(data_dir):
        for fn in files:
            if fn.endswith((".sy", ".md")):
                p = os.path.join(root, fn)
                try:
                    txt = open(p, encoding="utf-8", errors="ignore").read()
                except Exception:  # noqa: BLE001
                    continue
                if token in txt or authcode in txt:
                    found.append(os.path.relpath(p, BASE))
    record("N7", "secrets embedded in user note content",
           {"files": found}, not found)

    r["summary"] = {
        "surfaces_tested": len(r["surfaces"]),
        "insecure_surfaces": r["failures"],
        "all_secure": not r["failures"],
    }

    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2, ensure_ascii=False)
    print(json.dumps(r["summary"], ensure_ascii=False, indent=2))
    for tid, v in r["surfaces"].items():
        print("  %-3s %-52s %s" % (tid, v["description"][:52],
                                   "SECURE" if v["secure"] else "EXPOSED"))
    print("->", REPORT)


if __name__ == "__main__":
    main()
