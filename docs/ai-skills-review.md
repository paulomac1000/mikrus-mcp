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
authority. Upstream hardening branches are review input only; this consumer does not
repin to a candidate branch unless a deliberate adoption decision is recorded.

Where this repository deliberately exceeds `main` (skills-lock content digests,
application-owned capability projections, AFDS document schema 2 frontmatter, structural
evidence artifacts, and the evidence-freshness gate), those controls are documented as
local hardening in `docs/compliance-status.md` and are not presented as upstream
requirements.

## Stable main contract used by this repository

For an existing L2+ MCP server, stable `main` requires an exact-revision migration
assessment covering the complete stable rule catalog, exact artifact evidence, rollback,
residual risks, and an independent decision. The current adoption schema requires a
concrete `decision.reviewer` for every decision state. An approval additionally requires
provider-backed evidence, an APPROVED independent review bound to the exact assessed SHA,
and an external immutable acceptance authority.

The bundled GitHub evidence verifier in stable `main` is explicitly diagnostic and does
not itself provide acceptance authority. Consequently this candidate repository must not
present its own structural workflow or a self-authored assessment as final adoption
approval. Final acceptance belongs to an external authority workflow/reviewer after the
implementation SHA is frozen.

## Consumer hardening completed here

### Authority is pinned to main

Both hosted workflows and `ai-skills.lock.yaml` use the immutable stable `main` revision.
Candidate-only validators and rule identifiers are not authoritative gates.

### Authorization uses two phases

The kernel authenticates and authorizes capability plus selector namespace before target
configuration or network resolution. After the exact backend has been resolved, it
checks the resolved stable identity, resource authorization, and data classification.
Mutations additionally require operator write policy and a one-time approval bound to the
resolved identity and normalized resource/arguments. Identity is revalidated immediately
before execution.

### Manifest/runtime parity is executable

The public capability projection mirrors the enforced concurrency scope and approval TTL
contract and retains the independent operational-impact and idempotency-mechanism axes.
Tests and CI compare the projection with application policy rather than a candidate-only
upstream schema.

### Deadlines, retry and SSH cleanup fail closed

Long capabilities are not silently capped by the old ten-second default. Local credential
throttling returns a rate-limit error rather than sleeping through a request deadline.
Kernel retry backoff never outlives the remaining operation deadline and preserves the
original error category and retry guidance. SSH timeout, cancellation, and output-limit
paths all perform bounded process cleanup without turning cleanup failures into a new
operation result.

### Platform locks are provider-verified

Linux x64 CPython 3.12, 3.13 and 3.14 runtime/development lock files are committed.
Quality and compatibility lanes install the selected committed development lock with
`--require-hashes`; lock-regeneration lanes compare generated locks with the committed
copy and fail on drift.

## Structural evidence is not adoption approval

`.github/workflows/ai-skills-adoption.yml` is deliberately named **AI Skills structural
evidence**. It validates selected repository invariants against the pinned authority,
validates governed documentation, emits machine-bound evidence for the exact candidate
SHA, and rejects stale evidence. A green run is useful pre-review evidence only.

No `migration-assessment.yaml` is committed before an independent review exists because
stable `main` requires a real reviewer object. After the final implementation SHA is
provider-tested and independently reviewed, generate the assessment from the stable main
template, classify all stable rules, bind evidence and review records to that exact SHA,
and run the external acceptance authority. If implementation changes afterward, repeat
the evidence and review cycle.

## Evidence that remains external

Repository mocks cannot prove real SSH host-key enrollment and rotation, every production
filesystem race, or real mikr.us mutation reconciliation. Deployment audit sinks,
metrics/SLOs, recovery exercises, and release-platform evidence are also environment
responsibilities. These remain residual production risks even after repository adoption
acceptance.
