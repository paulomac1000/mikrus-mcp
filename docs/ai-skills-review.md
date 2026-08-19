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

### Reviewerless structural assessments

The adoption-assessment schema now allows `request-changes` and `rejected` structural
assessments to omit `decision.reviewer`. Reviewer evidence remains mandatory for
`approve`, and a reviewer object supplied for another decision is still validated. The
template and validator follow the same rule, so an adopter can record blocking gaps
without fabricating a provider review ID or reviewer identity.

This correction makes a machine-readable pre-review assessment possible, but it does not
turn self-produced structural evidence into independent acceptance. A final approval
still requires provider-backed evidence and a reviewer bound to the exact assessed
revision.

## Consumer-side requirements retained here

Even after the upstream contract repairs, this repository must independently prove its
own implementation. Canonical manifests do not establish correct runtime activation;
schema-valid identity fields do not prove real SSH host-key behavior; a filesystem
primitive still needs race evidence on deployed filesystems; compact hashed lock graphs
must remain bound to the exact declared runtime lane and be installed with
`--require-hashes`; and provider-green CI does not substitute for independent production
review.
