.PHONY: help validate push pull deploy seed export api-suite perm negative fidelity \
        backup restore-test upgrade rollback smoke status logs all clean-remote revoke

VM      ?= 192.168.88.9
BASE    ?= /opt/siyuan-lab
PY      ?= C:/Users/georg/.workbuddy/binaries/python/envs/default/Scripts/python.exe
SSH     ?= $(PY) ../_refs/sshlib.py
TAG     ?= v3.7.3

help:
	@echo "S1 targets:  push deploy seed export api-suite perm negative fidelity"
	@echo "             backup restore-test upgrade rollback smoke status pull all"
	@echo "Teardown:    revoke clean-remote"

# --- compose file is kept for portability even though deploy uses docker run ---
validate:
	$(SSH) "docker run --rm -v $(BASE)/infra/compose:/w -w /w mikefarah/yq e '.' docker-compose.yaml >/dev/null && echo compose-ok"

# --- code sync -------------------------------------------------------------
push:
	$(PY) host/push.py

pull:
	$(PY) host/pull.py

# --- S1 objective 1: deploy ------------------------------------------------
deploy: push
	$(SSH) "bash $(BASE)/host/deploy.sh"

# --- S1 objectives 2-4: notebooks, corpus import, native notes -------------
seed:
	$(SSH) "cd $(BASE) && python3 scripts/gen_corpus.py && python3 scripts/seed.py"

# --- S1 objective 5: API suite (create/read/update/export + error model) ---
api-suite:
	$(SSH) "cd $(BASE) && python3 scripts/api_suite.py"

# --- S1 objective 6: standard Markdown + assets export ---------------------
export:
	$(SSH) "cd $(BASE) && python3 scripts/export_md.py"

# round-trip fidelity is computed LOCALLY against the pulled export
fidelity:
	$(PY) scripts/fidelity.py

# --- S1 objective 7: permissions + leakage ---------------------------------
perm:
	$(SSH) "cd $(BASE) && python3 scripts/perm_matrix.py"

negative:
	$(SSH) "cd $(BASE) && python3 scripts/negative_tests.py"

# --- S1 objective 8: backup / restore / upgrade / rollback -----------------
backup:
	$(SSH) "bash $(BASE)/host/backup.sh"

restore-test:
	$(SSH) "bash $(BASE)/host/restore.sh"

upgrade:
	$(SSH) "bash $(BASE)/host/upgrade.sh $(TAG)"

rollback:
	$(SSH) "bash $(BASE)/host/rollback.sh"

smoke:
	$(SSH) "bash $(BASE)/host/smoke.sh"

# --- ops -------------------------------------------------------------------
status:
	$(SSH) "docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'; wget -qO- http://127.0.0.1:6806/api/system/version; echo"

logs:
	$(SSH) "docker logs --tail=200 siyuan-poc"

# --- full S1 run -----------------------------------------------------------
all: deploy seed api-suite export perm negative backup restore-test pull fidelity
	@echo "S1 complete - see results/ and docs/implementation/03-s1-scorecard.md"

# --- exit path (protocol step 10) -----------------------------------------
revoke:
	$(SSH) "shred -u $(BASE)/secrets/api_token $(BASE)/secrets/authcode 2>/dev/null || rm -f $(BASE)/secrets/api_token $(BASE)/secrets/authcode; echo secrets-revoked"

clean-remote:
	$(SSH) "docker rm -f siyuan-poc siyuan-caddy siyuan-restore 2>/dev/null; docker network rm siyuan_net 2>/dev/null; echo containers-removed; ls -1 $(BASE)/backups/"
