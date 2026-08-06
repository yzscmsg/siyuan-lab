# Architecture Decision Records — siyuan-lab (Experiment S1)

ADRs are immutable decision history. When a decision changes, create a new ADR
that supersedes the old one; do not rewrite history.

Status values: `Proposed`, `Accepted`, `Superseded`, `Rejected`.

## Index

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-siyuan-deployment-model.md) | SiYuan lab deployment model | Accepted |
| [0002](0002-export-as-portable-format.md) | Markdown + assets export is the only supported seam | Accepted |
| [0003](0003-siyuan-permission-model.md) | SiYuan is a single-user workbench, not the family permission system | Accepted |
| [0004](0004-backup-and-rollback.md) | Backup, restore and rollback for the SiYuan workbench | Accepted |
| [0005](0005-s1-verdict.md) | S1 verdict — adopt SiYuan on trial as a single-user workbench | **Proposed** (partially superseded by 0006) |
| [0006](0006-single-owner-publishing.md) | Single-owner LifeOS; SiYuan = private admin console, consumption via LifeOS granular publishing | Accepted |
| [0007](0007-lab-boundary-and-facade-deferral.md) | SiYuan lab boundary; custom family facade deferred as a synthetic-data PoC | Accepted |

ADR-0005 is the ADR candidate required by the S1 protocol. It remains `Proposed`
until the objective-8 manual test (five real family tasks on a mobile device) is
performed. ADR-0006 re-scopes its permission findings: the family boundary moves
from SiYuan (which has none) to LifeOS granular publishing.

The manual task was later completed. ADR-0007 records the current parent
architecture: SiYuan is adopted only as an optional single-owner authoring
workspace, while the custom family facade is deferred and remains a
synthetic-data PoC.

## Relationship to the FamilyLifeOS ADRs

These are scoped to the SiYuan experiment and are numbered independently. They
inherit from, and must stay consistent with, the parent decisions:

- FamilyLifeOS **ADR-0004** (health-data sensitivity and access logging) — the
  reason Phase-0.5-sensitive material is kept out of SiYuan entirely.
- FamilyLifeOS **ADR-0005** (layered backup and restore testing) — the source of
  the rule that a backup is not successful until automated checks pass.
- **RK-004 isolation** (rag-lab-kit; not family-lifeos ADR-0004) — an organisational boundary is never a
  security boundary; separate instances, DBs and ACLs per boundary.
