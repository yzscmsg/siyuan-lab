# ADR-0001: SiYuan lab deployment model

- Status: Accepted
- Date: 2026-08-03
- Scope: experiment S1 only (not a production commitment)

## Context

S1 needs a SiYuan instance that is reproducible, disposable and cannot
contaminate the rest of the estate. The protocol requires a fixed version, an
independent service account, an independent volume, DNS/TLS, and the API token
held in a secret store.

## Decision

Deploy on the isolated lab host `192.168.88.9` under `/opt/siyuan-lab` with:

1. **Pinned image** `b3log/siyuan:v3.7.3`, tag mirrored in `/opt/siyuan-lab/VERSION`.
   Never `:latest`.
2. **`serve` subcommand required** — `serve --workspace=/siyuan/workspace/
   --accessAuthCode=...`. Mandatory since v3.7.0.
3. **Dedicated service account** `siyuan` (uid/gid 1000) owning the workspace
   bind mount; container runs with `PUID`/`PGID` 1000, not root.
4. **Loopback-only kernel port** `-p 127.0.0.1:6806:6806`. The kernel is never
   published to the LAN.
5. **Caddy 2.8.4 in front** on 80/443 with `tls internal`, reverse-proxying to
   the kernel over the private `siyuan_net` bridge.
6. **Secrets on the host, not in the image or compose file**:
   `/opt/siyuan-lab/secrets/{authcode,api_token}`, mode 600. The auth code is
   generated with `openssl rand -hex 16`; the API token is extracted post-boot
   from `conf/conf.json → api.token`.
7. **Plain `docker run` for execution, compose file for description.**
   `docker-compose-plugin` is unavailable in the Ubuntu 26.04 release repo, so
   `host/deploy.sh` uses `docker run`. `infra/compose/docker-compose.yaml`
   is maintained as the reviewable, portable topology description.

## Consequences

- Redeploy is one idempotent command; the container is cattle, the workspace
  volume is the only state.
- The compose file and the deploy script can drift. Any topology change must be
  made in both. Accepted for a time-boxed experiment; unacceptable for
  production, where compose (or equivalent) must be the executed artefact.

## Known weakening

Caddy basic-auth was **removed**. `caddy hash-password` returns `Error: EOF`
non-interactively on this host and aborted the deploy under `set -e`.
Authentication therefore rests on SiYuan's own lock screen plus the API token,
with Caddy providing TLS only.

For a lab on a segmented network this is tolerable. **Before any promotion
beyond the lab, an authenticating reverse proxy is required** — this is the same
class of gap recorded for mcp-odoo's HTTP transport, and it must not be carried
forward silently.
