---
afds_schema_version: 2
assessed_revision: 6579cbeb7f651c16633854ab64e24f369aa3c1d8
description: Rule-level adoption status and residual evidence gaps for the pinned AI Skills authority
doc_id: reference.compliance-status
type: reference
status: evolving
rigor: operational
owners: [repository-maintainers]
verification:
  kind: command
  value: Compare this document with `ai-skills.lock.yaml`, run `scripts/check_evidence_freshness.py` and `scripts/ci.py`, and require independent deployment evidence before production approval.
---
# Compliance status

## Assessment boundary

This repository pins AI Skills `1.2.0` at revision
`661ff01a5e70d58d6c94a12545b24647e52063ed` — the current `main` of
`paulomac1000/ai-skills` and the sole contract authority for adoption claims. The pin is
recorded in `ai-skills.lock.yaml` with per-skill normative entrypoints and content
digests. The implementation targets the `mcp-server`, single-repository application
profile at maturity level L2.

Some repository controls deliberately exceed what `main` requires; they are labeled
*local hardening* below and are never presented as upstream requirements. Candidate-only
contracts from an upstream hardening branch (skills-lock validator, canonical capability
schema, atomic child controls, AFDS document schema 2) were removed from authoritative
gates; where retained locally they are explicitly non-authoritative.

`assessed_revision` in this document's frontmatter names the exact 2.0 release-candidate
code and workflow revision immediately before evidence-only release documentation updates.
Any descendant used for the release may differ only in the evidence paths allowed by
`scripts/check_evidence_freshness.py`; any implementation, dependency, configuration, or
workflow change requires a new assessment binding. Provider run IDs and artifact IDs are
not treated as timeless approval: release publication independently requires a successful
ordinary CI run and the exact non-expired release bundle for the tagged SHA. No document
treats its own commit hash, a badge, or self-authored evidence as independent production
approval.

## Implemented contract changes

Measured against the twelve stable `mcp-server-architect` rules on `main`, the repository
now provides:

- one transport-independent invocation kernel owning validation, authorization, target
  binding, deadlines, concurrency, execution, sanitization, provenance, and structured
  failures (`mcp.architecture.boundaries`);
- two-phase authorization: principal authentication plus capability and selector-namespace
  authorization before any target resolution, then a second authorization pass against the
  resolved backend identity, with mutations bound to stable identity including the verified
  SSH host-key fingerprint (`mcp.identity.target-binding`);
- a complete application-owned manifest for every capability with conservative defaults,
  supported and active catalogs, inactive reasons, and fail-closed registration
  (`mcp.manifest.complete`);
- manifest/runtime parity: projected concurrency and approval contracts describe exactly
  what the runtime enforces, verified by test (`mcp.manifest.complete`);
- transient read retry only, single-attempt mutations, pre-execution versus ambiguous
  post-start deadline classification, and retry backoff bounded by the remaining operation
  deadline (`mcp.retry.fail-closed`);
- stdio and authenticated loopback Streamable HTTP only, exercised through the official
  MCP client (`mcp.transport.supported`);
- request, capability, and server deadline bounds, keyed concurrency locks, cancellation
  propagation, and bounded SSH process cleanup with escalation
  (`mcp.deadline.concurrency`);
- protocol-native structured errors carrying the same provenance metadata as successes
  once the target is resolved, sanitization, and serialized-envelope response bounds
  (`mcp.response.structured`);
- server-side operator write enablement plus opaque one-time approvals bound to principal,
  capability, resolved target identity, resource, and normalized arguments
  (`mcp.authorization.server-side`);
- exact application-wheel SHA verification inside the container build and exact-wheel
  stdio/HTTP smoke tests (`mcp.artifact.exact`);
- breaking-change accounting, rollback, and residual risks recorded in `MIGRATION.md`
  and this document (`mcp.migration.accounted`);
- layered credential-free unit, smoke, official-client, wheel, and container gates
  (`mcp.verification.layered`).

## Local hardening beyond `main`

Retained deliberately, never claimed as upstream requirements:

- an AI Skills consumer skills lock with per-skill revisions, entrypoints, and content
  digests, checked by `scripts/check_docs.py`;
- canonical language-neutral capability projections (operation kind, risk, determinism,
  latency, impact, approval contract, concurrency) validated for runtime parity;
- AFDS document schema 2 frontmatter with typed verification objects on governed
  documents;
- a dedicated adoption workflow emitting machine-bound structural evidence artifacts and
  rejecting stale evidence;
- platform-exact hashed dependency locks for Linux x64 CPython 3.12, 3.13, and 3.14 with
  provider regeneration lanes and drift failure.

## Credential-free acceptance contract

Repository gates cover transport-independent backend adapters and one invocation kernel,
immutable configuration, complete manifest coverage, two-phase capability and target
authorization, no target fallback, one-time approval binding, read retry policy, mutation
retry veto and reconciliation semantics, structured sanitization, SSH identity, HTTP
authentication and bounds, cancellation, exact installed-wheel official-client behavior,
exact Linux/amd64 container behavior, workflow privilege policy, static security checks,
typing, lint, coverage, dependency audit, and pinned-authority documentation validation.

The exact installed-wheel transport checks exercise tool listing, representative reads,
missing-target failures, and unapproved-write rejection over both stdio and authenticated
Streamable HTTP. Provider conclusions, run IDs, artifact IDs, and digests are valid only
for the revision recorded by the corresponding evidence object.

## Rule summary

| Rule family | Current state | Evidence or gap |
| --- | --- | --- |
| mcp.architecture.boundaries | implemented | shared kernel, adapters, registration and transport tests |
| mcp.identity.target-binding | implemented structurally | two-phase authorization, exact target identity and SSH peer fingerprint; real rotation evidence remains |
| mcp.manifest.complete | implemented | complete manifests, parity-tested projections, fail-closed registration |
| mcp.retry.fail-closed | implemented | transient read retry only; mutations single-attempt; deadline-phase classification tested |
| mcp.transport.supported | implemented | stdio and authenticated loopback Streamable HTTP through official client |
| mcp.deadline.concurrency | implemented | request/capability/server bounds, keyed locks, cancellation, mutation classification budget |
| mcp.response.structured | implemented | provenance-parity errors, retry guidance, sanitization, envelope bounds |
| mcp.authorization.server-side | single-operator profile | hidden approvals bind principal, capability, target identity, resource and normalized arguments |
| mcp.operations.observable | incomplete | health dimensions exist; deployment audit/metrics/SLO and recovery drills remain |
| mcp.artifact.exact | implemented structurally | exact wheel and Linux/amd64 image build/smoke gates must be green for the tagged revision |
| mcp.migration.accounted | implemented | `MIGRATION.md`, rollback, residual risks, and this document |
| mcp.verification.layered | implemented | layered gates composed by `scripts/ci.py` plus provider lanes |

## Deferred external evidence

The following cannot be established by repository mocks or self-review:

- SSH fingerprint enrollment, rotation, and address-to-identity revalidation on real target classes;
- one execution and postcondition reconciliation for every real mikr.us mutation;
- remote filesystem symlink-swap behavior on each deployed filesystem/backend combination;
- published-image digest smoke for any release platform actually promoted;
- deployment-specific audit sink, metrics/SLO definition, and recovery exercises;
- an independent review bound to the exact final revision, required before
  `migration-assessment.yaml` can be regenerated as a schema-valid assessment under
  `main` (the stable schema requires a concrete reviewer for every decision).

The current container release profile remains Linux/amd64. Multi-architecture publication
is not claimed.

## Acceptance gate

Merge requires ordinary CI, Semgrep, and the AI Skills adoption workflow green against
`ai-skills@main`, committed locks without drift, exact wheel/container smoke green, and
this document bound to a revision whose only descendants are evidence-only. Production
acceptance additionally requires real-system deployment evidence and an independent
review of the exact final revision. No local result, intermediate branch SHA, badge, or
self-authored assessment is final AI Skills adoption approval.
