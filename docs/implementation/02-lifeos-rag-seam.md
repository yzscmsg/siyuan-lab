# SiYuan → LifeOS → n8n → Dify: the integration seam

- Status: designed and validated on the SiYuan side; LifeOS/n8n side not yet built
- Relates to: ADR-0002 (export is the only seam), ADR-0003 (permission model),
  FamilyLifeOS ADR-004 (instance isolation), `rag-lab-kit` (Dify + n8n lab)

## The shape

```
┌──────────────┐   standard export    ┌──────────────────┐
│   SiYuan     │  Markdown + assets   │  LifeOS Document │
│  (authoring) ├─────────────────────►│       API        │
└──────────────┘                      │  UUID · owner ·  │
       ▲                              │  ACL · checksum  │
       │ human edits                  └────────┬─────────┘
       │                                       │ canonical record
       │                              ┌────────▼─────────┐
       │                              │  NAS archive +   │
       │                              │  PG registry     │
       │                              └────────┬─────────┘
       │                                       │
       │                              ┌────────▼─────────┐
       │                              │       n8n        │
       │                              │ validate/classify│
       │                              │      /route      │
       │                              └────────┬─────────┘
       │                                       │ only ACL-cleared docs
       │                              ┌────────▼─────────┐
       └── AI draft, human approve ───┤   Dify (RAG)     │
                                      │ derived, rebuildable│
                                      └──────────────────┘
```

Direction of authority runs **right to left**: LifeOS owns the record, SiYuan is
a surface you type into, Dify is an index you can throw away and rebuild.

## Non-negotiable rules

1. **LifeOS never reads SiYuan's internal database.** Not the `.sy` files, not
   the SQLite index, not `/api/query/sql`. The only input is the Markdown +
   assets export. (ADR-0002)
2. **SiYuan is not a system of record.** If a document exists only in SiYuan, it
   does not exist. The registry entry in LifeOS is the fact.
3. **Dify holds nothing canonical.** Embeddings and chunks are derived artefacts.
   Dropping the vector store must never lose information.
4. **ACL is evaluated in LifeOS, before n8n hands anything to Dify.** SiYuan
   cannot enforce it (ADR-0003), so the gate lives upstream of the AI layer.
5. **Isolation per ADR-004.** The family instance and any KZ/Track-B instance get
   separate n8n and Dify deployments — separate containers, separate PostgreSQL
   DB and user, separate NAS ACLs. Shared hardware is fine; a shared install with
   only workspace segregation is not.

## Ingest contract

For each exported document, the ingest job submits to the LifeOS Document API:

| Field | Source | Notes |
| --- | --- | --- |
| `uuid` | **LifeOS-assigned** | Never SiYuan's block id. SiYuan ids change on re-create. |
| `source_system` | constant `siyuan` | |
| `source_ref` | notebook + hpath | e.g. `family-shared/corpus/c01`. Advisory only. |
| `owner` | resolved by LifeOS | SiYuan has no user concept to read this from. |
| `acl` | assigned by LifeOS | Default deny for anything unclassified. |
| `checksum` | sha256 of exported Markdown body | Computed **after** normalisation, see below. |
| `assets[]` | sha256 + bytes | Asset identity is the hash, never the filename. |
| `exported_at` | export run timestamp | |

### Normalisation before checksum

The export applies three systematic transformations (measured in S1, see the
[runbook §6](01-s1-runbook.md#6-objective-6--standard-markdown--assets-export-and-fidelity)).
Normalise them or the checksum changes on every export and every document
re-ingests forever:

1. **Strip the YAML front-matter** (`title`, `date`, `lastmod`). `lastmod` in
   particular changes on touch, so leaving it in guarantees checksum churn.
2. **Collapse the duplicated leading heading.** The export prepends the document
   *name* as an H1; documents whose body already starts with an H1 end up with
   two. Left in, every RAG chunk acquires a spurious title block.
3. **Resolve asset references by content hash**, not filename. SiYuan
   content-addresses on upload (`sample-chart.png →
   sample-chart-20260803004437-bel5vun.png`) while the bytes stay identical.

With these three applied, S1 measured 100% word retention and 30/30 structural
fidelity — the checksum is then stable and meaningful.

## Idempotency — the trap

`createDocWithMd` is **not idempotent**: posting the same path twice yields a
*second* document with a new id (`api_suite_report.json` →
`idempotency.same_id_on_dup_path: false`). Any n8n retry, webhook redelivery or
re-run duplicates content silently.

Therefore:

- **Deduplicate in n8n/LifeOS on the LifeOS UUID + content checksum**, never on
  SiYuan's path or block id.
- Writes back into SiYuan (if ever enabled) must be **read-then-update**, not
  blind create. Look up the existing document first; create only on a miss.
- Every ingest run is expected to re-see unchanged documents. Unchanged checksum
  ⇒ no-op, no new registry row, no re-embedding.

## Error handling

The API error model is thin: everything is `code: -1` with a prose `msg`; auth
failures arrive as HTTP 401 `Auth failed [session]`. Callers cannot branch on
error class.

- Treat any non-zero code as retryable with exponential backoff.
- Escalate to a human after N failures rather than attempting clever recovery —
  string-matching on `msg` is brittle and will break on upgrade.
- 401 is *not* retryable: it means the token is wrong or revoked. Fail loudly.

## Deletion and retraction

The protocol requires that deletion and retraction propagate. Deleting in SiYuan
only removes the *authoring copy*; it must not silently orphan the canonical
record or leave the document embedded in the vector store.

Propagation path: **LifeOS is the trigger, not SiYuan.**

1. Retraction is requested in LifeOS (or detected as an export absence + explicit
   confirmation — never on absence alone, since an export failure looks identical
   to a deletion).
2. LifeOS marks the registry row retracted and records who/when.
3. n8n removes the corresponding chunks from the Dify knowledge base and
   re-indexes.
4. The NAS archive copy follows the retention policy — retraction from the AI
   layer is immediate; destruction of the archived record is a separate,
   policy-governed action.
5. The SiYuan-side copy is deleted last, and its absence is never itself the
   source of truth.

## What this seam does not cover yet

- The LifeOS Document API is **not built**; this document is the contract it must
  satisfy.
- The n8n workflow is **not built**. `rag-lab-kit` (Dify + n8n on CT
  192.168.0.149) is the intended proving ground, using its seeded corpus and
  drop-folder inbox as the capture pattern.
- No writes back into SiYuan are in scope. S1 validated the read/export
  direction; the write direction is deliberately deferred until the idempotency
  problem above has a tested answer.
