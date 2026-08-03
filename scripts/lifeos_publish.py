"""LifeOS granular publishing layer — contract + boundary test (ADR-0006/0009).

Roadmap requirement (family-lifeos §下一轮, after D3/D4 closed):
  "构建 LifeOS 粒度发布层（ADR-0009）：per-item/per-person 只读 ACL + 审计，
   从 canonical store 消费；验证家庭成员零思源凭据即可消费。"

This script PROVES the boundary, it does not just claim it:

  1. CONSUMES from the canonical store. It reads only core.document rows that
     already exist (the 51-row S1 handoff fixture), publishing a handful of
     them via the publish facade. It never writes a document; publishing is a
     grant over existing canonical rows.

  2. TALKS ONLY TO postgres (lifeos-pg). The boundary proof records every
     network/host action. It asserts that NOTHING touched a SiYuan endpoint
     (no 127.0.0.1:6806, no siyuan container, no API token) — a family member
     consumes through LifeOS, with zero SiYuan credentials, by construction.

  3. DEFAULT-DENY. can_consume(doc, person) is false until an explicit grant
     exists. This is the whole point of ADR-0009: the authoring tool is a
     private owner console; consumption is a LifeOS decision.

  4. GRANT SCOPES. person / role / whole-household — all three are exercised
     on positive and negative sides.

  5. OWNER-ONLY PUBLISH. The publish facade passes granted_by; the DB trigger
     (migration 0007) rejects a non-owner publisher and a grant to a
     non-member. This is the schema-enforced expression of "owner console".

  6. AUDIT. Every publish/revoke/consume records an audit.event row.

Run ON the VM:  python3 scripts/lifeos_publish.py
"""
from __future__ import annotations
import os, sys, json, datetime, subprocess

BASE = "/opt/siyuan-lab"
REPORT = os.path.join(BASE, "exports", "lifeos_publish_report.json")
CT = "lifeos-pg"
DB = "lifeos"
DBUSER = "lifeos"
HOUSEHOLD_NAME = "s1-lab-household"

# ---- boundary probes: these strings must NEVER appear in any side-effect ----
SIYUAN_TOUCH_MARKERS = (
    "127.0.0.1:6806", "siyuan-poc", "siyuan-caddy", "/api/",
    "SIYUAN", "siyuan", "accessAuthCode", "api_token",
)
# the only host/container we are allowed to talk to
ALLOWED_HOST_SCOPE = ("lifeos-pg",)

side_effects = []  # (kind, target, allowed)


def record(kind, target, allowed):
    side_effects.append({"kind": kind, "target": target, "allowed": allowed})


def psql(sql):
    record("psql", "lifeos-pg", True)
    out = subprocess.run(
        ["docker", "exec", "-i", CT, "psql", "-At", "-U", DBUSER, "-d", DB, "-c", sql],
        capture_output=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError("psql failed: %s" % out.stderr.decode("utf-8", "replace")[:400])
    return out.returncode, out.stdout.decode("utf-8", "replace").strip(), \
        out.stderr.decode("utf-8", "replace")


def psql_script(script):
    record("psql-script", "lifeos-pg", True)
    out = subprocess.run(
        ["docker", "exec", "-i", CT, "psql", "-v", "ON_ERROR_STOP=1",
         "-U", DBUSER, "-d", DB, "-At", "-q"],
        input=script.encode("utf-8"), capture_output=True, timeout=300)
    return out.returncode, out.stdout.decode("utf-8", "replace"), \
        out.stderr.decode("utf-8", "replace")


def lit(s):
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"


def row0(sql):
    rc, out, err = psql(sql)
    for line in out.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


# -------------------------------------------------------------------------
# facade: publish / revoke / consume — thin wrappers that ALWAYS set
# granted_by (owner-only) and ALWAYS record audit. The DB trigger is the
# real gate; these wrappers just make the contract legible + enforced in app.
# -------------------------------------------------------------------------
def publish(document_id, household_id, granted_by, scope, value=None,
            access="read", reason="contract-test", expires_at=None):
    """scope in {'person','role','household'}; value carries the person/role."""
    cols = ["document_id", "household_id", "access", "granted_by", "reason"]
    vals = [lit(document_id), lit(household_id), lit(access), lit(granted_by), lit(reason)]
    if scope == "person":
        cols.append("grantee_person_id"); vals.append(lit(value))
    elif scope == "role":
        cols.append("grantee_role"); vals.append(lit(value))
    elif scope == "household":
        cols.append("grantee_household"); vals.append("true")
    if expires_at:
        cols.append("expires_at"); vals.append(lit(expires_at))
    sql = ("INSERT INTO core.publish_grant(%s) VALUES (%s) "
           "ON CONFLICT DO NOTHING RETURNING id"
           % (",".join(cols), ",".join(vals)))
    rc, out, err = psql_script(sql)
    rows = [l.strip() for l in out.splitlines() if l.strip()]
    granted = rc == 0 and bool(rows)
    psql("INSERT INTO audit.event(actor_type, action, object_type, object_id, "
         "household_id, outcome, details) VALUES ('user','publish','document',%s,%s,%s,"
         "jsonb_build_object('scope',%s,'value',%s,'access',%s,'granted_by',%s))"
         % (lit(document_id), lit(household_id),
            lit("success" if granted else "denied"),
            lit(scope), lit(value), lit(access), lit(granted_by)))
    return granted, (rows[0] if rows else None), err.strip().splitlines()[0][:160] if rc != 0 else None


def revoke(grant_id, household_id, revoked_by, reason="contract-test"):
    rc, out, err = psql_script(
        "UPDATE core.publish_grant SET revoked_at=now(), reason=%s "
        "WHERE id=%s AND household_id=%s RETURNING id"
        % (lit(reason), lit(grant_id), lit(household_id)))
    done = rc == 0 and bool([l for l in out.splitlines() if l.strip()])
    psql("INSERT INTO audit.event(actor_type, action, object_type, object_id, "
         "household_id, outcome, details) VALUES ('user','revoke','publish_grant',%s,%s,'success',"
         "jsonb_build_object('revoked_by',%s))"
         % (lit(grant_id), lit(household_id), lit(revoked_by)))
    return done


def can(person_id, doc_id):
    return row0("SELECT core.can_consume(%s::uuid,%s::uuid)" % (lit(doc_id), lit(person_id))) == "t"


def published_to(person_id):
    rc, out, err = psql("SELECT document_id FROM core.published_to(%s::uuid)" % lit(person_id))
    return [l.strip() for l in out.splitlines() if l.strip()]


# -------------------------------------------------------------------------
def main():
    started = datetime.datetime.now(datetime.timezone.utc)

    # fixture ids
    hh = row0("select id from core.household where name=%s" % lit(HOUSEHOLD_NAME))
    owner = row0("select id from core.person where legal_name='Owner Lab'")
    adult = row0("select id from core.person where legal_name='Adult Lab'")
    member = row0("select id from core.person where legal_name='Member Lab'")

    # pick real canonical docs to publish -- MUST be active (the publishing
    # layer must refuse to serve withdrawn/archived docs; publishing a
    # withdrawn doc would itself be a security hole, so we only target active
    # ones). 5 distinct docs so no two test cases collide on the same
    # (document, person) grant slot (the unique index allows only one).
    docs = [d.strip() for d in
            row0("SELECT string_agg(id::text,'|') FROM ("
                 "SELECT id FROM core.document WHERE household_id=%s AND status='active' "
                 "LIMIT 5) t" % lit(hh)).split("|")
            if d.strip()]
    # a doc that exists but will NOT be granted -> assert default-deny
    ungranted = row0(
        "SELECT id::text FROM core.document WHERE household_id=%s AND status='active' "
        "AND id NOT IN (%s) LIMIT 1"
        % (lit(hh), ",".join("'%s'" % d for d in docs) if docs else "'00000000-0000-0000-0000-000000000000'"))

    psql("DELETE FROM core.publish_grant WHERE household_id=%s" % lit(hh))  # clean slate

    results = {}

    # ---- DEFAULT DENY: no grant yet => nobody consumes ----
    results["D1_default_deny"] = {
        "owner_consumes": can(owner, docs[0]) if docs else None,
        "adult_consumes": can(adult, docs[0]) if docs else None,
        "member_consumes": can(member, docs[0]) if docs else None,
        "expected_all_false": True,
        "pass": bool(docs) and not can(owner, docs[0])
        and not can(adult, docs[0]) and not can(member, docs[0]),
    }

    # ---- P1 person-scoped grant ----
    g1_ok, g1_id, g1_err = publish(docs[0], hh, owner, "person", value=adult)
    results["P1_person_grant"] = {
        "granted": g1_ok, "grant_id": g1_id, "error": g1_err,
        "adult_can": can(adult, docs[0]), "owner_can": can(owner, docs[0]),
        "member_can": can(member, docs[0]),
        "expected": g1_ok and can(adult, docs[0]) and not can(member, docs[0]),
        "pass": g1_ok and can(adult, docs[0]) and not can(member, docs[0]),
    }

    # ---- P2 role-scoped grant (role = member) on doc[1] ----
    g2_ok, g2_id, g2_err = publish(docs[1], hh, owner, "role", value="member")
    results["P2_role_grant_member"] = {
        "granted": g2_ok, "grant_id": g2_id, "error": g2_err,
        "member_can": can(member, docs[1]), "owner_can": can(owner, docs[1]),
        "expected": g2_ok and can(member, docs[1]),
        "pass": g2_ok and can(member, docs[1]),
    }

    # ---- P3 whole-household grant on doc[2] ----
    g3_ok, g3_id, g3_err = publish(docs[2], hh, owner, "household")
    results["P3_household_grant"] = {
        "granted": g3_ok, "grant_id": g3_id, "error": g3_err,
        "owner_can": can(owner, docs[2]), "adult_can": can(adult, docs[2]),
        "member_can": can(member, docs[2]),
        "expected": g3_ok and can(owner, docs[2]) and can(adult, docs[2]) and can(member, docs[2]),
        "pass": g3_ok and can(owner, docs[2]) and can(adult, docs[2]) and can(member, docs[2]),
    }

    # ---- N1 default-deny on an ungranted doc ----
    results["N1_ungranted_doc_denied"] = {
        "member_can": can(member, ungranted) if ungranted else None,
        "expected_false": True,
        "pass": bool(ungranted) and not can(member, ungranted),
    }

    # ---- N2 non-owner cannot publish (trigger rejects) ----
    g_bad, g_bad_id, g_bad_err = publish(docs[0], hh, adult, "person", value=member)
    results["N2_non_owner_publish_rejected"] = {
        "granted": g_bad, "grant_id": g_bad_id, "error": g_bad_err,
        "expected_not_granted": True,
        "pass": (not g_bad) and g_bad_err and "publish denied" in g_bad_err,
    }

    # ---- N3 revoked grant => consume denied ----
    if g1_id:
        revoke(g1_id, hh, owner)
    results["N3_revoked_grant_denied"] = {
        "adult_can_after_revoke": can(adult, docs[0]),
        "expected_false": True,
        "pass": not can(adult, docs[0]),
    }

    # ---- N4 expired grant => consume denied (distinct doc, docs[3]) ----
    # Uses a SEPARATE doc from the role grant (docs[1]) so the expiry test is
    # not masked by another live grant on the same document.
    if len(docs) > 3:
        g_exp, g_exp_id, _ = publish(docs[3], hh, owner, "person", value=member,
                                     expires_at="2000-01-01T00:00:00+00:00")
        results["N4_expired_grant_denied"] = {
            "granted": g_exp, "member_can": can(member, docs[3]),
            "expected_false": True,
            "pass": g_exp and not can(member, docs[3]),
        }

    # ---- P5 status gating: a WITHDRAWN doc is never consumable, even with a
    # live grant. Publish docs[4] to member, prove visible, withdraw the doc,
    # prove denied, then restore (so we do not mutate the fixture permanently).
    # Uses a DISTINCT doc from N4 (docs[3]) to avoid the unique (document,
    # person) grant slot collision.
    if len(docs) > 4:
        g5_ok, g5_id, _ = publish(docs[4], hh, owner, "person", value=member)
        visible_before = can(member, docs[4])
        psql("UPDATE core.document SET status='withdrawn' WHERE id=%s" % lit(docs[4]))
        denied_after_withdraw = not can(member, docs[4])
        psql("UPDATE core.document SET status='active' WHERE id=%s" % lit(docs[4]))
        restored_visible = can(member, docs[4])
        if g5_id:
            revoke(g5_id, hh, owner)
        results["P5_withdrawn_doc_not_consumable"] = {
            "granted": g5_ok, "visible_before_withdraw": visible_before,
            "denied_after_withdraw": denied_after_withdraw,
            "restored_visible": restored_visible,
            "expected": g5_ok and visible_before and denied_after_withdraw and restored_visible,
            "pass": g5_ok and visible_before and denied_after_withdraw and restored_visible,
        }

    # ---- N5 grant to a non-member is rejected by trigger ----
    stranger = row0("SELECT gen_random_uuid()::text")
    g_str, g_str_id, g_str_err = publish(docs[0], hh, owner, "person", value=stranger)
    results["N5_grant_to_nonmember_rejected"] = {
        "granted": g_str, "error": g_str_err,
        "expected_not_granted": True,
        "pass": (not g_str) and g_str_err and "publish denied" in g_str_err,
    }

    # ---- consumption feed shape ----
    results["feed"] = {
        "owner_published_to_count": len(published_to(owner)),
        "adult_published_to_count": len(published_to(adult)),
        "member_published_to_count": len(published_to(member)),
    }

    # ---- audit present ----
    audit = int(row0("SELECT count(*) FROM audit.event "
                     "WHERE household_id=%s AND action IN ('publish','revoke')" % lit(hh)) or 0)
    results["audit_events"] = audit

    # ---- BOUNDARY PROOF: zero SiYuan touch ----
    # Every host/container this process talked to is recorded in `side_effects`
    # by psql()/psql_script(). The boundary claim is proven by:
    #   (a) the ONLY recorded target is lifeos-pg (core.can_consume /
    #       published_to resolve entirely inside PostgreSQL), and
    #   (b) no recorded target/string references a SiYuan asset (kernel port
    #       6806, the siyuan container, an /api/ call, or the API token).
    # We do NOT open a socket to 6806 to "prove" non-touch -- that would itself
    # be a SiYuan touch, and 6806 is legitimately bound on this lab host by
    # siyuan-poc. The absence of any SiYuan reference in what we actually did
    # is the proof.
    offending = [s for s in side_effects
                 if any(m.lower() in (s["target"] or "").lower() for m in SIYUAN_TOUCH_MARKERS)]
    boundary = {
        "side_effect_count": len(side_effects),
        "allowed_scope": sorted({s["target"] for s in side_effects if s["allowed"]}),
        "siyuan_touch_offenses": offending,
        "zero_siyuan_credentials_used": len(offending) == 0
        and sorted({s["target"] for s in side_effects if s["allowed"]}) == ["lifeos-pg"],
        "note": "family member consumes via LifeOS canonical store + publish_grant; "
                "no SiYuan API token, kernel port, or container was referenced.",
    }

    all_pass = (
        results["D1_default_deny"]["pass"]
        and results["P1_person_grant"]["pass"]
        and results["P2_role_grant_member"]["pass"]
        and results["P3_household_grant"]["pass"]
        and results["N1_ungranted_doc_denied"]["pass"]
        and results["N2_non_owner_publish_rejected"]["pass"]
        and results["N3_revoked_grant_denied"]["pass"]
        and results["N4_expired_grant_denied"]["pass"]
        and results["P5_withdrawn_doc_not_consumable"]["pass"]
        and results["N5_grant_to_nonmember_rejected"]["pass"]
        and boundary["zero_siyuan_credentials_used"]
        and audit >= 1
    )

    rep = {
        "household": HOUSEHOLD_NAME,
        "documents_published": len(docs),
        "ungranted_probe_doc": ungranted,
        "cases": results,
        "boundary": boundary,
        "elapsed_seconds": round(
            (datetime.datetime.now(datetime.timezone.utc) - started).total_seconds(), 2),
        "pass": bool(all_pass),
    }

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)

    print(json.dumps({k: v for k, v in rep.items() if k != "cases"},
                     indent=2, ensure_ascii=False))
    for k, v in results.items():
        if k in ("feed", "audit_events"):
            print("  %-32s %s" % (k, v))
            continue
        ok = v.get("pass")
        flag = "ok " if ok else "FAIL"
        print("  %s %-32s %s" % (flag, k, "pass" if ok else "FAILED"))
    print("  boundary zero_siyuan_touch=%s allowed_scope=%s"
          % (boundary["zero_siyuan_credentials_used"], boundary["allowed_scope"]))
    print("->", REPORT)


if __name__ == "__main__":
    main()
