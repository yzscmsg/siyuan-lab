# ADR-0002: Markdown + assets export is the only supported seam

- Status: Accepted
- Date: 2026-08-03

## Context

SiYuan stores documents as `.sy` JSON block trees and maintains its own SQLite
index. It is tempting to read that database directly — it is right there, it is
queryable, and `/api/query/sql` even exposes it over HTTP.

Doing so would make SiYuan structurally load-bearing. The moment LifeOS depends
on SiYuan's internal schema, "we can leave whenever we want" stops being true.

S1 tested whether the open-format path is good enough to make that dependency
unnecessary.

## Evidence

Round-trip: 20 imported + 10 native documents, hashed before import, exported
back to Markdown + assets, compared feature by feature (`scripts/fidelity.py`).

- 30/30 documents exported with content and title preserved
- 30/30 structural pass: headings, heading levels, tables, table rows, code
  blocks (body hashes identical), images, links, task lists, blockquotes, tags
- 100% word retention (min and mean), CJK compared per character
- 14/14 wikilinks survived
- 2/2 binary assets byte-identical by sha256

Three systematic, benign transformations:

1. YAML front-matter added (`title`, `date`, `lastmod`)
2. Document name prepended as an H1
3. Asset filenames content-addressed on upload
   (`sample-chart.png → sample-chart-20260803004437-bel5vun.png`); bytes unchanged

## Decision

1. **The standard Markdown + assets export is the only supported integration
   seam between SiYuan and LifeOS.**
2. **LifeOS must never read SiYuan's `.sy` files, its SQLite index, or
   `/api/query/sql` as a source of record.** `/api/query/sql` may be used for
   *operational* checks only (health, doc counts in smoke tests) and its results
   must never be persisted as canonical data.
3. Downstream parsers must expect and normalise the three systematic
   transformations above. The doubled leading heading in particular must be
   collapsed, or every document acquires a spurious title block in RAG chunks.
4. Asset identity is the **content hash**, never the filename.

## Consequences

- Exit cost stays bounded: the export is ordinary Markdown in ordinary folders.
  If SiYuan is dropped, `results/exports/markdown/**` is already the deliverable.
- Some SiYuan-native affordances (block references as live links, database views)
  degrade to plain text on export. That is the accepted price of portability and
  is a reason not to build family-critical structure out of those features.
- The export is per-document via `/api/export/exportMdContent`. A full-workspace
  export must be driven by iterating the document list — see `scripts/export_md.py`.
