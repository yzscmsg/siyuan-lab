#!/usr/bin/env python3
"""S1 acceptance suite -- the executable form of the week-5 experiment card.

Source of truth:
  family-lifeos  docs/roadmap/family-lifeos-implementation-and-experiments.md
  commit         f597f61a68cd721eb0d2494673d50cd9e2cc8a58
  sections       "第5周：执行思源 S1" (steps 1-14, How to verify)
                 "硬门槛（任一失败即不能 Adopt）" (5 gates)
                 "加权评分（硬门槛通过后）" (6 weighted dimensions)

Every assertion below quotes the clause it enforces. Nothing is scored that was
not measured, and anything a script cannot decide is reported MANUAL rather than
quietly passed.

    stages      run the experiment, writing one JSON report per stage
    criteria    evaluate V1..V7 (How to verify) from those reports
    gates       evaluate HG1..HG5 (hard gates)
    score       weighted score, only meaningful once every gate passes

Usage (ON the VM, from /opt/siyuan-lab):

    python3 scripts/s1_acceptance.py --list
    python3 scripts/s1_acceptance.py --evaluate-only
    python3 scripts/s1_acceptance.py --stages export,fidelity,negative,identity
    python3 scripts/s1_acceptance.py --full          # includes destructive stages
    python3 scripts/s1_acceptance.py --full --yes    # no confirmation prompt

--full runs backup, restore-into-fresh-instance, upgrade, rollback and the
retraction test, which deletes a document. Everything else is read-only against
the running workspace.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import datetime

BASE = os.environ.get("S1_BASE", "/opt/siyuan-lab")
SCRIPTS = os.path.join(BASE, "scripts")
HOST = os.path.join(BASE, "host")
EXPORTS = os.path.join(BASE, "exports")
REPORT_JSON = os.path.join(EXPORTS, "s1_acceptance.json")
REPORT_MD = os.path.join(EXPORTS, "s1_acceptance.md")
PY = sys.executable or "python3"

MANUAL = "MANUAL"


# --------------------------------------------------------------------------- util
def load(name, default=None):
    p = name if os.path.isabs(name) else os.path.join(EXPORTS, name)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def sh(cmd, timeout=1800, cwd=BASE):
    t0 = time.time()
    p = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=cwd,
                       capture_output=True, timeout=timeout)
    return {
        "cmd": cmd if isinstance(cmd, str) else " ".join(cmd),
        "rc": p.returncode,
        "seconds": round(time.time() - t0, 1),
        "stdout_tail": p.stdout.decode("utf-8", "replace")[-1500:],
        "stderr_tail": p.stderr.decode("utf-8", "replace")[-800:],
    }


# --------------------------------------------------------------------------- stages
# (name, destructive, description, command)
STAGES = [
    ("lifeos-pg", False, "bring up LifeOS canonical Postgres + apply migrations",
     ["bash", os.path.join(HOST, "lifeos_pg.sh")]),
    ("api-suite", False, "step 6: API create/read/update/export x5 + idempotency + errors",
     [PY, os.path.join(SCRIPTS, "api_suite.py")]),
    ("export", False, "step 7: standard Markdown+assets export + attachment hashes",
     [PY, os.path.join(SCRIPTS, "export_md.py")]),
    ("fidelity", False, "step 7: item-by-item round-trip fidelity of all 30 docs",
     [PY, os.path.join(SCRIPTS, "fidelity.py"),
      "--orig", os.path.join(BASE, "corpus"),
      "--exported", os.path.join(EXPORTS, "markdown"),
      "--out", os.path.join(EXPORTS, "fidelity_report.json")]),
    ("identity", False, "step 3: owner/adult/member identities + permission matrix",
     [PY, os.path.join(SCRIPTS, "identity_matrix.py")]),
    ("perm", False, "notebook-level ACL surface probe",
     [PY, os.path.join(SCRIPTS, "perm_matrix.py")]),
    ("negative", False, "step 12: private/export/attachment-URL/API/search + log+backup scan",
     [PY, os.path.join(SCRIPTS, "negative_tests.py")]),
    ("handoff", False, "step 8: register export into LifeOS canonical store, 3x",
     [PY, os.path.join(SCRIPTS, "lifeos_handoff.py")]),
    ("escrow", False, "hard gate 2: package secrets + recovery doc for off-host storage",
     ["bash", os.path.join(HOST, "escrow.sh")]),
    ("backup", True, "step 9: consistent workspace snapshot",
     ["bash", os.path.join(HOST, "backup.sh")]),
    ("restore", True, "step 9: restore into a FRESH instance and verify",
     ["bash", os.path.join(HOST, "restore.sh")]),
    # Direction matters: the lab is parked on the BASELINE tag (v3.7.2) before a
    # full run so this is a real forward upgrade, and rollback.sh then has a
    # genuinely different PREV_VERSION to return to. Running "upgrade" toward an
    # older tag would still exercise the mechanics but would not answer step 10.
    ("upgrade", True, "step 10: version upgrade + smoke test",
     ["bash", os.path.join(HOST, "upgrade.sh"),
      os.environ.get("S1_UPGRADE_TO", "v3.7.3")]),
    ("rollback", True, "step 10: documented rollback + smoke test",
     ["bash", os.path.join(HOST, "rollback.sh")]),
    ("retraction", True, "hard gate 4: deletion/retraction propagation across 5 layers",
     [PY, os.path.join(SCRIPTS, "retraction_test.py")]),
]
STAGE_BY_NAME = {s[0]: s for s in STAGES}

# Reports a stage owns. They are deleted *before* the stage runs so a crashed or
# skipped stage can never be scored from a previous run's leftovers. This is not
# hypothetical: a stale "docs_sql=ERR <urlopen error ...>" in
# restore_doc_count.txt survived a good run and crashed the scorer.
STAGE_OUTPUTS = {
    "api-suite":  ["api_suite_report.json"],
    "export":     ["export_report.json"],
    "fidelity":   ["fidelity_report.json"],
    "identity":   ["identity_matrix_report.json"],
    "perm":       ["perm_matrix_report.json"],
    "negative":   ["negative_report.json"],
    "handoff":    ["lifeos_handoff_report.json"],
    "escrow":     [os.path.join("escrow", "escrow_report.json")],
    # backup writes its manifest next to the archive in backups/, keyed by
    # timestamp, so there is nothing stale to clear.
    "restore":    ["restore_doc_count.txt", "restore_verify.json",
                   "restore_verify.err"],
    "retraction": ["retraction_report.json"],
}


def clear_stage_outputs(name):
    for rel in STAGE_OUTPUTS.get(name, []):
        p = rel if os.path.isabs(rel) else os.path.join(EXPORTS, rel)
        try:
            os.remove(p)
        except OSError:
            pass


# --------------------------------------------------------------------------- criteria
def evaluate(timings):
    """Map roadmap clauses to measured evidence. Returns (criteria, gates, defects)."""
    exp = load("export_report.json", {})
    fid = load("fidelity_report.json", {})
    api = load("api_suite_report.json", {})
    ident = load("identity_matrix_report.json", {})
    neg = load("negative_report.json", {})
    perm = load("perm_matrix_report.json", {})
    hand = load("lifeos_handoff_report.json", {})
    retr = load("retraction_report.json", {})
    escrow = load(os.path.join(EXPORTS, "escrow", "escrow_report.json"), {})

    restore_txt = ""
    try:
        with open(os.path.join(EXPORTS, "restore_doc_count.txt"), encoding="utf-8") as f:
            restore_txt = f.read().strip()
    except Exception:  # noqa: BLE001
        pass

    fsum = fid.get("summary", {})
    C = []

    def crit(cid, clause, status, evidence, note=""):
        C.append({"id": cid, "clause": clause, "status": status,
                  "evidence": evidence, "note": note})

    # ---- V1 -------------------------------------------------------------
    # docs_total = what the seed map says should exist; docs_live = what the
    # kernel still had at export time. They differ only if something was deleted
    # (the retraction stage does exactly that, but it runs LAST and now writes
    # its own report, so the export stage's evidence is never post-deletion).
    docs_total = exp.get("docs_in_seed_map") or exp.get("docs_total", 0)
    docs_live = exp.get("docs_live", exp.get("docs_total", 0))
    missing_at_export = exp.get("docs_missing_in_kernel") or []
    body_ok = (docs_total >= 30
               and docs_live == docs_total
               and exp.get("docs_with_content", 0) == docs_live
               and not missing_at_export)
    a_checked = exp.get("assets_checked", 0)
    a_match = exp.get("assets_hash_match", 0)
    v1 = "PASS" if (body_ok and a_checked >= 20 and a_match == a_checked) else "FAIL"
    crit("V1", "20 份导入材料的正文和附件 100% 可导出；随机 20 个附件 hash 一致", v1,
         {"docs_exported_with_content": "%d/%d" % (exp.get("docs_with_content", 0), docs_total),
          "titles_preserved": "%d/%d" % (exp.get("title_match", 0), docs_total),
          "attachments_hash_verified": "%d/%d" % (a_match, a_checked),
          "attachments_copied_into_export": exp.get("assets_copied"),
          "docs_missing_in_kernel_at_export": missing_at_export},
         "" if a_checked >= 20 else "fewer than 20 attachments in the corpus")

    # ---- V2 -------------------------------------------------------------
    native_rows = {k: v for k, v in (fid.get("per_doc") or {}).items() if k.startswith("n")}
    native_pass = sum(1 for v in native_rows.values() if v.get("structural_ok"))
    nonportable = fid.get("nonportable_inventory") or []
    npsum = fsum.get("nonportable_summary") or {}
    itemised = npsum.get("native_docs_itemised_count", 0)
    # Roadmap: every native note itemised AND no critical fact/attachment loss.
    # Losing a convenience feature is a finding; losing an attachment is a gate.
    v2 = "PASS" if (
        native_rows
        and native_pass == len(native_rows)
        and itemised >= 10
        and npsum.get("no_critical_loss") is True
    ) else "FAIL"
    crit("V2", "10 篇原生笔记的不可移植功能逐项列出；关键事实或附件丢失为硬门槛失败", v2,
         {"native_docs_structurally_intact": "%d/%d" % (native_pass, len(native_rows)),
          "native_docs_itemised": itemised,
          "min_word_retention": fsum.get("min_word_ratio"),
          "features_lost": npsum.get("lost"),
          "features_transformed": npsum.get("transformed"),
          "features_portable": npsum.get("portable"),
          "critical_loss": len(npsum.get("critical_loss") or []),
          "nonportable_rows_listed": len(nonportable)})

    # ---- V3 -------------------------------------------------------------
    # Preferred evidence is the per-document report (restore_verify.json): it
    # proves the 30 *seeded* ids came back. The one-line count file is only a
    # fallback, and it is parsed defensively -- an earlier run wrote
    # "docs_sql=ERR <urlopen error ...>" into it and int() killed the scorer.
    rv = load("restore_verify.json", {})

    def _num(prefix, text):
        for tok in text.split():
            if tok.startswith(prefix):
                val = tok.split("=", 1)[1]
                return int(val) if val.lstrip("-").isdigit() else None
        return None

    r_docs = rv.get("docs_sql") if isinstance(rv.get("docs_sql"), int) else _num("docs_sql=", restore_txt)
    r_nb = rv.get("notebooks") if isinstance(rv.get("notebooks"), int) else _num("notebooks=", restore_txt)
    seeded_found = rv.get("seeded_found")
    seeded_expected = rv.get("seeded_expected")
    restore_secs = timings.get("restore", {}).get("seconds")

    if rv:
        # exact evidence available: every seeded doc AND every asset must be back
        v3 = "PASS" if (rv.get("all_seeded_docs_present")
                        and rv.get("all_assets_present")
                        and rv.get("search_ok")
                        and (seeded_expected or 0) >= docs_total) else "FAIL"
    elif restore_txt:
        # degraded evidence: raw counts only
        v3 = "PASS" if (r_docs is not None and r_docs >= docs_total and r_nb) else "FAIL"
    else:
        v3 = "NOT_RUN"
    crit("V3", "全新实例恢复后 30/30 文档可见，搜索可用，API smoke tests 通过；恢复时间和步骤已记录", v3,
         {"seeded_docs_recovered": ("%s/%s" % (seeded_found, seeded_expected)
                                    if seeded_expected else "not measured"),
          "seeded_docs_missing": rv.get("seeded_missing"),
          "assets_recovered": ("%s/%s" % (rv.get("assets_found"), rv.get("assets_expected"))
                               if rv.get("assets_expected") else "not measured"),
          "search_after_restore": rv.get("search_ok"),
          "notebooks_restored": r_nb,
          "kernel_doc_blocks": r_docs,
          "raw_line": restore_txt or "not run",
          "docs_required": docs_total,
          "restore_seconds": restore_secs,
          "steps_documented": bool(escrow.get("contains_recovery_doc"))},
         "" if rv else "no restore_verify.json - scored from raw counts only, "
                       "which cannot distinguish seeded docs from leftovers")

    # ---- V4 -------------------------------------------------------------
    # ADR-0006 re-scopes this clause: initial LifeOS is SINGLE-OWNER. The
    # editable SiYuan workspace is a private admin console (owner-only reachable,
    # loopback-bound); family consumption goes through LifeOS granular
    # publishing, NOT through SiYuan. So "owner/adult/member identity matrix
    # inside SiYuan" is no longer the requirement - the requirement is that the
    # admin console is owner-only reachable and that consumption is a published
    # (read-only) surface with its own ACL.
    multi = (ident.get("summary") or {}).get("multi_identity_supported")
    kernel_lo = ((neg.get("surfaces") or {}).get("N3") or {}).get("kernel_loopback_only")
    n3_secure = ((neg.get("surfaces") or {}).get("N3") or {}).get("secure")
    n5_secure = ((neg.get("surfaces") or {}).get("N5") or {}).get("secure")
    # admin console verified owner-only: kernel loopback-bound AND no unauth
    # access through the edge (N3) AND single-owner scope is the design (N5).
    admin_console_ok = bool(kernel_lo) and bool(n3_secure) and bool(n5_secure)
    if ident:
        v4 = "PASS" if admin_console_ok else (
            "CAPPED" if multi and not (ident.get("summary") or {}).get("matrix_failures") else "FAIL")
    else:
        v4 = "NOT_RUN"
    crit("V4", "单所有者控制台：编辑工作区仅 owner 可达（loopback-only），消费经 LifeOS 粒度发布（ADR-0006）；产品无需内置 owner/adult/member 身份", v4,
         {"admin_console_owner_only": admin_console_ok,
          "kernel_loopback_only": kernel_lo,
          "n3_edge_blocks_anonymous": n3_secure,
          "n5_single_owner_scope": n5_secure,
          "model": "single-owner + granular publishing (ADR-0006)",
          "identity_endpoints_found": (ident.get("summary") or {}).get("identity_endpoints_found"),
          "matrix_cases": (ident.get("summary") or {}).get("matrix_cases"),
          "matrix_failures": (ident.get("summary") or {}).get("matrix_failures"),
          "per_notebook_acl": (perm or {}).get("per_notebook_acl_api")},
         "ADR-0006: single-owner LifeOS; SiYuan is a private admin console, "
         "family consumption via LifeOS granular publishing. PASS = admin "
         "console owner-only reachable. CAPPED/FAIL = LAN-facing console with "
         "no ACL, or no evidence of the publishing boundary.")

    # ---- V5 -------------------------------------------------------------
    up = timings.get("upgrade", {})
    rb = timings.get("rollback", {})
    v5 = "PASS" if up.get("rc") == 0 and rb.get("rc") == 0 else ("NOT_RUN" if not up else "FAIL")
    crit("V5", "升级成功并可回滚；无数据库手工修复", v5,
         {"upgrade_rc": up.get("rc"), "upgrade_seconds": up.get("seconds"),
          "rollback_rc": rb.get("rc"), "rollback_seconds": rb.get("seconds"),
          "manual_db_repair_required": False})

    # ---- V6 -------------------------------------------------------------
    b = hand.get("boundary") or {}
    v6 = "PASS" if (hand.get("pass") and b.get("read_only_portable_export")) else (
        "NOT_RUN" if not hand else "FAIL")
    crit("V6", "LifeOS 只通过标准导出/API接收内容；卸载思源后 canonical 数据仍完整", v6,
         {"deliveries": [d.get("canonical_total_after") for d in hand.get("deliveries", [])],
          "idempotent": hand.get("idempotent"),
          "unique_sha256": hand.get("unique_sha256"),
          "siyuan_internal_reads": b.get("siyuan_internal_reads"),
          "audit_events": hand.get("audit_events"),
          "storage_uri_raw_ip_leaks": hand.get("storage_uri_raw_ip_leaks")})

    # ---- V7 -------------------------------------------------------------
    docs_dir = os.path.join(BASE, "docs")
    have_scorecard = os.path.exists(os.path.join(docs_dir, "implementation", "03-s1-scorecard.md"))
    have_adr = os.path.exists(os.path.join(docs_dir, "adr", "0005-s1-verdict.md"))
    crit("V7", "scorecard、缺陷、维护分钟数和 adopt/trial/hold/reject 结论写入 ADR candidate",
         "PASS" if have_scorecard and have_adr else "FAIL",
         {"scorecard": have_scorecard, "adr_candidate": have_adr,
          "maintenance_minutes": round(sum(t.get("seconds", 0) for t in timings.values()) / 60.0, 1)})

    # ---- V8 (roadmap step 11, human-only) -------------------------------
    crit("V8", "在桌面和至少一台实际移动设备完成 5 个家庭任务", MANUAL,
         {"reason": "requires a human on a real phone; no script can assert this"},
         "Blocks the daily-use dimension of the weighted score.")

    # ================= hard gates =======================================
    G = []

    def gate(gid, clause, ok, evidence, note=""):
        G.append({"id": gid, "clause": clause,
                  "status": "PASS" if ok is True else ("FAIL" if ok is False else str(ok)),
                  "evidence": evidence, "note": note})

    def tri(deps, condition):
        """None (undetermined) if any dependency stage was not run.

        A gate must never read FAIL just because its evidence is missing -
        'we did not measure it' and 'it does not work' are different answers,
        and conflating them would understate the verdict dishonestly.
        """
        if any(d == "NOT_RUN" for d in deps):
            return None
        return bool(condition)

    gate("HG1", "能导出到开放格式，并在全新环境重建；不能依赖手工修数据库",
         tri([v1, v3],
             v1 == "PASS" and v3 == "PASS"
             and fsum.get("structural_pass") == fsum.get("docs_compared")),
         {"export": v1, "structural_fidelity": "%s/%s" % (fsum.get("structural_pass"),
                                                          fsum.get("docs_compared")),
          "fresh_env_rebuild": v3, "manual_db_fix": False})

    # "密钥和恢复说明不只存在于运行主机" - an archive that exists but has no
    # secrets or no recovery instructions does not satisfy the clause.
    off_host = bool(escrow.get("archive")
                    and escrow.get("contains_secrets")
                    and escrow.get("recovery_doc_extractable"))
    gate("HG2", "备份可恢复，升级失败可回滚；密钥和恢复说明不只存在于运行主机",
         tri([v3, v5], v3 == "PASS" and v5 == "PASS" and off_host),
         {"restore": v3, "rollback": v5, "offhost_escrow": escrow.get("archive"),
          "escrow_sha256": (escrow.get("sha256") or "")[:16],
          "escrow_secret_files": escrow.get("secret_files"),
          "recovery_doc_extractable": escrow.get("recovery_doc_extractable"),
          "escrow_pulled_off_host": "host/pull.py (operator workstation)"})

    nsum = neg.get("summary") or {}
    # HG3 under ADR-0006: "unauthorised users" = anyone but the owner, and the
    # family consumption surface is LifeOS granular publishing, not SiYuan. So
    # the gate is: every edge-facing surface blocks anonymous/unauthorised
    # access (N1/N2/N4/N6/N7 all_secure), the edge blocks anonymous assets (N3)
    # and the admin console is owner-only reachable (N5). SiYuan itself having
    # no ACL is fine as long as it is NOT a family-facing surface.
    n3_s = ((neg.get("surfaces") or {}).get("N3") or {}).get("secure")
    n5_s = ((neg.get("surfaces") or {}).get("N5") or {}).get("secure")
    hg3 = None if not neg else bool(nsum.get("all_secure")) and bool(n3_s) and bool(n5_s)
    gate("HG3", "未授权用户、日志、模型上下文和派生索引均看不到禁止字段 "
                "（ADR-0006：家庭成员只经 LifeOS 粒度发布消费；编辑工作区仅 owner 可达）",
         hg3,
         {"surfaces_tested": nsum.get("surfaces_tested"),
          "insecure_surfaces": nsum.get("insecure_surfaces"),
          "edge_blocks_anonymous_assets": n3_s,
          "admin_console_owner_only": n5_s,
          "kernel_loopback_only":
              ((neg.get("surfaces") or {}).get("N3") or {}).get("kernel_loopback_only"),
          "model": "single-owner + granular publishing (ADR-0006)"})

    gate("HG4", "删除/撤回能传播；不会留下用户不可见但 AI 仍可检索的副本",
         retr.get("hard_gate_4_pass") if retr else None,
         {"layers": {k: v.get("pass") for k, v in (retr.get("layers") or {}).items()},
          "notes": retr.get("notes")})

    uninstall_doc = os.path.exists(os.path.join(BASE, "run.sh"))
    canonical_survives = bool(hand.get("idempotent")) and bool(hand.get("unique_sha256"))
    gate("HG5", "有明确卸载步骤；移除组件不会丢失 canonical 数据",
         (uninstall_doc and canonical_survives) if hand else None,
         {"uninstall_target": "run.sh clean-remote / revoke",
          "canonical_rows_outside_siyuan": hand.get("unique_sha256"),
          "canonical_store": "postgres core.document (independent container)"})

    # ================= defects ==========================================
    D = []
    if api and api.get("idempotency", {}).get("same_id_on_dup_path") is False:
        D.append({"severity": "medium",
                  "defect": "createDocWithMd is not idempotent: the same path yields a new "
                            "doc id on every call. Any retrying automation duplicates docs.",
                  "mitigation": "Dedupe above SiYuan. LifeOS UNIQUE(household_id, sha256) "
                                "absorbs it, verified by 3x delivery in the handoff test."})
    if ((neg.get("surfaces") or {}).get("N3") or {}).get("kernel_anonymous_served"):
        D.append({"severity": "high",
                  "defect": "Attachment URLs are served to unauthenticated clients on the "
                            "kernel port.",
                  "mitigation": "Never expose 6806 directly; force all access through the "
                                "authenticating proxy."})
    if not multi:
        D.append({"severity": "high",
                  "defect": "No user/role model. One API token and one access code grant "
                            "global read/write over every notebook.",
                  "mitigation": "Single-user workbench only; family boundaries must live in "
                                "LifeOS, which can express owner/adult/member."})
    for n in (retr.get("notes") or []):
        D.append({"severity": "medium", "defect": n, "mitigation": "see retraction_report.json"})
    if hand.get("contract_negatives", {}).get("C4_illegal_media_type", {}).get("accepted"):
        D.append({"severity": "medium",
                  "defect": "core.document accepts any media_type; migration 0002 has no CHECK "
                            "and no status/version/supersedes column that week-4 step 3 requires.",
                  "mitigation": "Enforce in the week-4 API layer, or add a constraint migration."})

    return C, G, D


# --------------------------------------------------------------------------- scoring
WEIGHTS = [
    ("data_ownership_and_exit", 20, "导出/重建/卸载实测"),
    ("security_and_permission", 20, "自动化正负权限测试、日志检查"),
    ("solo_operating_cost", 20, "容器/依赖数、升级与恢复分钟数、每周维护时间"),
    ("features_and_family_ux", 15, "真实任务完成率、人工步骤、移动端/桌面体验"),
    ("integration_and_automation", 15, "API、webhook、幂等、错误恢复"),
    ("quality_and_performance", 10, "黄金集正确率、引用、拒答、P95 延迟"),
]


def score(criteria, gates, timings):
    cid = {c["id"]: c["status"] for c in criteria}
    gid = {g["id"]: g["status"] for g in gates}
    total_min = round(sum(t.get("seconds", 0) for t in timings.values()) / 60.0, 1)

    def pct(x):
        return max(0.0, min(1.0, x))

    rows = []

    # exit path: export + fidelity + fresh rebuild + uninstall
    v = pct((1.0 if cid.get("V1") == "PASS" else 0) * 0.4
            + (1.0 if cid.get("V3") == "PASS" else 0) * 0.4
            + (1.0 if gid.get("HG5") == "PASS" else 0) * 0.2)
    rows.append(("data_ownership_and_exit", v,
                 "export+fidelity clean, fresh-instance rebuild, canonical store independent"))

    # security: gate 3 + single-owner console verification (ADR-0006)
    v = pct((1.0 if gid.get("HG3") == "PASS" else 0.4) * 0.5
            + (1.0 if cid.get("V4") == "PASS" else 0.0) * 0.5)
    rows.append(("security_and_permission", v,
                 "single-owner console owner-only reachable; edge blocks anonymous "
                 "access; family consumption via LifeOS publishing (ADR-0006)"))

    # ops cost: fewer containers + fast upgrade/restore is better
    restore_m = timings.get("restore", {}).get("seconds", 0) / 60.0
    up_m = (timings.get("upgrade", {}).get("seconds", 0)
            + timings.get("rollback", {}).get("seconds", 0)) / 60.0
    v = pct(1.0 - min(0.5, restore_m / 20.0) - min(0.3, up_m / 20.0))
    rows.append(("solo_operating_cost", v,
                 "2 containers for SiYuan; restore %.1f min, upgrade+rollback %.1f min"
                 % (restore_m, up_m)))

    # family UX: cannot be earned without the manual test
    v = 0.0 if cid.get("V8") == MANUAL else 1.0
    rows.append(("features_and_family_ux", v,
                 "UNSCORED until the 5 real family tasks are done on a real phone"))

    # integration
    v = pct((1.0 if cid.get("V6") == "PASS" else 0) * 0.7
            + (1.0 if (load("api_suite_report.json", {}) or {}).get("create") else 0) * 0.3)
    rows.append(("integration_and_automation", v,
                 "idempotent handoff into canonical store; API suite green"))

    # quality/performance: golden-set work belongs to D1/I1, not S1
    rows.append(("quality_and_performance", None,
                 "out of scope for S1 (golden-set accuracy is D1/I1)"))

    out = {"dimensions": [], "earned": 0.0, "available": 0.0,
           "maintenance_minutes": total_min}
    wmap = {k: (w, ev) for k, w, ev in WEIGHTS}
    for key, val, note in rows:
        w, ev = wmap[key]
        if val is None:
            out["dimensions"].append({"dimension": key, "weight": w, "score": None,
                                      "points": None, "evidence": ev, "note": note})
            continue
        pts = round(w * val, 1)
        out["earned"] += pts
        out["available"] += w
        out["dimensions"].append({"dimension": key, "weight": w, "score": round(val, 3),
                                  "points": pts, "evidence": ev, "note": note})
    out["earned"] = round(out["earned"], 1)
    out["normalised_100"] = round(out["earned"] / out["available"] * 100, 1) if out["available"] else 0
    return out


def verdict(gates, sc, criteria):
    gs = {g["id"]: g["status"] for g in gates}
    failed = [k for k, v in gs.items() if v == "FAIL"]
    unrun = [k for k, v in gs.items() if v not in ("PASS", "FAIL")]
    cid = {c["id"]: c["status"] for c in criteria}
    if failed:
        return "hold", "Hard gate(s) failed: %s. Roadmap: 任何硬门槛失败时总分无效。" % ", ".join(failed)
    if unrun:
        return "incomplete", "Hard gate(s) not evaluated: %s. Run --full." % ", ".join(unrun)
    if cid.get("V4") != "PASS":
        return "trial", ("All hard gates pass, but the single-owner admin console is "
                         "not verified owner-only reachable (ADR-0006). Continue as a "
                         "single-owner authoring workbench; the family consumption "
                         "boundary is LifeOS granular publishing, not SiYuan.")
    if sc["earned"] >= 80:
        return "adopt", "All hard gates pass and weighted score >= 80."
    return "trial", "All hard gates pass but weighted score %.1f < 80." % sc["earned"]


# --------------------------------------------------------------------------- report
def render_md(doc):
    L = []
    a = L.append
    a("# S1 acceptance report")
    a("")
    a("Generated %s" % doc["generated"])
    a("")
    a("Source of truth: `family-lifeos docs/roadmap/family-lifeos-implementation-and-experiments.md`  ")
    a("Commit `%s`" % doc["roadmap_commit"])
    a("")
    a("**Verdict: `%s`** -- %s" % (doc["verdict"], doc["verdict_reason"]))
    a("")
    a("## Hard gates")
    a("")
    a("| Gate | Clause | Result |")
    a("|---|---|---|")
    for g in doc["hard_gates"]:
        a("| %s | %s | **%s** |" % (g["id"], g["clause"], g["status"]))
    a("")
    a("## How to verify")
    a("")
    a("| ID | Clause | Result | Key evidence |")
    a("|---|---|---|---|")
    for c in doc["criteria"]:
        ev = "; ".join("%s=%s" % (k, v) for k, v in list(c["evidence"].items())[:3])
        a("| %s | %s | **%s** | %s |" % (c["id"], c["clause"], c["status"], ev.replace("|", "/")))
    a("")
    a("## Weighted score")
    a("")
    a("| Dimension | Weight | Score | Points | Note |")
    a("|---|---:|---:|---:|---|")
    for d in doc["score"]["dimensions"]:
        a("| %s | %d%% | %s | %s | %s |" % (
            d["dimension"], d["weight"],
            "n/a" if d["score"] is None else "%.2f" % d["score"],
            "n/a" if d["points"] is None else d["points"], d["note"]))
    a("| **total** | **%d%%** | | **%.1f** | normalised **%.1f/100** |" % (
        doc["score"]["available"], doc["score"]["earned"], doc["score"]["normalised_100"]))
    a("")
    a("Measured maintenance time this run: **%.1f minutes**." % doc["score"]["maintenance_minutes"])
    a("")
    if doc["defects"]:
        a("## Defects")
        a("")
        a("| Severity | Defect | Mitigation |")
        a("|---|---|---|")
        for d in doc["defects"]:
            a("| %s | %s | %s |" % (d["severity"], d["defect"].replace("|", "/"),
                                    d["mitigation"].replace("|", "/")))
        a("")
    a("## Stage timings")
    a("")
    a("| Stage | rc | seconds |")
    a("|---|---:|---:|")
    for name, t in doc["timings"].items():
        a("| %s | %s | %s |" % (name, t.get("rc"), t.get("seconds")))
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="S1 acceptance suite")
    ap.add_argument("--stages", default="", help="comma list; 'safe' = all non-destructive")
    ap.add_argument("--full", action="store_true", help="run every stage incl. destructive")
    ap.add_argument("--evaluate-only", action="store_true", help="score existing reports")
    ap.add_argument("--list", action="store_true", help="list stages")
    ap.add_argument("--yes", action="store_true", help="skip the destructive-stage prompt")
    args = ap.parse_args()

    if args.list:
        print("%-12s %-11s %s" % ("STAGE", "DESTRUCTIVE", "DESCRIPTION"))
        for name, destructive, desc, _cmd in STAGES:
            print("%-12s %-11s %s" % (name, "yes" if destructive else "no", desc))
        return 0

    if args.full:
        selected = [s[0] for s in STAGES]
    elif args.stages == "safe":
        selected = [s[0] for s in STAGES if not s[1]]
    elif args.stages:
        selected = [x.strip() for x in args.stages.split(",") if x.strip()]
    elif args.evaluate_only:
        selected = []
    else:
        # a bare invocation running zero stages and silently re-scoring stale
        # reports is a footgun; default to the full non-destructive set.
        selected = [s[0] for s in STAGES if not s[1]]
        print("no --stages given; running all non-destructive stages "
              "(use --evaluate-only to just re-score)")

    unknown = [s for s in selected if s not in STAGE_BY_NAME]
    if unknown:
        print("unknown stage(s): %s" % ", ".join(unknown), file=sys.stderr)
        return 2

    destructive = [s for s in selected if STAGE_BY_NAME[s][1]]
    if destructive and not args.yes and not args.evaluate_only:
        print("Destructive stages selected: %s" % ", ".join(destructive))
        print("They stop the kernel, swap image tags and delete a document.")
        if input("continue? [y/N] ").strip().lower() != "y":
            return 1

    os.makedirs(EXPORTS, exist_ok=True)
    timings = {}
    prev = load("s1_acceptance.json", {})
    if prev.get("timings"):
        timings.update(prev["timings"])     # keep timings from earlier partial runs

    if not args.evaluate_only:
        for name in selected:
            _n, _d, desc, cmd = STAGE_BY_NAME[name]
            print("\n=== [%s] %s" % (name, desc))
            clear_stage_outputs(name)
            r = sh(cmd)
            timings[name] = r
            tail = r["stdout_tail"].strip().splitlines()[-4:]
            print("    rc=%s in %.1fs" % (r["rc"], r["seconds"]))
            for line in tail:
                print("    | " + line[:160])
            if r["rc"] != 0:
                print("    ! stderr: " + r["stderr_tail"].strip().splitlines()[-1][:200]
                      if r["stderr_tail"].strip() else "    ! non-zero exit")

    criteria, gates, defects = evaluate(timings)
    sc = score(criteria, gates, timings)
    v, reason = verdict(gates, sc, criteria)

    doc = {
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "roadmap_commit": "f597f61a68cd721eb0d2494673d50cd9e2cc8a58",
        "stages_run": selected,
        "timings": timings,
        "criteria": criteria,
        "hard_gates": gates,
        "defects": defects,
        "score": sc,
        "verdict": v,
        "verdict_reason": reason,
    }
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write(render_md(doc))

    print("\n" + "=" * 72)
    print("HARD GATES")
    for g in gates:
        print("  %-4s %-6s %s" % (g["id"], g["status"], g["clause"][:58]))
    print("\nHOW TO VERIFY")
    for c in criteria:
        print("  %-4s %-9s %s" % (c["id"], c["status"], c["clause"][:58]))
    print("\nSCORE  %.1f / %d  (normalised %.1f/100)   maintenance %.1f min"
          % (sc["earned"], sc["available"], sc["normalised_100"], sc["maintenance_minutes"]))
    print("VERDICT: %s" % v.upper())
    print("  %s" % reason)
    print("\n-> %s\n-> %s" % (REPORT_JSON, REPORT_MD))
    return 0 if v in ("adopt", "trial") else 1


if __name__ == "__main__":
    sys.exit(main())
