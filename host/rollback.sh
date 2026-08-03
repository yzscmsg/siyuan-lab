#!/usr/bin/env bash
# S1 rollback: redeploy the previously-pinned SiYuan tag (see upgrade.sh).
#
# Hard gate 2 asks whether a failed upgrade can be rolled back. A rollback that
# quietly does nothing and still prints a passing smoke test would satisfy the
# script while failing the gate, so this refuses to report success unless the
# running tag actually changed back.
set -euo pipefail
BASE=/opt/siyuan-lab

running_tag() {
  docker inspect -f '{{.Config.Image}}' siyuan-poc 2>/dev/null | sed 's#.*:##'
}

CUR="$(running_tag)"
PREV="$(cat "$BASE/PREV_VERSION" 2>/dev/null || true)"

if [[ -z "$PREV" ]]; then
  echo "[rollback] FAILED: no PREV_VERSION recorded - nothing to roll back to" >&2
  exit 3
fi
if [[ "$PREV" == "$CUR" ]]; then
  echo "[rollback] FAILED: PREV_VERSION ($PREV) equals the running tag ($CUR);" >&2
  echo "           this would be a silent no-op, not a rollback." >&2
  exit 3
fi

echo "[rollback] $CUR -> $PREV"
bash "$BASE/host/upgrade.sh" "$PREV"

NOW="$(running_tag)"
if [[ "$NOW" != "$PREV" ]]; then
  echo "[rollback] FAILED: expected $PREV, running $NOW" >&2
  exit 4
fi
echo "[rollback] confirmed running $NOW"
