# siyuan-lab — FamilyLifeOS Experiment S1

Time-boxed trial of **SiYuan (思源笔记)** as the family knowledge **authoring workbench**.

This repository is the executable evidence pack for S1. It is *not* a production
deployment. It exists to answer one question:

> Is SiYuan worth adopting for the "authoring workspace" capability slot, and
> can we get our data back out if the answer later becomes no?

**Verdict: `ADOPT` for the optional single-owner authoring-workspace slot
(83.9/90 assessed points; all five SiYuan hard gates passed).** The separately
reported 93.2% is only a normalization over the 90 assessed points and must not
be read as 93.2/100 coverage of the wider LifeOS architecture or security.

Self-hosted SiYuan still has **no per-user ACL**. It can be a private
single-owner workbench, but it is never the family permission system or an
authoritative record store.
See [docs/implementation/03-s1-scorecard.md](docs/implementation/03-s1-scorecard.md)
and [ADR-0005](docs/adr/0005-s1-verdict.md).

## Current experiment boundary

This repository owns SiYuan deployment experiments, adapters and measured
evidence only. `family-lifeos` owns product schemas, migrations, authorization,
Evidence/Artifact contracts and release logic.

The custom family facade is retained as a **non-production authentication PoC
using synthetic data**. It has known blocking defects and is not an accepted
identity or real-family-data boundary. V1 remains owner-only over VPN. See
[ADR-0007](docs/adr/0007-lab-boundary-and-facade-deferral.md) and
[the facade warning](docs/implementation/06-family-facade.md).

The active scope, evidence rules and exit criteria are in the
[S1 experiment charter](docs/EXPERIMENT-CHARTER.md).

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

## Vendoring (sync from family-lifeos)

Per [ADR-0007](docs/adr/0007-lab-boundary-and-facade-deferral.md) (cited
cross-repo as **SL-0007**),
[ADR-0010](../family-lifeos/docs/adr/0010-artifact-centred-operating-model.md)
and
[ADR-0012 §2](../family-lifeos/docs/adr/0012-cross-repo-contract-and-boundaries.md),
`family-lifeos` owns product schemas, migrations and release code. This repo
does **not** commit copied product code. The lab VM still needs them to run, so
a sync script copies them on demand:

```bash
bash scripts/sync_from_family_lifeos.sh /path/to/family-lifeos
```

This populates, all `.gitignore`d:

| Path | Source in family-lifeos |
|---|---|
| `infra/lifeos-migrations/` | `db/migrations/` |
| `scripts/lifeos_api.py` | `scripts/lifeos_api.py` |
| `scripts/seed_service_token.py` | `scripts/seed_service_token.py` |
| `scripts/ingest_api_test.py` | `tests/test_ingest_api_contract.py` |
| `scripts/lifeos_handoff.py` | `tests/contract/lifeos_handoff.py` |
| `scripts/family_view.py` | `scripts/experimental/family_view.py` |
| `scripts/seed_v8_grants.sql` | `scripts/experimental/seed_v8_grants.sql` |

The last three moved out of this repository on 2026-08-06 (ADR-0012 §2) and are
synced back only because retained lab evidence executes them. **Edit them in
`family-lifeos`; a local edit here is silently overwritten by the next sync.**

Run the sync before `run.sh push` / `run.sh deploy` / `run.sh lifeos-pg`. It
fails loudly if a source file is missing, rather than leaving a stale copy.

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

Objective 8's five representative phone tasks were subsequently completed by a
human and passed 15/15. That result validates the tested SiYuan authoring and
read-only experiment experience; it does not certify the custom facade or the
wider LifeOS security architecture for production use.

## Exit path

`make revoke` shreds the tokens; `make clean-remote` removes the containers.
Backups in `/opt/siyuan-lab/backups/` and the exported Markdown in `results/`
remain readable without SiYuan — that is the whole point of the export gate.
