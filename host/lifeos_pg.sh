#!/usr/bin/env bash
# Stand up the LifeOS canonical store so S1 step 8 can actually be executed.
#
# Roadmap step 8: "将导出内容交给第4周 Document API 注册；LifeOS 分配 UUID/owner/
# ACL/hash，禁止读取思源内部数据库或数据目录。"
#
# The week-4 Document API is not implemented yet, but its schema IS: this brings
# up postgres:16 and applies family-lifeos db/migrations verbatim (vendored at
# infra/lifeos-migrations, provenance commit f597f61), using the same
# checksummed-idempotent semantics as the repo's scripts/admin/migrate.sh.
#
# That gives the handoff test the real constraint that matters:
#   core.document UNIQUE (household_id, sha256)
# which is the canonical idempotency key for repeated ingest.
set -Eeuo pipefail

BASE=/opt/siyuan-lab
MIG="$BASE/infra/lifeos-migrations"
CT=lifeos-pg
DB=lifeos
DBUSER=lifeos
PGPORT=${PGPORT:-55432}

mkdir -p "$BASE/secrets"
if [[ ! -f "$BASE/secrets/pg_password" ]]; then
  openssl rand -hex 24 > "$BASE/secrets/pg_password"
  chmod 600 "$BASE/secrets/pg_password"
fi
PGPASS=$(cat "$BASE/secrets/pg_password")

docker network create siyuan_net >/dev/null 2>&1 || true

if ! docker ps --format '{{.Names}}' | grep -qx "$CT"; then
  docker rm -f "$CT" >/dev/null 2>&1 || true
  echo "[lifeos-pg] starting postgres:16"
  docker run -d --name "$CT" --network siyuan_net --restart unless-stopped \
    -e POSTGRES_DB="$DB" -e POSTGRES_USER="$DBUSER" -e POSTGRES_PASSWORD="$PGPASS" \
    -v "$BASE/lifeos-pgdata:/var/lib/postgresql/data" \
    -p 127.0.0.1:${PGPORT}:5432 \
    postgres:16 >/dev/null
fi

echo "[lifeos-pg] waiting for readiness"
for _ in $(seq 1 60); do
  if docker exec "$CT" pg_isready -U "$DBUSER" -d "$DB" >/dev/null 2>&1; then break; fi
  sleep 2
done
docker exec "$CT" pg_isready -U "$DBUSER" -d "$DB"

psqlc() { docker exec -i "$CT" psql -v ON_ERROR_STOP=1 -U "$DBUSER" -d "$DB" "$@"; }

# 0001 creates audit.schema_migration itself, so bootstrap it unconditionally.
for m in "$MIG"/*.sql; do
  fn=$(basename "$m"); ver=${fn%%_*}
  sum=$(sha256sum "$m" | awk '{print $1}')
  existing=$(psqlc -Atc "select sha256 from audit.schema_migration where version='$ver'" 2>/dev/null || true)
  if [[ -n "$existing" ]]; then
    if [[ "$existing" != "$sum" ]]; then
      echo "[lifeos-pg] FAIL applied migration changed: $fn" >&2; exit 3
    fi
    echo "[lifeos-pg] already applied: $fn"
    continue
  fi
  echo "[lifeos-pg] applying $fn"
  psqlc < "$m"
  psqlc -c "insert into audit.schema_migration(version, filename, sha256) values ('$ver','$fn','$sum')"
done

echo "[lifeos-pg] migrations:"
psqlc -Atc "select version || ' ' || filename from audit.schema_migration order by version"
echo "[lifeos-pg] ready on 127.0.0.1:${PGPORT} db=$DB user=$DBUSER"
