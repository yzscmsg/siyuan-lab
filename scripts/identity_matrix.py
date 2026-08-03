"""S1 step 3 + verify item: owner / adult / member identity and permission matrix.

Roadmap requirement
-------------------
  step 3   "创建两个测试空间：family-shared 和 person-private；创建 owner、adult、
            member 测试身份，记录实际可配置权限。"
  verify   "owner/adult/member 的正负权限矩阵全部通过；若产品无法提供所需隔离，
            结论只能是单人工作台或 reject。"

The verification clause explicitly allows the answer "the product cannot provide
the isolation". This script does not assume that answer -- it *attempts* to
create the three identities through every credential surface the kernel exposes,
records what is actually configurable, and only then runs the matrix with
whatever principals genuinely exist.

Principals attempted:
  owner   full API token from the secret store
  adult   a second, independently-issued API token (if the product can mint one)
  member  read-only / scoped principal (if the product can express scope)

Run ON the VM:
  SIYUAN_BASE_URL=http://127.0.0.1:6806 python3 scripts/identity_matrix.py
"""
from __future__ import annotations
import os, sys, json, ssl, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import SiyuanClient, SiyuanError  # noqa: E402

REPORT = "/opt/siyuan-lab/exports/identity_matrix_report.json"
BASE = os.environ.get("SIYUAN_BASE_URL", "http://127.0.0.1:6806")

# Endpoints that WOULD implement multi-identity if the product had it. Probing
# them is the evidence that it does not -- an unprobed absence proves nothing.
IDENTITY_ENDPOINTS = [
    "/api/system/getConf",
    "/api/system/getWorkspaces",
    "/api/account/login",
    "/api/account/checkActivationcode",
    "/api/setting/setAccount",
    "/api/user/createUser",
    "/api/user/listUsers",
    "/api/auth/createToken",
    "/api/auth/listTokens",
    "/api/token/create",
    "/api/system/setAccessAuthCode",
    "/api/system/setAPIToken",
    "/api/notebook/setNotebookConf",
]


def raw_post(endpoint, payload=None, token=None, timeout=20):
    """POST returning (http_status, code, msg) without raising."""
    url = BASE.rstrip("/") + endpoint
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = "Token " + token
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            body = r.read().decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        status = e.code
    except Exception as e:  # noqa: BLE001
        return (0, None, "transport: %s" % str(e)[:120])
    try:
        obj = json.loads(body)
    except json.JSONDecodeError:
        return (status, None, body[:120].replace("\n", " "))
    if isinstance(obj, list):
        return (status, 0, "list[%d]" % len(obj))
    return (status, obj.get("code"), str(obj.get("msg", ""))[:120])


def main():
    owner_token = SiyuanClient().token
    rep = {
        "principals_attempted": ["owner", "adult", "member"],
        "identity_surface_probe": {},
        "principals_created": {},
        "configurable_permissions": {},
        "matrix": [],
        "finding": "",
    }

    # ---------- 1. probe the identity surface ----------
    for ep in IDENTITY_ENDPOINTS:
        status, code, msg = raw_post(ep, {}, token=owner_token)
        rep["identity_surface_probe"][ep] = {
            "http": status, "code": code, "msg": msg,
            "exists": status != 404 and "not found" not in msg.lower(),
        }

    # ---------- 2. what is actually configurable ----------
    conf = None
    try:
        conf = SiyuanClient()._post("/api/system/getConf")
    except SiyuanError as e:
        rep["configurable_permissions"]["getConf_error"] = str(e)[:160]

    if conf:
        c = conf.get("conf", conf)
        acc = c.get("access", {}) if isinstance(c, dict) else {}
        api = c.get("api", {}) if isinstance(c, dict) else {}
        rep["configurable_permissions"] = {
            "top_level_conf_keys": sorted(c.keys())[:40] if isinstance(c, dict) else [],
            "has_users_collection": any(
                k in c for k in ("users", "accounts", "members", "roles")
            ) if isinstance(c, dict) else False,
            "access_keys": sorted(acc.keys()) if isinstance(acc, dict) else [],
            "api_keys": sorted(api.keys()) if isinstance(api, dict) else [],
            # the only two real knobs in self-hosted SiYuan
            "single_access_auth_code": "accessAuthCode" in json.dumps(c)[:200000],
            "single_api_token": "token" in api if isinstance(api, dict) else False,
        }

    # ---------- 3. attempt to create adult + member ----------
    # owner always exists (it is the token deploy.sh extracted)
    rep["principals_created"]["owner"] = {
        "created": True, "how": "kernel-issued single API token (conf.json api.token)",
        "scope": "global",
    }
    for role in ("adult", "member"):
        attempts = []
        for ep, payload in (
            ("/api/user/createUser", {"name": "s1-" + role, "role": role}),
            ("/api/auth/createToken", {"name": "s1-" + role, "scope": role}),
            ("/api/token/create", {"name": "s1-" + role}),
            ("/api/setting/setAccount", {"name": "s1-" + role}),
        ):
            status, code, msg = raw_post(ep, payload, token=owner_token)
            attempts.append({"endpoint": ep, "http": status, "code": code, "msg": msg})
        created = any(a["http"] == 200 and a["code"] == 0 for a in attempts)
        rep["principals_created"][role] = {
            "created": created, "attempts": attempts,
            "scope": "n/a" if not created else "unknown",
        }

    # ---------- 4. permission matrix over principals that really exist ----------
    cli = SiyuanClient()
    notebooks = {n["name"]: n["id"] for n in cli.ls_notebooks()}
    private_id = notebooks.get("person-private")
    shared_id = notebooks.get("family-shared")

    principals = {
        "owner": owner_token,
        "anonymous": None,
        "wrong-token": "0000000000000000",
    }
    # add adult/member only if the product actually minted them
    for role in ("adult", "member"):
        if rep["principals_created"][role]["created"]:
            principals[role] = rep["principals_created"][role].get("token")

    cases = [
        ("list-notebooks", "/api/notebook/lsNotebooks", {}),
        ("read-private-notebook-conf", "/api/notebook/getNotebookConf", {"notebook": private_id}),
        ("search-private-content", "/api/query/sql",
         {"stmt": "SELECT id,box,hpath FROM blocks WHERE box='%s' LIMIT 5" % private_id}),
        ("read-shared-notebook-conf", "/api/notebook/getNotebookConf", {"notebook": shared_id}),
        ("write-into-private", "/api/filetree/createDocWithMd",
         {"notebook": private_id, "path": "/native/_permcheck", "markdown": "# perm probe\n"}),
    ]

    # expectation: a real family permission system would DENY anonymous and
    # wrong-token everywhere, and DENY member/adult on person-private.
    expected_denied = {"anonymous", "wrong-token", "adult", "member"}

    for name, ep, payload in cases:
        if payload.get("notebook") is None and "notebook" in payload:
            continue
        for pname, ptok in principals.items():
            status, code, msg = raw_post(ep, payload, token=ptok)
            allowed = status == 200 and code == 0
            should_deny = pname in expected_denied and (
                "private" in name or pname in ("anonymous", "wrong-token")
            )
            rep["matrix"].append({
                "case": name, "principal": pname, "http": status, "code": code,
                "msg": msg, "allowed": allowed,
                "expected": "deny" if should_deny else "allow",
                "pass": (not allowed) if should_deny else allowed,
            })

    fails = [m for m in rep["matrix"] if not m["pass"]]
    have_multi = any(
        rep["principals_created"][r]["created"] for r in ("adult", "member")
    )
    rep["summary"] = {
        "matrix_cases": len(rep["matrix"]),
        "matrix_failures": len(fails),
        "multi_identity_supported": have_multi,
        "identity_endpoints_found": sorted(
            ep for ep, v in rep["identity_surface_probe"].items() if v["exists"]
        ),
    }
    if not have_multi:
        rep["finding"] = (
            "Self-hosted SiYuan exposes no user/role/token-issuance surface. Only two "
            "global credentials exist: one accessAuthCode (UI lock screen) and one API "
            "token. 'adult' and 'member' cannot be created, therefore the owner/adult/"
            "member matrix is UNSATISFIABLE by the product. Per roadmap week-5 verify "
            "clause, the conclusion is capped at single-user workbench."
        )
    else:
        rep["finding"] = "Multi-identity surface found; see matrix for pass/fail."

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print(json.dumps(rep["summary"], indent=2, ensure_ascii=False))
    print(rep["finding"])
    print("->", REPORT)


if __name__ == "__main__":
    main()
