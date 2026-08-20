---
afds_schema_version: 2
description: Rule-level adoption status and residual evidence gaps for the pinned AI Skills authority
doc_id: reference.compliance-status
type: reference
status: evolving
rigor: operational
owners: [repository-maintainers]
verification:
  kind: command
  value: Compare this document with `ai-skills.lock.yaml`, validate `migration-assessment.yaml` and `atomic-claims.yaml` with the pinned authority, run `scripts/ci.py`, and require independent deployment evidence before production approval.
---
# Compliance status

## Assessment boundary

This repository pins AI Skills `1.2.0` to immutable revision
`fdb46268454bf08258e39e604e0ab7f764b54c7a`. The pin is the current contract authority
and matches `ai-skills.lock.yaml`; the newer upstream hardening candidate is not adopted
while its own provider evidence is not green.

The implementation and adoption tooling are assessed at immutable revision
`7cf17f934483469b281a1f30d7ceb1f16ba4e92b`. `migration-assessment.yaml` and
`atomic-claims.yaml` both bind that revision. Branch commits after it are allowed to touch
only the explicitly governed evidence/status files. `scripts/check_evidence_freshness.py`
fails closed if any implementation, test, workflow, lock, packaging, or runtime file
changes after the assessed revision.

The GitHub Actions `AI Skills adoption` source run `32427847331` on the assessed revision
validated the immutable skill lock, migration assessment, atomic authority, consumer
atomic report, and 69 targeted evidence tests, then emitted the real
`structural-attestation.json` artifact. Its freshness step was intentionally red while the
committed evidence still pointed to the preceding assessment. Evidence-only descendant
`49eaf78a22bf32b8d0cb435f669cc499fba61861` subsequently demonstrated that the rebound
assessment, atomic report, and freshness contract pass together in run `32428268008`.
Every later evidence-only descendant must pass the same gates; no document treats its own
commit hash as approval evidence.

The assessed implementation SHA had green ordinary CI (`32427847300`) and Semgrep
(`32427847467`). The evidence-only validation point above also had green ordinary CI
(`32428268010`) and Semgrep (`32428268131`). These runs establish provider evidence for
code quality and structural controls; they are not independent production acceptance.

## Implemented contract changes

The repository now provides:

- immutable per-skill AI Skills lock entries with version, full revision, and normative entrypoint;
- a machine-readable migration assessment plus atomic child-control report;
- a dedicated pinned-authority adoption workflow and an evidence-freshness gate;
- canonical language-neutral capability projections with operation kind, risk, lifecycle state, retry/idempotency semantics, approval policy, concurrency, response bounds, and protocol revisions;
- separate supported and active catalogs with explicit inactive reasons;
- verified SSH peer identity based on the SHA-256 host-key fingerprint for mutation approval binding;
- prohibition of writes over deliberately unverified SSH;
- no-follow directory-descriptor remote writes shared by SSH and the mikr.us `/exec` backend;
- independent capability, request, and server deadline bounds;
- phase-aware mutation deadlines: a mutation does not consume its approval or enter the side-effecting adapter unless at least the adapter classification budget remains, while expiry after execution starts is reported as an ambiguous outcome;
- immediate local rate-limit errors with retry guidance instead of sleeping inside an operation deadline;
- provenance metadata and retry guidance preserved across the public MCP boundary;
- response limits applied to the serialized application envelope;
- startup/liveness/readiness/dependency/capability-degradation health dimensions;
- exact application-wheel SHA verification inside the container build;
- committed hashed Linux x64 CPython 3.12, 3.13, and 3.14 runtime and development locks, each regenerated and installed in provider lock lanes with `--require-hashes` and `pip check`;
- AFDS v2 frontmatter for every governed document.

## Credential-free acceptance contract

Repository gates cover transport-independent backend adapters and one invocation kernel,
immutable configuration, complete manifest coverage, capability and target authorization,
no target fallback, one-time approval binding, read retry policy, mutation retry veto and
reconciliation semantics, structured sanitization, SSH identity, HTTP authentication and
bounds, cancellation, exact installed-wheel official-client behavior, exact Linux/amd64
container behavior, workflow privilege policy, static security checks, typing, lint,
coverage, dependency audit, pinned AI Skills adoption validation, and atomic child-control
validation.

The exact installed-wheel transport checks exercise tool listing, representative reads,
missing-target failures, and unapproved-write rejection over both stdio and authenticated
Streamable HTTP. Provider conclusions, run IDs, artifact IDs, and digests are valid only
for the revision recorded by the corresponding evidence object.

## Rule summary

| Rule family | Current state | Evidence or gap |
| --- | --- | --- |
| MCP architecture boundaries | implemented | shared kernel, adapters, registration and transport tests |
| Identity and target binding | implemented structurally | selector authorization, exact target identity and SSH peer fingerprint; real rotation evidence remains |
| Manifest completeness | implemented | canonical supported/active projections and fail-closed registration |
| Retry and workflow safety | implemented | transient read retry only; mutations single-attempt; pre-execution versus ambiguous post-start deadline behavior tested |
| Transport and lifecycle | implemented | stdio and authenticated loopback Streamable HTTP exercised through official client |
| Deadlines and concurrency | implemented | request/capability/server bounds, keyed locks, cancellation and mutation classification budget |
| Structured responses | implemented | protocol-native errors, provenance, retry guidance, sanitization and envelope bounds |
| Server-side authorization | single-operator profile | hidden approvals bind principal, capability, target identity, resource and normalized arguments |
| Filesystem write boundary | implemented structurally | component no-follow dir-fd traversal and atomic replacement; real remote race evidence remains |
| Exact artifact | implemented structurally | exact wheel and Linux/amd64 image build/smoke gates are green on assessed revision |
| Dependency reproducibility | implemented for declared Python lanes | committed 3.12-3.14 runtime/dev hashed locks and provider regeneration/install lanes |
| AFDS documentation | implemented structurally | schema v2 governed documents validated by pinned authority |
| AI Skills adoption evidence | implemented structurally | pinned adoption validator, atomic report validator, provider artifact and stale-evidence rejection |
| Production operations | incomplete | deployment audit/metrics/SLO, recovery drills, real-system mutation/SSH/filesystem evidence and independent review remain |

## Pinned-contract limitation

The pinned `fdb462...` atomic catalog currently makes the `mcp.artifact.multiarch-exact`
child control applicable when the generic atomic profile contains `container`, not only
when a deployment actually claims multi-architecture publication. This repository
intentionally advertises Linux/amd64 only. `atomic-claims.yaml` therefore does not invent
multi-architecture evidence or select the container atomic profile. Linux/amd64 container
evidence remains recorded separately in repository CI and migration documentation. A
future authority may correct that applicability distinction; until then this is an
explicit upstream-contract limitation, not a consumer-side multi-architecture claim.

## Deferred external evidence

The following cannot be established by repository mocks or self-review:

- SSH fingerprint enrollment, rotation, and address-to-identity revalidation on real target classes;
- one execution and postcondition reconciliation for every real mikr.us mutation;
- remote filesystem symlink-swap behavior on each deployed filesystem/backend combination;
- published-image digest smoke for any release platform actually promoted;
- deployment-specific audit sink, metrics/SLO definition, and recovery exercises;
- independent review bound to the accepted production revision.

The current container release profile remains Linux/amd64. Multi-architecture publication
is not claimed.

## Acceptance gate

Structural L2 migration evidence is valid only while the assessed code/tooling revision
remains `7cf17f934483469b281a1f30d7ceb1f16ba4e92b`, all later changes are limited to the
evidence/status allowlist, and the pinned assessment validator, atomic validator,
freshness gate, ordinary CI, and security scan are green on the candidate evidence-only
HEAD.

Production acceptance additionally requires completion or an owned, expiring waiver for
applicable real-system and operational controls, retained deployment artifact evidence,
and independent review after the final accepted evidence revision. No local result,
intermediate branch SHA, badge, self-authored assessment, or provider-green CI run is by
itself final AI Skills production approval.
