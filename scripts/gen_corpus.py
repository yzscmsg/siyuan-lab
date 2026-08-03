"""Generate the S1 corpus: 20 import docs + 10 native-note drafts + assets + manifest.

Deterministic (fixed seed) so pre-import sha256 in manifest/ can be compared
against post-export content to prove round-trip fidelity (S1 hard gate:
"20 imported materials 100% exportable; random 20 attachment hashes match").

Outputs (under siyuan-lab/corpus/):
  c01..c20.md      import corpus (zh / en / bilingual; tables, image, PDF, long-form, links)
  n01..n10.md      native-note drafts (block ref, wikilink, tag, template, query/DB view)
  assets/sample-chart.png, assets/sample-doc.pdf
  manifest.yaml    sha256 of every .md + asset, plus feature tags
"""
from __future__ import annotations
import os, hashlib, zlib, struct, random

ROOT = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(ROOT, "..", "corpus")
ASSETS = os.path.join(CORPUS, "assets")
os.makedirs(ASSETS, exist_ok=True)

random.seed(20260803)

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

# ---------- binary assets ----------
def make_png(path, w=64, h=64, rgb=(40, 90, 200)):
    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    def ihdr():
        return struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b""
    for y in range(h):
        raw += b"\x00" + bytes(rgb) * w
    idat = zlib.compress(raw)
    sig = b"\x89PNG\r\n\x1a\n"
    png = sig + chunk(b"IHDR", ihdr()) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)

def make_pdf(path, title="Sample PDF Attachment"):
    content = (
        "%PDF-1.4\n"
        "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        "4 0 obj<</Length 110>>stream\nBT /F1 18 Tf 72 700 Td (%s) Tj ET\nBT /F1 12 Tf 72 680 Td (A short PDF used as a SiYuan attachment in S1.) Tj ET\nendstream endobj\n"
        "5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        "xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000101 00000 n \n0000000200 00000 n \n0000000348 00000 n \ntrailer<</Size 6/Root 1 0 R>>\nstartxref\n448\n%%EOF\n"
    ).replace("%s", title)
    with open(path, "wb") as f:
        f.write(content.encode("latin-1"))

def make_svg(path, label="s1", rgb=(200, 90, 40)):
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60" viewBox="0 0 120 60">'
        '<rect width="120" height="60" fill="rgb(%d,%d,%d)"/>'
        '<text x="10" y="35" font-family="sans-serif" font-size="16" fill="#ffffff">%s</text>'
        "</svg>\n" % (rgb[0], rgb[1], rgb[2], label)
    )
    with open(path, "wb") as f:
        f.write(svg.encode("utf-8"))


def make_csv(path, name="dataset", rows=12):
    lines = ["id,name,category,amount_sgd,recorded_on"]
    for i in range(1, rows + 1):
        lines.append(
            "%d,%s-%02d,%s,%.2f,2026-0%d-%02d"
            % (i, name, i, ["utility", "medical", "school", "insurance"][i % 4],
               round(random.uniform(10, 900), 2), (i % 9) + 1, (i % 28) + 1)
        )
    with open(path, "wb") as f:
        f.write(("\n".join(lines) + "\n").encode("utf-8"))


def make_txt(path, title="Plain text attachment"):
    body = (
        "%s\n%s\n\n"
        "This plain-text attachment exercises non-image, non-PDF binary handling in\n"
        "the SiYuan asset pipeline. It contains CJK to catch encoding regressions:\n"
        "中文附件内容：备份、恢复、导出、回滚。\n"
    ) % (title, "=" * len(title))
    with open(path, "wb") as f:
        f.write(body.encode("utf-8"))


def make_json(path, kind="metadata"):
    import json as _json
    payload = {
        "kind": kind,
        "household": "lab-household",
        "retention_class": "standard-7y",
        "classification": "internal",
        "note": "S1 attachment fixture 附件",
    }
    with open(path, "wb") as f:
        f.write((_json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


# 22 attachments so the roadmap check "随机 20 个附件 hash 一致" has a real population.
ASSET_SPECS = [
    ("sample-chart.png",   lambda p: make_png(p, 64, 64, (40, 90, 200))),
    ("sample-doc.pdf",     lambda p: make_pdf(p, "Sample PDF Attachment")),
    ("diagram-arch.png",   lambda p: make_png(p, 96, 48, (30, 140, 110))),
    ("diagram-flow.png",   lambda p: make_png(p, 48, 96, (150, 60, 160))),
    ("photo-scan-01.png",  lambda p: make_png(p, 128, 80, (90, 90, 90))),
    ("photo-scan-02.png",  lambda p: make_png(p, 80, 128, (170, 120, 40))),
    ("receipt-2026-01.png", lambda p: make_png(p, 72, 100, (210, 210, 210))),
    ("receipt-2026-02.png", lambda p: make_png(p, 100, 72, (60, 60, 120))),
    ("policy-terms.pdf",   lambda p: make_pdf(p, "Household Policy Terms")),
    ("medical-report.pdf", lambda p: make_pdf(p, "Annual Medical Report")),
    ("school-notice.pdf",  lambda p: make_pdf(p, "School Term Notice")),
    ("expenses-2026q1.csv", lambda p: make_csv(p, "expense", 14)),
    ("inventory.csv",      lambda p: make_csv(p, "item", 9)),
    ("readings.csv",       lambda p: make_csv(p, "reading", 20)),
    ("notes-plain.txt",    lambda p: make_txt(p, "Plain notes")),
    ("recovery-steps.txt", lambda p: make_txt(p, "Recovery steps 恢复步骤")),
    ("changelog.txt",      lambda p: make_txt(p, "Changelog")),
    ("icon-family.svg",    lambda p: make_svg(p, "family", (200, 90, 40))),
    ("icon-private.svg",   lambda p: make_svg(p, "private", (40, 120, 200))),
    ("meta-doc.json",      lambda p: make_json(p, "document-metadata")),
    ("meta-retention.json", lambda p: make_json(p, "retention-policy")),
    ("archive-manifest.json", lambda p: make_json(p, "archive-manifest")),
]

for _name, _fn in ASSET_SPECS:
    _fn(os.path.join(ASSETS, _name))

PNG = os.path.join(ASSETS, "sample-chart.png")
PDF = os.path.join(ASSETS, "sample-doc.pdf")

# Which doc references which extra attachment (beyond the two already inline
# in c01 / c16 / n05). Keeps every asset reachable from exported Markdown so
# the export walker actually has to carry all 22.
ATTACH_MAP = {
    "c02": ["diagram-arch.png"],
    "c03": ["diagram-flow.png"],
    "c04": ["photo-scan-01.png"],
    "c05": ["photo-scan-02.png"],
    "c07": ["receipt-2026-01.png"],
    "c08": ["receipt-2026-02.png"],
    "c09": ["policy-terms.pdf"],
    "c10": ["medical-report.pdf"],
    "c11": ["school-notice.pdf"],
    "c12": ["expenses-2026q1.csv"],
    "c13": ["inventory.csv"],
    "c14": ["readings.csv"],
    "c15": ["notes-plain.txt"],
    "c17": ["recovery-steps.txt"],
    "c18": ["changelog.txt"],
    "c19": ["icon-family.svg"],
    "c20": ["icon-private.svg"],
    "n06": ["meta-doc.json"],
    "n07": ["meta-retention.json"],
    "n09": ["archive-manifest.json"],
}

IMAGE_EXT = (".png", ".svg")


def attachment_section(names):
    lines = ["", "## 附件 / Attachments", ""]
    for n in names:
        if n.lower().endswith(IMAGE_EXT):
            lines.append("![%s](assets/%s)" % (n, n))
        else:
            lines.append("[%s](assets/%s)" % (n, n))
        lines.append("")
    return "\n".join(lines)

# ---------- corpus docs ----------
def table(rows):
    head, *body = rows
    out = "| " + " | ".join(head) + " |\n"
    out += "| " + " | ".join("---" for _ in head) + " |\n"
    for r in body:
        out += "| " + " | ".join(r) + " |\n"
    return out

corpus = {}
# EN
corpus["c01"] = ("EN article + table", """# Quarterly Operations Review (EN)

This note records the quarterly operations review for the family workspace.

## Summary
- Headcount: 4
- Open items: 12
- Blocked: 2

## Metrics
%s

## Notes
The review cadence should stay monthly. See [[c06 中文运营复盘]] for the Chinese mirror.
""" % table([["Metric","Q1","Q2"],["Revenue","1.2","1.4"],["Cost","0.8","0.9"]]))

corpus["c02"] = ("EN long-form", "# Long-form Essay on Knowledge Hygiene\n\n" + "\n".join(
    f"Paragraph {i}: knowledge hygiene means treating notes as living assets that can be exported, "
    f"restored, and audited. Block {i} emphasizes that ownership of data must never depend on a single vendor.\n"
    for i in range(1, 41)))

corpus["c03"] = ("EN + image embed", """# Architecture Diagram (EN)

The deployment uses a kernel behind a reverse proxy.

![architecture chart](assets/sample-chart.png)

The chart shows the kernel (6806) fronted by Caddy (443, internal TLS).
""")

corpus["c04"] = ("EN + code", "# API Snippet (EN)\n\nUse the token header:\n\n```python\nimport urllib.request\nreq = urllib.request.Request(url, headers={'Authorization': 'Token <token>'})\n```\n")

corpus["c05"] = ("EN + internal link", "# Index (EN)\n\n- [[c01 Quarterly Operations Review]]\n- [[n01 Welcome Note]]\n")

# ZH
corpus["c06"] = ("ZH 运营复盘 + 表格", """# 中文运营复盘

本笔记记录家庭工作台的季度运营复盘。

## 摘要
- 成员：4 人
- 待办：12 项
- 受阻：2 项

## 指标
%s

## 备注
复盘节奏保持每月一次。英文镜像见 [[c01 Quarterly Operations Review]]。
""" % table([["指标","第一季度","第二季度"],["收入","1.2","1.4"],["成本","0.8","0.9"]]))

corpus["c07"] = ("ZH 长文", "# 知识卫生中文长文\n\n" + "\n".join(
    f"第{i}段：知识卫生意味着把笔记当作可导出、可恢复、可审计的活资产。第{i}块强调数据所有权不能依赖单一厂商。\n"
    for i in range(1, 41)))

corpus["c08"] = ("ZH + 图片", """# 架构图（中文）

部署采用反向代理前置内核。

![架构图](assets/sample-chart.png)

图中内核（6806）由 Caddy（443，内部 TLS）前置。
""")

corpus["c09"] = ("ZH + 代码", "# 接口片段（中文）\n\n使用 token 头：\n\n```python\nreq = urllib.request.Request(url, headers={'Authorization': 'Token <token>'})\n```\n")

corpus["c10"] = ("ZH + 内部链接", "# 索引（中文）\n\n- [[c06 中文运营复盘]]\n- [[n02 模板示例]]\n")

# Bilingual
corpus["c11"] = ("Bilingual intro", "# 介绍 / Introduction\n\n这是家庭知识库的实验入口。This is the experimental entry point of the family knowledge base.\n\n目标 / Goal: 验证思源是否值得作为工作台。Validate whether SiYuan is worth adopting as a workbench.\n")
corpus["c12"] = ("Bilingual policy", "# 隐私政策 / Privacy Policy\n\n我们保留导出与删除权。We reserve the right to export and delete our data.\n")
corpus["c13"] = ("Bilingual glossary", "# 术语表 / Glossary\n\n| 中文 | English |\n| --- | --- |\n| 知识库 | Knowledge base |\n| 附件 | Attachment |\n")
corpus["c14"] = ("Bilingual tasks", "# 任务 / Tasks\n\n- 导入语料 / Import corpus\n- 导出 Markdown / Export Markdown\n")
corpus["c15"] = ("Bilingual FAQ", "# 常见问题 / FAQ\n\nQ: 能导出吗？/ Can it export?\nA: 能，标准 Markdown+assets。/ Yes, standard Markdown+assets.\n")

# Mixed / attachments / misc
corpus["c16"] = ("PDF attachment link", "# PDF 附件示例\n\n本笔记关联一份 PDF 附件：\n\n[查看示例 PDF](assets/sample-doc.pdf)\n\n附件用于验证导出后哈希一致性。\n")
corpus["c17"] = ("Quote + nested headings", "# 引用与层级\n\n## 第一节\n\n> 知识应当及时可恢复。\n\n### 子节\n\n细节在此。\n")
corpus["c18"] = ("Checklist", "# 检查清单\n\n- [x] 部署\n- [ ] 备份\n- [ ] 回滚\n")
corpus["c19"] = ("Mixed en/zh table", "# 中英混合表格\n\n| Item | 状态 |\n| --- | --- |\n| Deploy | 已完成 |\n| Backup | 待办 |\n")
corpus["c20"] = ("Index hub", "# 总索引\n\n- [[c01 Quarterly Operations Review]]\n- [[c06 中文运营复盘]]\n- [[c11 介绍 / Introduction]]\n- [[n01 Welcome Note]]\n")

# ---------- native note drafts (use SiYuan syntax) ----------
native = {}
native["n01"] = ("Welcome + block ref + wikilink", """# 欢迎笔记 / Welcome Note

这是原生笔记示例，测试 block reference、双向链接、标签与模板。

## 任务清单
- 部署思源 #s1 #infra
- 验证导出 #export

## 关键结论
思源应仅作为 **authoring workspace**，canonical 数据由 LifeOS/NAS 管理。

相关：[[c01 Quarterly Operations Review]]

> 模板变量：{{.title}} 于 {{now | date "2006-01-02"}} 创建
""")

native["n02"] = ("Template example", "# 模板示例 / Template\n\n标题：{{.title}}\n\n日期：{{now | date \"2006-01-02\"}}\n\n标签：#template #demo\n")
native["n03"] = ("Tags example", "# 标签示例\n\n#family #private #archive #s1\n\n标签用于检索与权限分组。\n")
native["n04"] = ("Wikilinks example", "# 双向链接示例\n\n- [[c06 中文运营复盘]]\n- [[n01 Welcome Note]]\n- [[c13 术语表 / Glossary]]\n")
native["n05"] = ("Attachment example", "# 附件示例\n\n![图](assets/sample-chart.png)\n\n[PDF](assets/sample-doc.pdf)\n")
native["n06"] = ("Block ref target", "# Block Reference 目标\n\n这里是被引用块的内容。((BLOCKREF)) 会被替换为真实 block id。\n")
native["n07"] = ("Query / DB view example", "# 查询 / 数据库视图\n\n```query\nSELECT * FROM blocks WHERE content LIKE '%#s1%' LIMIT 20\n```\n\n（SiYuan 实际用属性视图；此处记录查询意图。）\n")
native["n08"] = ("Long native note", "# 原生长笔记\n\n" + "\n".join(f"第{i}块：原生笔记可包含任意结构，包括表格、引用与代码。" for i in range(1, 21)))
native["n09"] = ("Table native", "# 原生表格\n\n| 名称 | 类型 |\n| --- | --- |\n| family-shared | notebook |\n| person-private | notebook |\n")
native["n10"] = ("Summary native", "# S1 原生笔记汇总\n\n覆盖：block reference、双向链接、模板、标签、附件、查询/数据库视图。\n")

# ---------- write files + manifest ----------
manifest = {"generated": "2026-08-03", "seed": 20260803, "docs": {}, "assets": {}, "features": {}}


def _write(k, feat, body, kind):
    extra = ATTACH_MAP.get(k)
    if extra:
        body = body.rstrip("\n") + "\n" + attachment_section(extra)
    p = os.path.join(CORPUS, k + ".md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    manifest["docs"][k] = {
        "file": k + ".md",
        "sha256": sha256(p),
        "features": feat + (" + attachment" if extra else ""),
        "kind": kind,
        "attachments": extra or [],
    }


for k, (feat, body) in corpus.items():
    _write(k, feat, body, "corpus")

for k, (feat, body) in native.items():
    _write(k, feat, body, "native")

for _name, _fn in ASSET_SPECS:
    manifest["assets"][_name] = sha256(os.path.join(ASSETS, _name))

import yaml
with open(os.path.join(CORPUS, "manifest.yaml"), "w", encoding="utf-8") as f:
    yaml.safe_dump(manifest, f, allow_unicode=True, sort_keys=False)

print("generated:")
print("  corpus docs:", len(corpus))
print("  native docs:", len(native))
print("  assets:", os.listdir(ASSETS))
print("  manifest:", os.path.join(CORPUS, "manifest.yaml"))
