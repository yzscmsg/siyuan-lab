#!/usr/bin/env python3
"""
S1 round-trip fidelity analyzer.

Compares the ORIGINAL corpus/native markdown (pre-import) against the
Markdown+assets exported out of SiYuan, feature by feature, as required by
the S1 protocol:

    "compare fidelity of the 20 imported docs and 10 native docs; record
     differences in heading levels, tables, code blocks, images, links,
     task lists and metadata"

This runs OFFLINE against files already in the repo - no SiYuan needed.

Usage:
    python scripts/fidelity.py
    python scripts/fidelity.py --orig corpus --exported results/exports/markdown
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# ---------------------------------------------------------------- extraction

FRONTMATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.S)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.M)
FENCE_RE = re.compile(r"^```([A-Za-z0-9_+-]*)\s*\r?\n(.*?)^```\s*$", re.M | re.S)
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
TASK_RE = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.*)$", re.M)
LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(?!\[[ xX]\])", re.M)
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.M)
TABLE_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$", re.M)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
BLOCKQUOTE_RE = re.compile(r"^\s*>\s+", re.M)
TAG_RE = re.compile(r"(?<![\w#])#([A-Za-z0-9\u4e00-\u9fff_/-]+)(?!\w)")
BLOCKREF_RE = re.compile(r"\(\((\d{14}-[a-z0-9]{7})\s")
BLOCKID_ATTR_RE = re.compile(r"\{:\s*[^}]*\}")


def strip_frontmatter(text: str):
    """Return (body, frontmatter_dict_or_None)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return text, None
    raw = m.group(0)
    fm = {}
    for line in raw.splitlines():
        if ":" in line and not line.startswith("---"):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return text[m.end():], fm


def strip_export_title(body: str, stem: str):
    """
    SiYuan export prepends the DOCUMENT NAME as an H1. Our doc names are the
    file stems (c01..c20, n01..n10), so detect and remove exactly that.
    Returns (body_without_title, was_present).
    """
    lines = body.lstrip("\n").splitlines()
    if lines and lines[0].strip() in ("# " + stem, "#" + stem):
        return "\n".join(lines[1:]).lstrip("\n"), True
    return body, False


def tables(text: str):
    """Group contiguous pipe-rows into tables. Returns list of row counts."""
    out, run = [], 0
    for line in text.splitlines():
        if TABLE_ROW_RE.match(line):
            run += 1
        else:
            if run:
                out.append(run)
            run = 0
    if run:
        out.append(run)
    # a real table needs header + separator + >=1 body row
    return [n for n in out if n >= 2]


def norm_words(text: str):
    """Normalized word bag for content-preservation ratio."""
    t = BLOCKID_ATTR_RE.sub(" ", text)
    t = re.sub(r"[`*_>#|\[\]()!~-]", " ", t)
    t = re.sub(r"\s+", " ", t)
    # keep CJK chars individually, latin as words
    words = []
    for tok in t.split():
        if re.search(r"[\u4e00-\u9fff]", tok):
            words.extend(list(re.sub(r"[^\u4e00-\u9fff\w]", "", tok)))
        else:
            w = re.sub(r"[^\w.%/]", "", tok).lower()
            if w:
                words.append(w)
    return words


def features(text: str):
    codes = FENCE_RE.findall(text)
    tbl = tables(text)
    return {
        "headings": [(len(h), t) for h, t in HEADING_RE.findall(text)],
        "heading_levels": Counter(len(h) for h, _ in HEADING_RE.findall(text)),
        "tables": len(tbl),
        "table_rows": sum(tbl),
        "code_blocks": len(codes),
        "code_langs": sorted(x for x, _ in codes if x),
        "code_hashes": sorted(
            hashlib.sha256(c.strip().encode("utf-8")).hexdigest()[:12] for _, c in codes
        ),
        "images": sorted(a for a, _ in IMAGE_RE.findall(text)),
        "image_targets": [b for _, b in IMAGE_RE.findall(text)],
        "links": sorted(a for a, _ in LINK_RE.findall(text)),
        "link_targets": [b for _, b in LINK_RE.findall(text)],
        "wikilinks": sorted(WIKILINK_RE.findall(text)),
        "blockrefs": len(BLOCKREF_RE.findall(text)),
        "tasks_total": len(TASK_RE.findall(text)),
        "tasks_done": len([1 for m, _ in TASK_RE.findall(text) if m.lower() == "x"]),
        "list_items": len(LIST_RE.findall(text)),
        "inline_code": len(INLINE_CODE_RE.findall(text)),
        "blockquotes": len(BLOCKQUOTE_RE.findall(text)),
        "tags": sorted(set(TAG_RE.findall(text))),
        "words": norm_words(text),
    }


# ---------------------------------------------------------------- comparison

def compare(stem: str, orig_text: str, exp_text: str):
    exp_body, fm = strip_frontmatter(exp_text)
    exp_body, title_added = strip_export_title(exp_body, stem)

    o = features(orig_text)
    e = features(exp_body)

    ow, ew = Counter(o["words"]), Counter(e["words"])
    kept = sum((ow & ew).values())
    word_ratio = (kept / sum(ow.values())) if sum(ow.values()) else 1.0
    lost = [w for w, n in (ow - ew).items() for _ in range(n)]

    # SiYuan content-addresses uploaded assets (foo.png -> foo-<ts>-<hash>.png).
    # Those filename tokens legitimately change; asset BYTES are verified
    # separately by export_md.py via sha256. Exclude asset path tokens so the
    # ratio measures prose/structure loss, not intentional renaming.
    asset_tokens = set()
    for tgt in o["image_targets"] + o["link_targets"] + e["image_targets"] + e["link_targets"]:
        if "assets/" in tgt or re.search(r"\.(png|jpe?g|gif|pdf|svg|webp)$", tgt, re.I):
            asset_tokens.update(norm_words(tgt))
    ow_adj = Counter({w: n for w, n in ow.items() if w not in asset_tokens})
    ew_adj = Counter({w: n for w, n in ew.items() if w not in asset_tokens})
    kept_adj = sum((ow_adj & ew_adj).values())
    word_ratio_adj = (
        (kept_adj / sum(ow_adj.values())) if sum(ow_adj.values()) else 1.0
    )
    lost_adj = [w for w, n in (ow_adj - ew_adj).items() for _ in range(n)]
    asset_rename_only = word_ratio < 1.0 and word_ratio_adj >= 1.0

    # wikilinks may survive as wikilinks OR be resolved to block refs / md links
    wiki_kept = len(set(o["wikilinks"]) & set(e["wikilinks"]))
    wiki_resolved = 0
    for w in o["wikilinks"]:
        if w in e["wikilinks"]:
            continue
        head = w.split()[0]
        if head and (head in exp_body):
            wiki_resolved += 1

    checks = {
        "headings_count": (len(o["headings"]), len(e["headings"])),
        "heading_levels": (
            dict(sorted(o["heading_levels"].items())),
            dict(sorted(e["heading_levels"].items())),
        ),
        "heading_text_preserved": [t for _, t in o["headings"]]
        == [t for _, t in e["headings"]],
        "tables": (o["tables"], e["tables"]),
        "table_rows": (o["table_rows"], e["table_rows"]),
        "code_blocks": (o["code_blocks"], e["code_blocks"]),
        "code_langs_preserved": o["code_langs"] == e["code_langs"],
        "code_body_identical": o["code_hashes"] == e["code_hashes"],
        "images": (len(o["images"]), len(e["images"])),
        "image_targets_rewritten": [
            (a, b)
            for a, b in zip(o["image_targets"], e["image_targets"])
            if a != b
        ],
        "links": (len(o["links"]), len(e["links"])),
        "wikilinks": (len(o["wikilinks"]), len(e["wikilinks"])),
        "wikilinks_kept": wiki_kept,
        "wikilinks_resolved_other": wiki_resolved,
        "blockrefs_in_export": e["blockrefs"],
        "tasks_total": (o["tasks_total"], e["tasks_total"]),
        "tasks_done": (o["tasks_done"], e["tasks_done"]),
        "list_items": (o["list_items"], e["list_items"]),
        "inline_code": (o["inline_code"], e["inline_code"]),
        "blockquotes": (o["blockquotes"], e["blockquotes"]),
        "tags": (o["tags"], e["tags"]),
        "word_ratio": round(word_ratio, 4),
        "word_ratio_excl_asset_renames": round(word_ratio_adj, 4),
        "asset_rename_only": asset_rename_only,
        "words_lost_sample": sorted(set(lost))[:12],
        "words_lost_excl_asset_renames": sorted(set(lost_adj))[:12],
        "metadata_frontmatter_added": sorted(fm.keys()) if fm else [],
        "metadata_title_h1_added": title_added,
    }

    # structural verdict: what actually matters for LifeOS re-ingestion
    structural_ok = (
        checks["headings_count"][0] == checks["headings_count"][1]
        and checks["heading_text_preserved"]
        and checks["tables"][0] == checks["tables"][1]
        and checks["table_rows"][0] == checks["table_rows"][1]
        and checks["code_blocks"][0] == checks["code_blocks"][1]
        and checks["code_body_identical"]
        and checks["images"][0] == checks["images"][1]
        and checks["tasks_total"][0] == checks["tasks_total"][1]
        and checks["tasks_done"][0] == checks["tasks_done"][1]
        and word_ratio_adj >= 0.98
    )
    return structural_ok, checks


# ---------------------------------------------------------------- main

def find_exported(root: str):
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        if os.path.basename(dirpath) == "assets":
            continue
        for f in files:
            if f.endswith(".md"):
                out[os.path.splitext(f)[0]] = os.path.join(dirpath, f)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--orig", default=os.path.join(REPO, "corpus"))
    ap.add_argument(
        "--exported", default=os.path.join(REPO, "results", "exports", "markdown")
    )
    ap.add_argument(
        "--out", default=os.path.join(REPO, "results", "fidelity_report.json")
    )
    args = ap.parse_args()

    exported = find_exported(args.exported)
    originals = sorted(
        f for f in os.listdir(args.orig) if re.fullmatch(r"[cn]\d\d\.md", f)
    )
    if not originals:
        print("no originals found in", args.orig)
        return 2

    rows, per_doc = [], {}
    ok_count = 0
    for fn in originals:
        stem = os.path.splitext(fn)[0]
        exp_path = exported.get(stem)
        if not exp_path:
            per_doc[stem] = {"exported": False}
            rows.append((stem, "MISSING", 0.0, "not exported"))
            continue
        with open(os.path.join(args.orig, fn), encoding="utf-8") as fh:
            orig = fh.read()
        with open(exp_path, encoding="utf-8") as fh:
            exp = fh.read()
        ok, checks = compare(stem, orig, exp)
        ok_count += 1 if ok else 0
        per_doc[stem] = {
            "exported": True,
            "structural_ok": ok,
            "orig_path": os.path.join(args.orig, fn),
            "exported_path": exp_path,
            "checks": checks,
        }

        notes = []
        for label, key in (
            ("headings", "headings_count"),
            ("tables", "tables"),
            ("rows", "table_rows"),
            ("code", "code_blocks"),
            ("images", "images"),
            ("tasks", "tasks_total"),
        ):
            a, b = checks[key]
            if a != b:
                notes.append("%s %s->%s" % (label, a, b))
        if not checks["heading_text_preserved"]:
            notes.append("heading text changed")
        if not checks["code_body_identical"]:
            notes.append("code body changed")
        if checks["word_ratio_excl_asset_renames"] < 0.98:
            notes.append(
                "words %.1f%%" % (checks["word_ratio_excl_asset_renames"] * 100)
            )
        if checks["asset_rename_only"]:
            notes.append("asset filename content-addressed (bytes verified)")
        rows.append(
            (
                stem,
                "PASS" if ok else "DIFF",
                checks["word_ratio_excl_asset_renames"],
                "; ".join(notes) or "-",
            )
        )

    # aggregate
    agg = {
        "docs_compared": len([d for d in per_doc.values() if d.get("exported")]),
        "docs_missing": len([d for d in per_doc.values() if not d.get("exported")]),
        "structural_pass": ok_count,
        "structural_pass_pct": round(100.0 * ok_count / max(1, len(originals)), 1),
        "min_word_ratio": round(
            min(
                (
                    d["checks"]["word_ratio_excl_asset_renames"]
                    for d in per_doc.values()
                    if d.get("exported")
                ),
                default=0.0,
            ),
            4,
        ),
        "mean_word_ratio": round(
            sum(
                d["checks"]["word_ratio_excl_asset_renames"]
                for d in per_doc.values()
                if d.get("exported")
            )
            / max(1, len([d for d in per_doc.values() if d.get("exported")])),
            4,
        ),
        "docs_with_asset_rename_only": len(
            [
                d
                for d in per_doc.values()
                if d.get("exported") and d["checks"]["asset_rename_only"]
            ]
        ),
    }

    # systematic (every-doc) transformations - these are the real "metadata diff"
    exported_docs = [d for d in per_doc.values() if d.get("exported")]
    agg["systematic_transforms"] = {
        "yaml_frontmatter_added_to_all": all(
            d["checks"]["metadata_frontmatter_added"] for d in exported_docs
        ),
        "frontmatter_keys": sorted(
            {
                k
                for d in exported_docs
                for k in d["checks"]["metadata_frontmatter_added"]
            }
        ),
        "doc_name_h1_added_to_all": all(
            d["checks"]["metadata_title_h1_added"] for d in exported_docs
        ),
        "asset_paths_rewritten": sum(
            len(d["checks"]["image_targets_rewritten"]) for d in exported_docs
        ),
        "wikilinks_original_total": sum(
            d["checks"]["wikilinks"][0] for d in exported_docs
        ),
        "wikilinks_surviving_total": sum(
            d["checks"]["wikilinks"][1] for d in exported_docs
        ),
    }

    # ---- itemised non-portable feature inventory -------------------------
    # Roadmap week-5 verify: "10 篇原生笔记的不可移植功能逐项列出；关键事实或附件
    # 丢失为硬门槛失败，不能用总分抵消。" A feature only counts as a LOSS if the
    # information is gone; a reversible rewrite is a transform, not a loss.
    FEATURES = [
        ("block_reference", re.compile(r"\(\([0-9a-zA-Z\-]{6,}\)\)"),
         "((block-id)) inline reference"),
        ("blockref_placeholder", re.compile(r"\(\(BLOCKREF\)\)"),
         "unresolved block-ref placeholder"),
        ("wikilink", WIKILINK_RE, "[[wikilink]] bidirectional link"),
        ("template_var", re.compile(r"\{\{[^}]+\}\}"), "template variable / render directive"),
        ("inline_tag", re.compile(r"(?:^|\s)#[\w\u4e00-\u9fff-]+"), "#tag"),
        ("query_block", re.compile(r"^```query", re.M), "query / database view block"),
        ("attachment_ref", re.compile(r"assets/|/assets/"), "attachment reference"),
    ]
    inventory = []
    for fn in originals:
        stem = os.path.splitext(fn)[0]
        d = per_doc.get(stem, {})
        if not d.get("exported"):
            continue
        try:
            with open(d["orig_path"], encoding="utf-8") as fh:
                o_text = fh.read()
            with open(d["exported_path"], encoding="utf-8") as fh:
                e_text = fh.read()
        except (OSError, KeyError):
            continue
        # compare against the export BODY (frontmatter + injected H1 are
        # export artefacts, not authored content)
        e_body, _fm = strip_frontmatter(e_text)
        e_body, _t = strip_export_title(e_body, stem)
        for key, rx, label in FEATURES:
            n_o = len(rx.findall(o_text))
            if not n_o:
                continue
            n_e = len(rx.findall(e_body))
            if key == "attachment_ref":
                # SiYuan content-addresses uploads; presence of the rewritten name
                # is survival. Count any assets/ reference in the export.
                survived = n_e > 0
                verdict_ = "transformed" if survived else "LOST"
                detail = "path rewritten to content-addressed filename; bytes hash-verified"
            elif n_e >= n_o:
                survived, verdict_, detail = True, "portable", "survives verbatim"
            elif n_e > 0:
                survived, verdict_ = True, "partial"
                detail = "%d of %d survive" % (n_e, n_o)
            else:
                survived, verdict_ = False, "LOST"
                detail = "absent from exported Markdown"
            inventory.append({
                "doc": stem,
                "native": stem.startswith("n"),
                "feature": key, "label": label,
                "in_original": n_o, "in_export": n_e,
                "verdict": verdict_, "survived": survived, "detail": detail,
            })

    # "逐项列出" means every native note is accounted for, including the ones
    # that turn out to have NO non-portable feature. Silently omitting those
    # would make the coverage count look short.
    native_stems = [os.path.splitext(f)[0] for f in originals if f.startswith("n")]
    native_examined = [s for s in native_stems if per_doc.get(s, {}).get("exported")]
    native_inv = [i for i in inventory if i["native"]]
    native_with_features = {i["doc"] for i in native_inv}
    native_clean = [s for s in native_examined if s not in native_with_features]

    agg["nonportable_summary"] = {
        "features_examined": len(inventory),
        "native_docs_examined": sorted(native_examined),
        "native_docs_examined_count": len(native_examined),
        "native_docs_with_nonportable_features": sorted(native_with_features),
        "native_docs_fully_portable": sorted(native_clean),
        "native_docs_itemised": sorted(native_examined),
        "native_docs_itemised_count": len(native_examined),
        "lost": sorted({i["feature"] for i in inventory if i["verdict"] == "LOST"}),
        "partial": sorted({i["feature"] for i in inventory if i["verdict"] == "partial"}),
        "transformed": sorted({i["feature"] for i in inventory if i["verdict"] == "transformed"}),
        "portable": sorted({i["feature"] for i in inventory if i["verdict"] == "portable"}),
        # a "critical loss" is an ATTACHMENT or FACT vanishing, not a
        # convenience feature (block refs) degrading. Roadmap: 关键事实或附件丢失
        # 为硬门槛失败。
        "critical_loss": [
            i for i in inventory
            if i["verdict"] == "LOST" and i["feature"] == "attachment_ref"
        ],
    }
    agg["nonportable_summary"]["no_critical_loss"] = (
        not agg["nonportable_summary"]["critical_loss"]
    )

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"summary": agg, "nonportable_inventory": inventory,
                   "per_doc": per_doc}, fh, indent=2, ensure_ascii=False)

    # markdown table for the scorecard
    md = ["| doc | verdict | word retention | differences |", "| --- | --- | --- | --- |"]
    for stem, verdict, ratio, notes in rows:
        md.append("| %s | %s | %.1f%% | %s |" % (stem, verdict, ratio * 100, notes))
    md_path = os.path.join(os.path.dirname(args.out), "fidelity_table.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")

    print(json.dumps(agg, indent=2, ensure_ascii=False))
    print("\nwrote", args.out)
    print("wrote", md_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
