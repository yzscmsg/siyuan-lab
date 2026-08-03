# S1 Runbook — SiYuan workbench trial

- Experiment: S1 (Week 5)
- Executed: 2026-08-02 / 2026-08-03
- Host: `192.168.88.9` (`r310-siyuan-poc-0`), Ubuntu 26.04, Docker 29.1.3
- Subject: `b3log/siyuan:v3.7.3` (pinned)
- Status: executed end-to-end; one objective (subjective family-task test) still requires a human

This runbook is written so the experiment can be re-run from zero on a clean host.
Every command below was actually executed; the "Observed" blocks are real output,
not expected output.

---

## 0. Prerequisites

- SSH reachable from the operator workstation (a route to `192.168.88.0/24` was
  added mid-experiment; before that the host was only reachable via a jump).
- `_refs/sshlib.py` provides `connect()` / `run()` and doubles as a CLI:
  `python _refs/sshlib.py "<command>"`.

Host preparation is idempotent and lives in `_refs/install_vm.py`:

- installs `docker.io`, `ca-certificates`, `apparmor`, `uidmap`, `slirp4netns`
- `systemctl enable --now docker`
- creates `/opt/siyuan-lab/{workspace,secrets,backups,exports,scripts,compose}`
- generates the lock-screen auth code: `openssl rand -hex 16 > secrets/authcode`

> **Gotcha.** `docker-compose-plugin` is **not** in the Ubuntu 26.04 release repo
> (`E: Unable to locate package`). The stack therefore deploys with plain
> `docker run`. `infra/compose/docker-compose.yaml` is kept as the portable,
> reviewable description of the same topology.

---

## 1. Objective 1 — Deploy a fixed version in an isolated lab

```bash
make deploy      # = push + bash /opt/siyuan-lab/host/deploy.sh
```

What `deploy.sh` guarantees, in the order the protocol asks for it:

| Requirement | Implementation |
| --- | --- |
| Fixed version | image pinned `b3log/siyuan:v3.7.3`, tag recorded in `/opt/siyuan-lab/VERSION` |
| Independent service account | `useradd -r -u 1000 siyuan`; `chown -R 1000:1000 workspace` |
| Independent volume | single bind mount `/opt/siyuan-lab/workspace → /siyuan/workspace` |
| Not exposed to the LAN directly | `-p 127.0.0.1:6806:6806` (loopback only) |
| DNS/TLS | `caddy:2.8.4` on 80/443, `tls internal` (self-signed CA) |
| API token in a secret store | extracted post-boot to `secrets/api_token`, `chmod 600` |

> **Gotcha.** Since v3.7.0 the container needs the `serve` subcommand:
> `serve --workspace=/siyuan/workspace/ --accessAuthCode=...`. Without it the
> kernel starts in a mode that never answers `/api/system/version`.

> **Gotcha.** The API token is **not** at `system.token` as older docs suggest.
> In v3.7.3 it is `conf/conf.json → api.token`.

> **Gotcha.** `caddy hash-password` returns `Error: EOF` when run non-interactively
> on this host, which aborted the first deploy under `set -e`. Basic-auth was
> dropped from the Caddyfile; authentication is enforced by SiYuan's own lock
> screen (`accessAuthCode`) plus the API token. Caddy is TLS termination only.
> **This is a known weakening and is recorded as a defect in the scorecard.**

**Observed**

```
siyuan-poc     b3log/siyuan:v3.7.3   Up
siyuan-caddy   caddy:2.8.4           Up
{"code":0,"msg":"","data":"3.7.3"}
```

---

## 2. Objective 2 — Two notebooks and the real permission model

```bash
make seed        # creates the notebooks as part of seeding
make perm        # probes the permission model
```

Created `family-shared` (intended public) and `person-private` (intended private),
then tested whether that intent is actually enforceable.

**Observed** (`results/exports/perm_matrix_report.json`)

```json
{
  "single_token_reads_all": {"api-suite": true, "person-private": true, "family-shared": true},
  "per_notebook_acl_api": "No 'permission'/'acl'/'share' key in notebook conf"
}
```

**Finding — this is the most important result of S1.** Self-hosted SiYuan exposes
a *single* API token and has *no* per-user or per-notebook ACL. One token reads
every notebook, including `person-private`. Notebook separation is organisational,
not a security boundary.

Consequence, per the protocol's own rule ("if multi-user isolation is insufficient,
it can only be positioned as a single-person workbench, not the family permission
system"): **SiYuan cannot be the family permission system.** See
[ADR-0003](../adr/0003-siyuan-permission-model.md).

---

## 3. Objective 3 — Import 20 corpus documents

```bash
make seed
```

`scripts/gen_corpus.py` generates the corpus **and** records a pre-import
`sha256` manifest (`corpus/manifest.yaml`) before anything touches SiYuan —
this is what makes the round-trip claim falsifiable.

Coverage is deliberately spread across the formats that break importers:

| Docs | Coverage |
| --- | --- |
| c01–c05 | EN: article+table, long-form, image embed, code, internal link |
| c06–c10 | ZH: 运营复盘+表格, 长文, 图片, 代码, 内部链接 |
| c11–c15 | Bilingual: intro, policy, glossary, tasks, FAQ |
| c16–c20 | PDF attachment link, quote + nested headings, checklist, mixed en/zh table, index hub |

Binary assets: `sample-chart.png`, `sample-doc.pdf` (both hashed pre-import).

> **Gotcha.** `gen_corpus.py`'s PDF writer originally used `%`-formatting on a
> body containing literal `%` sequences → `ValueError: unsupported format
> character 'P'`. Fixed by using `.replace("%s", title)`.

---

## 4. Objective 4 — 10 native notes using SiYuan-specific features

| Note | Feature under test |
| --- | --- |
| n01 | block reference + wikilink |
| n02 | template |
| n03 | tags |
| n04 | wikilinks |
| n05 | attachment |
| n06 | block-ref target |
| n07 | query / database view |
| n08 | long native note |
| n09 | native table |
| n10 | summary |

These exist specifically to find out what is *lost* when leaving SiYuan —
they are the vendor-lock-in probes.

---

## 5. Objective 5 — API create / read / update / export ×5

```bash
make api-suite
```

Auth is `Authorization: Token <token>`, POST + JSON. Endpoints exercised:
`/api/notebook/{lsNotebooks,createNotebook,openNotebook}`,
`/api/filetree/createDocWithMd`, `/api/asset/upload` (multipart),
`/api/export/exportMdContent`, `/api/query/sql`.

**Observed** (`results/exports/api_suite_report.json`)

```json
{
  "create": ["...5 ids..."],
  "read":   {"...": true, "x5": true},
  "update": {"...": true, "x5": true},
  "export": {"...": true, "x5": true},
  "idempotency": {"same_id_on_dup_path": false},
  "errors": {
    "no_token":     {"code": -1, "msg": "HTTP 401: Auth failed [session]"},
    "bad_notebook": {"code": -1, "msg": "Query notebook failed"}
  }
}
```

Two behaviours that the integration layer must absorb:

1. **`createDocWithMd` is not idempotent.** Posting the same path twice creates a
   *second* document with a new id. Any retry — an n8n re-run, a webhook
   redelivery — silently duplicates content. Deduplication must live in
   LifeOS/n8n, keyed on the LifeOS UUID, never on SiYuan's path.
2. **The error model is thin.** Everything is `code: -1` with a prose `msg`;
   auth failures surface as HTTP 401. Callers cannot branch on error class,
   only on string matching. Treat all non-zero codes as retry-with-backoff and
   escalate on repeat.

> **Gotcha.** `/api/query/sql` in v3.7.3 returns a **raw JSON array**, not the
> usual `{code,msg,data}` envelope. `scripts/api_client.py:_post` handles both.

---

## 6. Objective 6 — Standard Markdown + assets export, and fidelity

```bash
make export     # on the VM: writes exports/markdown/<notebook>/<hpath>.md + assets/
make pull       # bring evidence back to the repo
make fidelity   # local round-trip analysis
```

**Export result** (`results/exports/export_report.json`)

```
docs_total 30 | docs_exported 30 | docs_with_content 30 | title_match 30
assets_checked 2 | assets_hash_match 2
```

**Round-trip fidelity** (`results/fidelity_report.json`) compares the *pre-import*
originals against the *post-export* Markdown across headings, heading levels,
tables, table rows, code blocks + code body hashes, images, links, wikilinks,
task lists, list items, inline code, blockquotes, tags and a normalised word bag
(CJK compared per-character).

```
docs_compared 30 | docs_missing 0
structural_pass 30/30 (100%)
word retention: min 100%, mean 100%
wikilinks: 14 original -> 14 surviving
```

Three **systematic** transformations apply to every document. All three are
benign and reversible, but a downstream parser must expect them:

1. A YAML front-matter block is prepended (`title`, `date`, `lastmod`).
2. The document *name* is prepended as an H1, so a doc whose body already starts
   with an H1 exports with two leading headings.
3. Uploaded assets are content-addressed on upload:
   `assets/sample-chart.png → assets/sample-chart-20260803004437-bel5vun.png`.
   The **bytes are unchanged** (sha256 verified 2/2); only the filename changes.
   Four documents (c03, c08, c16, n05) reference assets and therefore show a
   filename delta — `scripts/fidelity.py` classifies these as
   `asset_rename_only` rather than data loss.

This is the hard gate that matters most for the exit path, and it passes: the
export is ordinary Markdown plus an ordinary asset folder, readable with no
SiYuan present.

---

## 7. Objective 7 — Backup, restore on a fresh instance

```bash
make backup        # stop kernel -> tar.gz workspace -> restart -> manifest
make restore-test  # extract to a NEW workspace, boot a throwaway kernel on :6807, verify
```

`backup.sh` stops the kernel first so in-flight writes flush, then writes an
archive plus a manifest with size, `.sy` count and sha256.

**Observed backup manifest**

```json
{
  "archive": "siyuan-20260802-165053.tar.gz",
  "workspace_doc_count_sy": 42,
  "size_bytes": 29808145,
  "sha256": "9bf8bbcc9e25367d112a5bc740750d4e48b633826fd2c0dca54f02bebdada5c4"
}
```

**Observed restore verification** (`results/exports/restore_doc_count.txt`)

```
notebooks=3 docs_sql=46 sy_files=42
```

Notebooks open, documents indexed and searchable, attachments present — restored
into a *fresh* workspace on a *separate* container, with **no manual database
surgery**. Hard gate passed.

> **Gotcha (cost us the most time).** The restore reported `0 docs` three times
> for three different reasons, all now fixed in `restore.sh`:
> 1. Extracting into `$BASE` and then `mv`-ing moved the **live** workspace out
>    from under the running container. Fixed: extract to `mktemp -d` first.
> 2. `mkdir -p $RESTORE_WS` before `mv $TMP/workspace $RESTORE_WS` **nested** the
>    data one level deep (`restore-workspace/workspace/...`), so the kernel saw
>    an empty workspace. Fixed: `rm -rf $RESTORE_WS` and let `mv` create it.
> 3. The restored instance has **its own** token; reusing the secret-store token
>    returned 401 and `set -e` killed the script. Fixed: read the token from the
>    *restored* `conf.json` and pass it via `SIYUAN_TOKEN`.
> 4. Notebooks must be **opened** and given ~15 s to index before
>    `SELECT COUNT(*) FROM blocks` returns anything.

> **Gotcha.** `zstd` is not installed on this host; `tar --zstd` fails and leaves
> a 0-byte archive. Switched to `--gzip`.

---

## 8. Objective 8 — Version upgrade, smoke test, rollback

```bash
make upgrade TAG=v3.7.2
make rollback           # returns to the tag saved in PREV_VERSION
```

`upgrade.sh` records the current tag to `PREV_VERSION`, redeploys against the new
tag on the *same* workspace volume, waits for boot, then runs `smoke.sh`
(kernel version + `SELECT COUNT(*) FROM blocks WHERE type='d'`).

**Observed:** v3.7.3 → v3.7.2 → v3.7.3, smoke test passing at every step, doc
count unchanged, no data loss.

- Downtime per switch: container recreate + kernel boot, roughly 20–40 s.
- Manual steps required: none — the tag is the only input.
- Rollback is a single command and does not depend on a backup being restored,
  because the workspace format was compatible in both directions across this
  patch range. **Caveat:** SiYuan performs one-way data migrations on some
  *minor* upgrades. A backup before upgrade is mandatory, and rollback across a
  minor version must be assumed to require `make restore-test`, not `make rollback`.

---

## 9. Permission negative tests and leakage check

```bash
make negative
```

**Observed** (`results/exports/negative_report.json`)

```json
{
  "search_visible_boxes_with_one_token": ["family-shared", "person-private", "api-suite"],
  "private_notebook_visible_to_single_token": true,
  "secret_leak_in_userdata": false,
  "secret_in_userdata_files": []
}
```

- Unauthorised read: **not preventable within SiYuan** — one token, full visibility.
  Search results leak private-notebook paths. This is the finding from §2 confirmed
  from the search surface.
- Token / auth-code leakage into note content or exported files: **none found**.
- Backups contain `conf.json`, which contains the API token. Backup archives must
  therefore be treated as secret material — encrypt at rest and keep them out of
  any path an AI layer can read.

---

## 10. Open item — manual step

Objective: *"run five real family tasks on a real mobile device and record the
subjective experience."*

This cannot be automated and is **not** done. It requires: install the SiYuan
mobile client, connect it to `https://192.168.88.9` (accepting the internal CA),
and perform five genuine tasks — e.g. capture a receipt photo, write a shopping
list, look up a past note, edit a shared doc, attach a PDF.

Record for each: did it work, how long, how annoying. This feeds the
"daily-use value" weight in the scorecard, which is currently scored on desktop/API
evidence only and flagged as provisional.

---

## 11. Exit path (protocol step 10)

```bash
make revoke        # shred secrets/api_token and secrets/authcode
make clean-remote  # remove siyuan-poc, siyuan-caddy, siyuan-restore, siyuan_net
```

Evidence retained after teardown:

- `results/exports/markdown/**` — plain Markdown + assets, readable without SiYuan
- `results/*.json` — all test reports
- `/opt/siyuan-lab/backups/*.tar.gz` + manifests — full workspace snapshots

**Not yet executed.** The stack is intentionally left running pending the
objective-8 mobile test. Run these two targets once that is done, or immediately
if the trial is abandoned.
