---
afds_schema_version: 2
description: Review findings and remaining amendments for the pinned post-1.2.0 ai-skills hardening authority
doc_id: reference.ai-skills-upstream-review
type: reference
status: evolving
rigor: informative
owners: [repository-maintainers]
verification:
  kind: manual-review
  value: Compare each finding with the exact pinned ai-skills contract revision, `migration-assessment.yaml`, `atomic-claims.yaml`, and provider evidence before treating it as resolved.
---
# AI Skills upstream review

## Current authority

This repository pins the post-1.2.0 hardening authority at
`fdb46268454bf08258e39e604e0ab7f764b54c7a`. The pin is intentional: a newer upstream
hardening candidate exists, but this consumer does not repin merely because a branch is
newer. A replacement authority must first have coherent contracts and provider evidence
suitable for a controlled migration.

The consumer implementation and adoption tooling are assessed at
`7cf17f934483469b281a1f30d7ceb1f16ba4e92b`. Provider CI and Semgrep are green on that
revision. The `AI Skills adoption` source run validates the pinned authority and emits a
machine-bound structural report before the later evidence-only commit updates the
assessment. `scripts/check_evidence_freshness.py` rejects any implementation drift after
the assessed revision.

## Resolved upstream findings

### Read idempotency and retry semantics

The earlier capability schema forced incorrect read semantics. The pinned authority now
treats reads as naturally idempotent while leaving retry eligibility opt-in and does not
require a mutation-style idempotency key for a retryable read. `mikrus-mcp` therefore
keeps explicit transient/rate-limit retry conditions without degrading its read contract.

### Malformed approval binding validation

The canonical capability validator and generated Python validator now validate binding
element types before set conversion. Malformed non-hashable values become controlled
validation findings instead of escaping as `TypeError`.

### Reusable-workflow inherited permissions

The workflow auditor evaluates effective write permission for local reusable-workflow
calls instead of checking only job-local `permissions`. A caller cannot hide inherited
workflow-level write authority from the recursive policy audit.

### Python generator destination links

The generator checks lexical destination components for symlink/reparse objects before
resolution. Resolution can no longer erase evidence that an untrusted destination parent
was reached through a link.

### Reviewerless structural assessments

`request-changes` and `rejected` structural assessments may omit `decision.reviewer`.
Reviewer evidence remains mandatory for `approve`, and supplied reviewer objects remain
fully validated. This permits an honest pre-review assessment without fabricated review
IDs or identities.

## Consumer findings fixed in this branch

### Adoption validation is now executable

A dedicated least-privileged workflow checks out the immutable pinned authority and runs
its skill-lock validator, migration-assessment validator, atomic catalog validator and
consumer atomic-report validator. It builds and installs the exact application wheel
before official-client subprocess tests, then emits a real provider artifact containing
`structural-attestation.json`, its SHA-256, the exact wheel, and the committed assessment
inputs.

The report for assessed revision `7cf17f934483469b281a1f30d7ceb1f16ba4e92b` was emitted
by GitHub Actions run `32427847331`; the assessment uses the actual provider run, job,
artifact, provider digest and report digest. No historical run is relabeled as current
evidence.

### Atomic child controls are now explicit

`atomic-claims.yaml` records the applicable L2 child controls for the single-repository,
migration, local-stdio, remote-http, multi-backend, filesystem and packaged profiles.
Each passed claim points to concrete repository tests and implementation paths. The
pinned validator reports zero atomic findings for the report and the evidence test set is
executed in provider CI.

### Stale evidence fails closed

`migration-assessment.yaml` and `atomic-claims.yaml` must bind the same full revision.
That revision must be an ancestor of the checked-out HEAD, and every file changed after
it must be an explicitly allowed evidence/status file. Changing runtime code, tests,
workflow policy, packaging or locks automatically invalidates the assessment until a new
provider-backed code revision is assessed.

### Mutation deadline phases are separated

The kernel no longer treats entry into a mutation wrapper as proof that a side effect may
have been dispatched. Lock waiting remains inside the request deadline without consuming
the one-time approval. After the lock is acquired, a production mutation starts only if
at least the adapter classification budget remains; otherwise it returns ordinary timeout
and preserves the approval. Expiry after mutation execution begins remains
`AMBIGUOUS_OUTCOME` and requires reconciliation. Regression tests cover both paths.

### Platform locks are provider-verified

Linux x64 CPython 3.12, 3.13 and 3.14 runtime/development lock files are committed,
regenerated from provider-selected wheelhouses and reinstalled with `--require-hashes`
and `pip check`. This prevents a hand-edited or stale wheel hash from being accepted merely
because direct dependency pins still resolve.

## Remaining pinned-authority issue

The pinned atomic catalog currently makes `mcp.artifact.multiarch-exact` applicable when
the generic atomic profile contains `container`, not only when a deployment actually
claims multi-architecture publication. `mikrus-mcp` intentionally advertises Linux/amd64
only. The consumer therefore does not add the `container` profile to its atomic context
or invent arm64/platform evidence. Its real Linux/amd64 container build and smoke remain
separate CI evidence.

This applicability distinction should ultimately be corrected in `ai-skills`: a
single-architecture container profile and a multi-architecture publication profile are
not equivalent requirements. Until a corrected authority is provider-green, the consumer
records the limitation explicitly rather than weakening or falsifying its evidence.

## Evidence that remains external

Canonical manifests do not prove real SSH host-key enrollment and rotation. Structural
filesystem tests do not prove every production filesystem race. Mock and fake-upstream
mutation tests do not establish real mikr.us postcondition reconciliation. Provider-green
CI also does not constitute an independent production review.

Those deployment-specific checks remain blocking residual risks in
`migration-assessment.yaml`. The current decision is therefore `request-changes`, not a
self-issued adoption approval.
