#!/usr/bin/env bash
# make-free runner for the S1 targets.
# `make` is not installed on the Windows operator workstation (Git Bash ships
# without it), so this mirrors the Makefile one-for-one.
#
#   setup      : push | deploy | seed | reseed | lifeos-pg
#   evidence   : api-suite | export | fidelity | identity | perm | negative
#              : handoff | escrow
#   lifecycle  : backup | restore-test | upgrade [tag] | rollback | smoke
#   destructive: retraction
#   suite      : accept-safe | accept-full | accept-eval | stages
#   operator   : pull | status | logs | all | revoke | clean-remote
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Git Bash reports /c/Users/... which a native Windows python cannot open.
# cygpath -m yields C:/Users/... which works for both.
if command -v cygpath >/dev/null 2>&1; then
  HERE="$(cygpath -m "$HERE")"
else
  # fallback: /c/Users/... -> C:/Users/...
  HERE="$(printf '%s' "$HERE" | sed -E 's#^/([a-zA-Z])/#\1:/#')"
fi
BASE=/opt/siyuan-lab
PY="${PY:-C:/Users/georg/.workbuddy/binaries/python/envs/default/Scripts/python.exe}"
SSHLIB="$HERE/../_refs/sshlib.py"

ssh_run() { "$PY" "$SSHLIB" "$1"; }

case "${1:-help}" in
  push)         "$PY" "$HERE/host/push.py" ;;
  pull)         "$PY" "$HERE/host/pull.py" ;;
  fidelity)     "$PY" "$HERE/scripts/fidelity.py" ;;

  deploy)       "$PY" "$HERE/host/push.py"; ssh_run "bash $BASE/host/deploy.sh" ;;
  seed)         ssh_run "cd $BASE && python3 scripts/gen_corpus.py && python3 scripts/seed.py" ;;
  # createDocWithMd is not idempotent (defect D1) - re-seeding without a reset
  # doubles the corpus, so a repeat run must drop the notebooks first.
  reseed)       ssh_run "cd $BASE && python3 scripts/gen_corpus.py && python3 scripts/seed.py --reset" ;;

  lifeos-pg)    ssh_run "bash $BASE/host/lifeos_pg.sh" ;;
  api-suite)    ssh_run "cd $BASE && python3 scripts/api_suite.py" ;;
  export)       ssh_run "cd $BASE && python3 scripts/export_md.py" ;;
  identity)     ssh_run "cd $BASE && python3 scripts/identity_matrix.py" ;;
  perm)         ssh_run "cd $BASE && python3 scripts/perm_matrix.py" ;;
  negative)     ssh_run "cd $BASE && python3 scripts/negative_tests.py" ;;
  handoff)      ssh_run "cd $BASE && python3 scripts/lifeos_handoff.py" ;;
  escrow)       ssh_run "bash $BASE/host/escrow.sh" ;;
  retraction)   ssh_run "cd $BASE && python3 scripts/retraction_test.py" ;;

  backup)       ssh_run "bash $BASE/host/backup.sh" ;;
  restore-test) ssh_run "bash $BASE/host/restore.sh" ;;
  upgrade)      ssh_run "bash $BASE/host/upgrade.sh ${2:-v3.7.3}" ;;
  rollback)     ssh_run "bash $BASE/host/rollback.sh" ;;
  smoke)        ssh_run "bash $BASE/host/smoke.sh" ;;

  # ---- master acceptance suite (executable form of the week-5 card) --------
  stages)       ssh_run "cd $BASE && python3 scripts/s1_acceptance.py --list" ;;
  accept-safe)  ssh_run "cd $BASE && python3 scripts/s1_acceptance.py --stages safe" ;;
  # detached: the destructive stages outlive an SSH channel
  accept-full)  "$PY" "$HERE/host/run_full.py" --full --yes ;;
  accept-eval)  ssh_run "cd $BASE && python3 scripts/s1_acceptance.py --evaluate-only" ;;
  accept)       ssh_run "cd $BASE && python3 scripts/s1_acceptance.py --stages ${2:-export}" ;;

  status)       ssh_run "docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'; wget -qO- http://127.0.0.1:6806/api/system/version; echo" ;;
  logs)         ssh_run "docker logs --tail=200 siyuan-poc" ;;

  all)
    echo "=== push+deploy ===";   "$0" deploy
    echo "=== reseed ===";        "$0" reseed
    echo "=== accept-full ===";   "$0" accept-full
    echo "=== pull ===";          "$0" pull
    echo "S1 complete - see results/ and docs/implementation/03-s1-scorecard.md" ;;

  revoke)
    ssh_run "shred -u $BASE/secrets/api_token $BASE/secrets/authcode 2>/dev/null || rm -f $BASE/secrets/api_token $BASE/secrets/authcode; echo secrets-revoked" ;;
  clean-remote)
    ssh_run "docker rm -f siyuan-poc siyuan-caddy siyuan-restore lifeos-pg 2>/dev/null; docker network rm siyuan_net 2>/dev/null; echo containers-removed; ls -1 $BASE/backups/" ;;

  *)
    sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^#\s\{0,1\}//' ;;
esac
