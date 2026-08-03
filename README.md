# siyuan-lab — FamilyLifeOS Experiment S1

Time-boxed trial of **SiYuan (思源笔记)** as the family knowledge **authoring workbench**.

This repository is the executable evidence pack for S1. It is *not* a production
deployment. It exists to answer one question:

> Is SiYuan worth adopting for the "authoring workspace" capability slot, and
> can we get our data back out if the answer later becomes no?

**Verdict: `TRIAL` (score 75/100, all five hard gates passed).**
Capped by one finding: self-hosted SiYuan has **no per-user ACL**, so it can be a
single-person workbench but never the family permission system.
See [docs/implementation/03-s1-scorecard.md](docs/implementation/03-s1-scorecard.md)
and [ADR-0005](docs/adr/0005-s1-verdict.md).

## Capability slot boundary

| Layer | Owner | Notes |
| --- | --- | --- |
| Canonical record | **LifeOS / NAS** | UUID, owner, ACL, checksum, retention |
| Authoring workspace | **SiYuan** (this trial) | Editing surface only. Not a system of record. |
| Derived AI layer | **Dify** (`rag-lab-kit`) | Index/embeddings are rebuildable, never canonical |

Hard rule, enforced by design: **LifeOS never reads SiYuan's internal database.**
The only supported seam is the standard Markdown + assets export.
See [docs/implementation/02-lifeos-rag-seam.md](docs/implementation/02-lifeos-rag-seam.md).

## Environment under test

| Item | Value |
| --- | --- |
| Host | `192.168.88.9` (`r310-siyuan-poc-0`), Ubuntu 26.04 |
| Runtime | Docker 29.1.3, plain `docker run` (no compose plugin in this release repo) |
| SiYuan | `b3log/siyuan:v3.7.3`, pinned, `serve` subcommand |
| Proxy | `caddy:2.8.4`, `tls internal` |
| Base path | `/opt/siyuan-lab` |
| Service account | `siyuan` uid/gid 1000, owns the workspace volume |
| Secrets | `/opt/siyuan-lab/secrets/{authcode,api_token}`, mode 600, off the container |

## Layout

```
infra/compose/     docker-compose.yaml + Caddyfile + .env.example (pinned versions)
host/              deploy, backup, restore, upgrade, rollback, smoke, push/pull
scripts/           API client + the S1 test suites
corpus/            20 imported docs + 10 native notes + assets + sha256 manifest
results/           evidence pulled back from the VM (reports, exported markdown)
docs/adr/          decision records
docs/implementation/  runbook, RAG seam, scorecard
```

## Running S1

`make` is not installed on the Windows operator workstation (Git Bash ships
without it), so **`./run.sh <target>` is the working entry point** and mirrors the
Makefile one-for-one. Use `make` on a Linux/macOS operator box if you prefer.

```bash
./run.sh deploy    # or: make deploy
./run.sh all       # or: make all
```

Full sequence:

```bash
./run.sh deploy         # provision + boot pinned stack, extract API token
./run.sh seed           # 2 notebooks, 20 corpus docs, 10 native notes, 2 assets
./run.sh api-suite      # create/read/update/export x5 + idempotency + error model
./run.sh export         # standard Markdown + assets, verify asset hashes
./run.sh perm           # permission matrix
./run.sh negative       # leakage + unauthorised-read checks
./run.sh backup         # consistent workspace snapshot
./run.sh restore-test   # restore into a FRESH instance and verify
./run.sh upgrade v3.7.2 && ./run.sh rollback
./run.sh pull           # bring evidence home
./run.sh fidelity       # round-trip fidelity analysis (runs locally)
```

Ops helpers: `./run.sh status`, `./run.sh logs`, `./run.sh smoke`.

## Headline results

| Objective | Result |
| --- | --- |
| Deploy (pinned, isolated, TLS, secret store) | pass |
| Notebooks + permission model | **pass with finding — no per-user ACL exists** |
| 20 corpus docs imported | 30/30 docs created |
| 10 native notes (block ref, wikilink, tags, template, attachment, query) | pass |
| API create/read/update/export ×5 | pass; `createDocWithMd` is **not idempotent** |
| Markdown + assets export | 30/30, titles preserved, 2/2 asset hashes match |
| Round-trip fidelity | **30/30 structural pass, 100% word retention** |
| Backup → restore on fresh instance | 3 notebooks, 42 `.sy`, 46 doc blocks, searchable |
| Upgrade → rollback | v3.7.3 → v3.7.2 → v3.7.3, no data loss |
| Secret leakage into notes/logs | none found |

The one thing S1 could not do for you: **objective 8's subjective test** (five real
family tasks on a real phone). That needs a human. See the runbook's
[open item](docs/implementation/01-s1-runbook.md#10-open-item--manual-step).

## Exit path

`make revoke` shreds the tokens; `make clean-remote` removes the containers.
Backups in `/opt/siyuan-lab/backups/` and the exported Markdown in `results/`
remain readable without SiYuan — that is the whole point of the export gate.
