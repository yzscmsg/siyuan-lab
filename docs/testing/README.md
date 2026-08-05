# S1 Experiment — Test & Gate Scripts

This directory holds the **human-steppable test scripts** for the S1 experiment
(SiYuan as single-owner authoring console). Each file is one gate or one test,
so a human can walk every step and record the result.

## Standardized test-script format

Every gate/test script in this directory (and the companion ones in
`family-lifeos/docs/testing/`) follows the same structure so results are
comparable and auditable:

| Section | Required | What it contains |
| --- | --- | --- |
| **Header (YAML)** | yes | `id`, `title`, `status`, `source`, `last_run`, `recorded_by` |
| **Goal** | yes | The clause / question the gate proves. Quotes the rubric where possible. |
| **Scope** | yes | Exactly what surfaces/data the test touches. |
| **Prerequisites / Dependencies** | yes | Stack state, DB, fixtures, secrets, other gates that must pass first. |
| **Inputs** | yes | What the human or automation supplies (commands, fixtures, tokens). |
| **Expected output / pass criteria** | yes | Concrete, checkable pass conditions. |
| **Steps (human-steppable)** | yes | Numbered, copy-pasteable commands; prompts where a human decision is needed. |
| **Recorded result** | if run | The actual outcome from the executed run (evidence file + value). |
| **Issues found / notes** | yes | Known defects, findings, and caveats — even on a PASS. |
| **Re-run** | yes | Exact command to repeat the test. |

Principle (from `scripts/s1_acceptance.py`): *nothing is scored that was not
measured; anything a script cannot decide is reported MANUAL rather than quietly
passed.*

## Gate / test status legend

- `PASS` / `CLOSED` — measured and passed; evidence recorded.
- `OPEN` — not yet executed or not yet satisfiable (dependency missing).
- `DEFERRED` — intentionally out of scope for this experiment/product path.
- `MANUAL` — must be confirmed by a human; no automation decides it.

## Index — S1 experiment gates (siyuan-lab)

| ID | Script | Gate | Status | Last run |
| --- | --- | --- | --- | --- |
| HG1 | `gate-HG1-export-rebuild.md` | Open-format export + rebuild in fresh env, no manual DB repair | PASS | 2026-08-03 |
| HG2 | `gate-HG2-backup-rollback.md` | Backup recoverable, rollback, secrets off-host | PASS | 2026-08-03 |
| HG3 | `gate-HG3-unauthorized-access.md` | Unauthorised users/logs/models/indexes see no forbidden fields | PASS (ADR-0006) | 2026-08-03 |
| HG4 | `gate-HG4-retraction-propagation.md` | Deletion/retraction propagates across 5 layers | PASS | 2026-08-03 |
| HG5 | `gate-HG5-uninstall-canonical.md` | Clear uninstall; canonical data survives | PASS | 2026-08-03 |
| V8 | `gate-V8-family-ux.md` | Family viewing UX on a real phone (5 tasks) | PASS (15/15) | 2026-08-04 |
| S1-V | `gate-S1-verdict.md` | Overall verdict driver (runs `s1_acceptance.py`) | ADOPT 83.9/90 | 2026-08-04 |

## Index — S1 supporting feature tests (automated)

These are executed by `scripts/s1_acceptance.py` and live in `scripts/`. Their
metadata headers were added inline (see each file's module docstring):

| Test | Script | Gate covered | Recorded |
| --- | --- | --- | --- |
| Export + asset hashes | `scripts/export_md.py` | HG1 | 30/30 docs, 22/22 asset hashes |
| Round-trip fidelity | `scripts/fidelity.py` | HG1 | 30/30 structural, 100% words |
| Negative / leakage | `scripts/negative_tests.py` | HG3 | 7 surfaces secure |
| Retraction propagation | `scripts/retraction_test.py` | HG4 | 5 layers |
| Permission matrix | `scripts/perm_matrix.py` | HG3 (context) | single-user finding |
| Handoff → LifeOS | `scripts/lifeos_handoff.py` | HG5 / canonical | 52 rows canonical |
| V8 smoke (automated) | `scripts/v8_smoke_test.py` | V8 (pre-human) | 11/11 |
| Facade smoke (PoC) | `scripts/facade_smoke_test.py` | — (Deferred PoC) | n/a |

## How to run the whole suite

On the lab VM (`192.168.88.9`, `/opt/siyuan-lab`):

```bash
python3 scripts/s1_acceptance.py --list
python3 scripts/s1_acceptance.py --evaluate-only      # read-only scoring
python3 scripts/s1_acceptance.py --stages export,fidelity,negative,identity
python3 scripts/s1_acceptance.py --full               # destructive: backup/restore/upgrade/rollback/retraction
python3 scripts/s1_acceptance.py --full --yes        # no prompt
```

Evidence lands in `exports/s1_acceptance.json` / `.md` (pulled home to
`results/exports/`).
