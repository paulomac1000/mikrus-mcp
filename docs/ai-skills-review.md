---
afds_schema_version: 2
description: Review findings and remaining amendments for the pinned post-1.2.0 ai-skills hardening authority
doc_id: reference.ai-skills-upstream-review
type: reference
status: evolving
rigor: informative
owners: [repository-maintainers]
verification:
  kind: review
  value: Compare each finding with the exact pinned ai-skills contract revision and its regression tests before treating the finding as resolved.
---
# AI Skills upstream review

## Current authority

This repository currently evaluates the post-1.2.0 hardening authority pinned in
`ai-skills.lock.yaml`. Earlier findings about canonical skill locks, protocol revisions,
atomic child controls, provider-neutral evidence records, AFDS v2, and multi-architecture
promotion are now represented by executable contracts or references in that authority.
They are no longer treated here as missing features merely because they were absent from
the published 1.2.0 baseline.

The authority pin does not itself mean that the upstream branch is provider-green or
independently accepted. Consumer CI validates the exact pinned source contract; upstream
provider evidence and adopter acceptance remain separate claims.

## Resolved review findings

### Read idempotency and retry semantics

The earlier capability schema forced every read to declare both `idempotent: false` and
`retryable: false`. The current pinned authority now treats reads as naturally
idempotent while leaving retry opt-in. It also avoids requiring a mutation-style
idempotency key solely because an idempotent read is retryable. `mikrus-mcp` therefore
keeps explicit transient/rate-limit retry conditions for reads without degrading the
read contract.

### Malformed approval binding validation

Both the canonical capability validator and generated Python validator previously called
`set()` directly on arbitrary list values. Non-hashable entries could therefore escape as
a `TypeError` instead of becoming a controlled validation finding. The pinned authority
validates binding element types before set conversion.

### Reusable workflow inherited permissions

The workflow auditor now evaluates effective write permission for local reusable workflow
calls rather than checking only job-local `permissions`. A caller cannot hide inherited
workflow-level write authority from the recursive-audit guard.

### Python generator destination symlinks

The generator now checks the lexical destination path components for symlink/reparse
objects before resolving the path. Resolution can no longer erase the evidence that an
untrusted destination parent was reached through a link.

## Remaining upstream defect

### Structural request-changes assessment still requires reviewer evidence

The current adoption-assessment schema requires `decision.reviewer` for every decision,
including a pre-review `request-changes` structural assessment. The validator likewise
validates reviewer identity unconditionally. This creates the wrong evidence incentive:
an adopter which has found blocking gaps but has not yet received a provider review must
either omit the machine-readable assessment or fabricate a review ID and reviewer
identity.

The contract should require `decision.reviewer` only when a reviewer-backed decision is
actually claimed, and must require it for `approve`. A reviewer object supplied for
`request-changes` or `rejected` should still be validated normally. The default template
for structural `request-changes` should omit reviewer coordinates rather than contain
placeholder provider evidence.

This is an upstream contract correction, not a reason for `mikrus-mcp` to fabricate
acceptance evidence. Until the authority includes that correction, the adopting
repository can record its structural state in prose and tests but must not label a
reviewer-less document as schema-valid adoption acceptance.

## Consumer-side requirements retained here

Even after the upstream contract repairs, this repository must independently prove its
own implementation. In particular, canonical manifests do not establish correct runtime
activation; schema-valid identity fields do not prove real SSH host-key behavior; a
filesystem primitive still needs race evidence on deployed filesystems; hashed lock
contracts still require committed graphs for every declared lane; and provider-green CI
does not substitute for independent production review.
