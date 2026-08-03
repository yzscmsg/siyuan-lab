"""SiYuan v3.7.3 kernel HTTP API client (used by all S1 experiment scripts).

Auth model (docs/API.md):
  - Kernel listens on :6806. Every call is POST with JSON body + header
    `Authorization: Token <apiToken>` (token from Settings -> About, also in
    workspace/conf/conf.json -> system.apiToken).
  - In this PoC the kernel is fronted by Caddy (tls internal + basicauth), so
    clients also send HTTP Basic (user `siyuan`, pass = accessAuthCode).

The client is transport-agnostic: point SIYUAN_BASE_URL at either the LAN
Caddy URL (https://192.168.88.9) or the kernel directly (http://127.0.0.1:6806).
"""
from __future__ import annotations
import os, sys, time, json, hashlib, ssl, urllib.request, urllib.error, base64

SECRETS = ("/opt/siyuan-lab/secrets", "secrets")


def _read_secret(name):
    """Read a deploy.sh-provisioned secret from the VM secret store."""
    for d in SECRETS:
        try:
            with open(os.path.join(d, name)) as f:
                return f.read().strip()
        except OSError:
            continue
    return ""


def _on_vm():
    return os.path.isfile("/opt/siyuan-lab/secrets/api_token")


def _default_base():
    """
    Explicit env always wins. Otherwise pick the transport that actually works
    from where we are running:
      - ON the VM  -> kernel loopback (no TLS, no Caddy basicauth in the path)
      - elsewhere  -> the LAN Caddy URL
    Without this, VM-side scripts hit Caddy, get a 401 for the missing basicauth
    password, and fail as a misleading "kernel did not boot".
    """
    if os.environ.get("SIYUAN_BASE_URL"):
        return os.environ["SIYUAN_BASE_URL"]
    return "http://127.0.0.1:6806" if _on_vm() else "https://192.168.88.9"


DEFAULT_BASE = _default_base()
DEFAULT_TOKEN = os.environ.get("SIYUAN_TOKEN") or _read_secret("api_token")
# basicauth: OPT-IN ONLY. The PoC Caddy could not generate a password hash on
# this host (see infra/compose/Caddyfile + ADR-0001), so no basicauth is in the
# path today and the kernel authenticates purely on `Authorization: Token`.
# Auto-populating this would clobber the Token header and produce a misleading
# "Auth failed [session]" 401. Set SIYUAN_BASIC_PASS explicitly to re-enable.
BASIC_USER = os.environ.get("SIYUAN_BASIC_USER", "siyuan")
BASIC_PASS = os.environ.get("SIYUAN_BASIC_PASS", "")


class SiyuanError(RuntimeError):
    def __init__(self, code, msg, endpoint):
        super().__init__(f"[{endpoint}] code={code} msg={msg}")
        self.code = code
        self.msg = msg


class SiyuanClient:
    def __init__(self, base=DEFAULT_BASE, token=DEFAULT_TOKEN, basic_user=BASIC_USER, basic_pass=BASIC_PASS):
        self.base = base.rstrip("/")
        self.token = token
        self.basic_user = basic_user
        self.basic_pass = basic_pass

    # ---- low level ----
    def _post(self, endpoint, payload=None, raw=False, files=None, params=None, timeout=60):
        url = self.base + endpoint
        headers = {"Authorization": f"Token {self.token}"}
        if self.basic_pass:
            cred = base64.b64encode(f"{self.basic_user}:{self.basic_pass}".encode()).decode()
            headers["Authorization"] = f"Basic {cred}"
            headers["X-Siyuan-Token"] = self.token  # keep kernel token on a separate header
        data = None
        if files is not None:
            import io, random, string
            boundary = "----siyuanboundary" + "".join(random.choices(string.ascii_letters + string.digits, k=12))
            body = io.BytesIO()
            for k, v in (params or {}).items():
                body.write(f"--{boundary}\r\n".encode())
                body.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
                body.write(str(v).encode() + b"\r\n")
            for fname, fbytes in files:
                body.write(f"--{boundary}\r\n".encode())
                body.write(f'Content-Disposition: form-data; name="file[]"; filename="{fname}"\r\n'.encode())
                body.write(b"Content-Type: application/octet-stream\r\n\r\n")
                body.write(fbytes + b"\r\n")
            body.write(f"--{boundary}--\r\n".encode())
            data = body.getvalue()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        else:
            data = json.dumps(payload or {}).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                body = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            raise SiyuanError(-1, f"HTTP {e.code}: {body[:300]}", endpoint)
        if raw:
            return body
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            raise SiyuanError(-2, f"non-JSON response: {body[:300]}", endpoint)
        # Some endpoints (e.g. /api/query/sql in v3.7.3) return a raw array
        # instead of the {code,msg,data} envelope.
        if isinstance(obj, list):
            return obj
        if obj.get("code", 0) != 0:
            raise SiyuanError(obj.get("code"), obj.get("msg", ""), endpoint)
        return obj.get("data")

    # ---- boot / version ----
    def wait_boot(self, timeout=120, interval=2):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                self._post("/api/system/version")
                return True
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(interval)
        # surface the real cause - a 401 from Caddy is an auth problem, not a
        # boot problem, and silently calling it a timeout wastes an hour.
        raise TimeoutError(
            "SiYuan not reachable at %s after %ss; last error: %r"
            % (self.base, timeout, last))

    def version(self):
        return self._post("/api/system/version")

    # ---- notebooks ----
    def ls_notebooks(self):
        return self._post("/api/notebook/lsNotebooks").get("notebooks", [])

    def create_notebook(self, name):
        return self._post("/api/notebook/createNotebook", {"name": name})["notebook"]

    def open_notebook(self, notebook_id):
        return self._post("/api/notebook/openNotebook", {"notebook": notebook_id})

    def close_notebook(self, notebook_id):
        return self._post("/api/notebook/closeNotebook", {"notebook": notebook_id})

    def remove_notebook(self, notebook_id):
        return self._post("/api/notebook/removeNotebook", {"notebook": notebook_id})

    def get_notebook_conf(self, notebook_id):
        return self._post("/api/notebook/getNotebookConf", {"notebook": notebook_id})

    # ---- documents ----
    def create_doc_with_md(self, notebook_id, path, markdown):
        return self._post("/api/filetree/createDocWithMd",
                          {"notebook": notebook_id, "path": path, "markdown": markdown})

    def rename_doc(self, notebook_id, path, title):
        return self._post("/api/filetree/renameDoc",
                          {"notebook": notebook_id, "path": path, "title": title})

    def get_hpath_by_id(self, id):
        return self._post("/api/filetree/getHPathByID", {"id": id})

    # ---- blocks / editing ----
    def append_block(self, doc_id, markdown):
        return self._post("/api/block/appendBlock",
                          {"dataType": "markdown", "data": markdown, "parentID": doc_id})

    def update_block(self, block_id, markdown):
        return self._post("/api/block/updateBlock",
                          {"dataType": "markdown", "data": markdown, "id": block_id})

    def get_block_kramdown(self, block_id):
        return self._post("/api/block/getBlockKramdown", {"id": block_id})

    # ---- assets / attachments ----
    def upload_asset(self, filename, data, assets_dir="/assets/"):
        return self._post("/api/asset/upload", params={"assetsDirPath": assets_dir},
                          files=[(filename, data)])

    # ---- export ----
    def export_md_content(self, doc_id):
        return self._post("/api/export/exportMdContent", {"id": doc_id})

    def export_resources(self, paths, name=None):
        payload = {"paths": paths}
        if name:
            payload["name"] = name
        return self._post("/api/export/exportResources", payload)

    def get_file(self, path):
        # /api/file/getFile?path=... returns raw bytes
        url = self.base + "/api/file/getFile?path=" + urllib.parse.quote(path, safe="")
        headers = {"Authorization": f"Token {self.token}"}
        if self.basic_pass:
            cred = base64.b64encode(f"{self.basic_user}:{self.basic_pass}".encode()).decode()
            headers["Authorization"] = f"Basic {cred}"
            headers["X-Siyuan-Token"] = self.token
        req = urllib.request.Request(url, headers=headers, method="POST")
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
            return r.read()

    # ---- query ----
    def sql(self, stmt):
        return self._post("/api/query/sql", {"stmt": stmt}) or []

    def search(self, query):
        return self._post("/api/query/sql",
                          {"stmt": f"SELECT id, hpath, box FROM blocks WHERE content LIKE '%{query}%' LIMIT 50"})

    def fulltext_search(self, query, limit=50):
        """Real search index, not a SQL LIKE.

        `search()` above goes through query/sql, which reads the same sqlite
        table the UI reads but bypasses the search pipeline entirely. To claim
        "search works after a restore" we have to hit the endpoint the UI hits.

        MEASURED (v3.7.3): sending a `types` key AT ALL - even the doc example
        {"d":true,"h":true,"p":true}, even an empty {} - makes this endpoint
        return zero matches. Omitting the key entirely returns real hits. This
        is a genuine product quirk (see defect list); we omit `types` on purpose.
        """
        r = self._post("/api/search/fullTextSearchBlock",
                       {"query": query, "method": 0,  # NOTE: no "types" key, see above
                        "paths": [], "groupBy": 0, "orderBy": 0,
                        "page": 1, "pageSize": limit}) or {}
        return r.get("blocks") or []


if __name__ == "__main__":
    c = SiyuanClient()
    c.wait_boot()
    print("version:", c.version())
    print("notebooks:", [n["name"] for n in c.ls_notebooks()])
