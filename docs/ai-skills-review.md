---
afds_schema_version: 2
description: Review findings and remaining amendments for the pinned ai-skills main authority
doc_id: reference.ai-skills-upstream-review
type: reference
status: evolving
rigor: informative
owners: [repository-maintainers]
verification:
  kind: manual-review
  value: Compare each finding with the exact pinned ai-skills contract revision and provider evidence before treating it as resolved.
---
# AI Skills upstream review

## Current authority

This repository pins `main` of `paulomac1000/ai-skills` at
`661ff01a5e70d58d6c94a12545b24647e52063ed` (release 1.2.0) as the sole contract
authority. Upstream hardening branches are tracked as review input only; this consumer
does not repin to a candidate branch unless its own provider evidence is green and a
deliberate adoption decision is recorded.

Findings below describe the pinned `main` contracts. Where this repository deliberately
exceeds `main` (skills lock with digests, canonical capability projections, AFDS document
schema 2 frontmatter, machine-bound adoption evidence, evidence-freshness gate), those
controls are documented as local hardening in `docs/compliance-status.md` and are never
presented as upstream requirements.


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

A dedicated least-privileged workflow checks out the immutable pinned authority, builds
and installs the exact application wheel before official-client subprocess tests, runs
the governed-documentation AFDS validation, and emits a real provider artifact containing
`structural-attestation.json`, its SHA-256, and the exact wheel.

### Stale evidence fails closed

`docs/compliance-status.md` declares the assessed revision in its frontmatter.
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

## Remaining upstream observations

The stable `main` adoption schema requires a concrete reviewer for every decision,
including `request-changes`. This repository therefore ships no self-authored assessment
file: a schema-valid `migration-assessment.yaml` can only be produced after an
independent review of the exact final revision exists, and producing one earlier would
require fabricating reviewer evidence.

Multi-architecture publication remains unclaimed; a single-architecture container
profile and a multi-architecture publication profile are not equivalent requirements, and
this distinction should ultimately be clarified in `ai-skills`.

## Evidence that remains external

Canonical manifests do not prove real SSH host-key enrollment and rotation. Structural
filesystem tests do not prove every production filesystem race. Mock and fake-upstream
mutation tests do not establish real mikr.us postcondition reconciliation. Provider-green
CI also does not constitute an independent production review.

Those deployment-specific checks remain blocking residual risks recorded in
`docs/compliance-status.md`. Adoption approval stays open until an independent review of
the exact final revision exists.
