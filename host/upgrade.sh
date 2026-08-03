#!/usr/bin/env bash
# S1 upgrade/rollback driver: change the pinned SiYuan image tag and redeploy.
# Usage: host/upgrade.sh <new-tag>
#
# S1 finding (defect D6): the first version of this script took the current tag
# from the VERSION text file and wrote PREV_VERSION unconditionally. Two ways
# that lies:
#   1. VERSION drifts from the image actually running, so PREV_VERSION records
#      a tag nobody was on.
#   2. Re-running with the tag already deployed collapses PREV_VERSION onto the
#      current tag, after which rollback.sh is a NO-OP that still prints a
#      passing smoke test.
# The running container is now the source of truth, PREV_VERSION is only
# updated on a real change, and the upgrade asserts the kernel actually reports
# the new version before declaring success.
set -euo pipefail
BASE=/opt/siyuan-lab

running_tag() {
  docker inspect -f '{{.Config.Image}}' siyuan-poc 2>/dev/null | sed 's#.*:##'
}

CUR="$(running_tag)"
if [[ -z "$CUR" ]]; then
  CUR="$(cat "$BASE/VERSION" 2>/dev/null || echo v3.7.3)"
  echo "[upgrade] no running container; falling back to VERSION file: $CUR"
fi
NEW="${1:-$CUR}"

if [[ "$NEW" == "$CUR" ]]; then
  echo "[upgrade] already on $CUR - nothing to do (PREV_VERSION left untouched)"
  echo "$CUR" > "$BASE/VERSION"
  exit 0
fi

echo "$CUR" > "$BASE/PREV_VERSION"
echo "$NEW" > "$BASE/VERSION"
AUTHCODE="$(cat "$BASE/secrets/authcode")"

echo "[upgrade] $CUR -> $NEW"
docker rm -f siyuan-poc 2>/dev/null || true
docker run -d --name siyuan-poc --restart unless-stopped --network siyuan_net \
  -e PUID=1000 -e PGID=1000 -e TZ=Asia/Shanghai \
  -e SIYUAN_ACCESS_AUTH_CODE="$AUTHCODE" \
  -v "$BASE/workspace":/siyuan/workspace \
  -p 127.0.0.1:6806:6806 \
  b3log/siyuan:"$NEW" serve --workspace=/siyuan/workspace/ --accessAuthCode="$AUTHCODE"

# The documented contract for every SiYuan endpoint is POST; /api/system/version
# happens to tolerate GET, but probing it the documented way removes any doubt.
# The elapsed line matters: the first measured upgrade took 121s and the loop
# timeout is also 120s, so without printing the iteration we could not tell a
# slow kernel boot from a probe that never succeeded. This number feeds the
# scorecard's maintenance minutes, so it has to be real.
BOOTED=false
for i in $(seq 1 60); do
  if wget -qO- --post-data='{}' http://127.0.0.1:6806/api/system/version >/dev/null 2>&1; then
    BOOTED=true; echo "[upgrade] kernel answered after $((i*2))s"; break
  fi
  sleep 2
done
$BOOTED || { echo "[upgrade] FAILED: kernel never answered on :6806" >&2
             docker logs --tail 40 siyuan-poc >&2 || true; exit 5; }

# assert the kernel really is the version we asked for
REPORTED="$(wget -qO- --post-data='{}' http://127.0.0.1:6806/api/system/version \
            | sed 's/.*"data":"\([^"]*\)".*/\1/')"
WANT="${NEW#v}"
if [[ "$REPORTED" != "$WANT" ]]; then
  echo "[upgrade] FAILED: asked for $WANT, kernel reports '$REPORTED'" >&2
  exit 4
fi
echo "[upgrade] kernel confirms $REPORTED"

echo "[upgrade] running smoke test"
bash "$BASE/host/smoke.sh" 6806
