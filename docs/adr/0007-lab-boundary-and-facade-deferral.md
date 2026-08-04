# ADR-0007: SiYuan lab boundary and custom-facade deferral

- Status: Accepted
- Date: 2026-08-04
- Parent decision: `family-lifeos` ADR-0010
- Supersedes in part: ADR-0006 claims that the custom facade is production-ready

## Context

S1 demonstrated that SiYuan can serve as a portable, recoverable single-owner
authoring workspace. Subsequent work added copies of LifeOS migrations and a
custom username/password facade to this experiment repository. Review found
that this mixed product ownership into the lab and expanded the maintenance and
security boundary before the Health Evidence-to-Artifact workflow was proven.

The facade also has unresolved blockers including response-header ordering,
broad cookie scope, direct non-TLS exposure, metadata disclosure before access
approval, broad database transport and incomplete account/security lifecycle.

## Decision

1. `siyuan-lab` owns only SiYuan deployment, export/API adapters, fidelity,
   security, maintenance and recovery experiments.
2. `family-lifeos` owns product schemas, migrations, identity/authorization,
   Evidence/Artifact contracts and release code.
3. The facade and migration `0008` are retained temporarily as historical PoC
   evidence using synthetic data. They are not an accepted production identity
   boundary and must not receive real family information.
4. The initial LifeOS is owner-only over VPN. A maintained identity component
   is reconsidered only after the Health vertical slice proves value and
   maintainability.
5. A subsequent repository-boundary change removes copied migrations and makes
   this lab consume a pinned LifeOS contract or release.
6. SiYuan remains `ADOPT` only for the optional single-owner authoring slot.
   The adoption decision does not extend to the custom facade, shared-family
   access or LifeOS as a whole.

## Consequences

- Existing facade scripts are experimental and may be disabled or deleted after
  useful fixtures/tests are migrated to `family-lifeos`.
- Lab documentation and routes must not be used as instructions for a real-data
  deployment.
- Product security gates are passed only in `family-lifeos`, with negative
  authorization tests and a witnessed recovery exercise.
- S1's measured results remain evidence, but normalized scores cannot substitute
  for unassessed product/security controls.
