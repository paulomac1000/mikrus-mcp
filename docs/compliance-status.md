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
  value: Compare this document with `ai-skills.lock.yaml`, run `scripts/ci.py`, and require provider-backed evidence on the exact final revision before approval.
---
# Compliance status

## Assessment boundary

This repository pins AI Skills `1.2.0` to immutable revision
`2b04b30f4d3883437dd1738ceaaae61567b0c564`. The revision is a post-1.2.0 hardening
candidate and is used as the current contract authority for this migration. Its exact
head does not yet have complete provider-green upstream evidence, so this repository
does not infer upstream release acceptance from the pin.

This document is a diagnostic self-assessment. Provider CI on the exact adopting
revision and independent review are separate evidence. No reviewer, review ID, provider
run, artifact digest, or real-system result may be invented to make an assessment pass.

## Implemented contract changes

The repository now provides:

- immutable per-skill AI Skills lock entries with version, full revision, and normative entrypoint;
- canonical language-neutral capability projections with operation kind, risk, lifecycle state, retry/idempotency semantics, approval policy, concurrency, response bound, and protocol revisions;
- separate supported and active catalogs, including explicit reasons for inactive capabilities;
- verified SSH peer identity based on the SHA-256 host-key fingerprint for mutation approval binding;
- prohibition of writes over deliberately unverified SSH;
- no-follow directory-descriptor remote writes shared by SSH and the mikr.us `/exec` backend;
- independent capability, request, and server deadline bounds instead of the previous global 10-second truncation;
- provenance metadata and retry guidance preserved across the public MCP boundary;
- response limits applied to the serialized application envelope;
- startup/liveness/readiness/dependency/capability-degradation health dimensions;
- exact application-wheel SHA verification inside the container build;
- a hashed Linux x64 CPython 3.12 runtime lock and provider jobs which generate candidate hashed runtime/development locks for Python 3.12, 3.13, and 3.14;
- AFDS v2 frontmatter for every governed document.

## Credential-free acceptance contract

The repository gates cover:

- transport-independent backend adapters and one invocation kernel;
- immutable configuration loaded before dependency construction;
- complete supported and active manifest coverage;
- capability and exact-target authorization before protected target operations;
- no default-target fallback;
- operator write gates and one-time approvals bound to principal, capability, resolved target identity, resource, and normalized operation arguments;
- mutation retry veto, ambiguous-outcome classification, and bounded read retry limited to explicit transient failures;
- field-aware response redaction, provenance, retry guidance, and final-envelope size bounds;
- SSH host verification, peer-fingerprint identity, and bounded process output;
- loopback Host, Origin, bearer authentication, and body controls;
- official MCP client tool listing, schema inspection, representative fake-upstream read, missing-target failure, and approval-boundary rejection over real stdio and Streamable HTTP subprocesses from the installed exact wheel;
- cancellation propagation and deterministic target cleanup;
- exact-wheel installation and official-client smoke over every advertised transport;
- container build from the verified wheelhouse and application-wheel digest;
- release-candidate ancestry validation and quarantine-to-production digest promotion without executing candidate code in the privileged publisher;
- lint, formatting, strict typing, security scan, dependency audit, and coverage gates.

Test counts, coverage percentages, artifact digests, and provider conclusions are
per-revision evidence. They are valid only when the provider run is bound to the exact
pull-request or release candidate SHA.

## Rule summary

| Rule family | Current state | Evidence or gap |
| --- | --- | --- |
| MCP architecture boundaries | implemented | `config.py`, `manifests.py`, `kernel.py`, `clients/`, `server.py`, and tests |
| Identity and target binding | implemented structurally | HTTP request principal, mikr.us identity, SSH verified peer fingerprint, selector authorization, and no fallback; real host-key rotation evidence remains deployment work |
| Manifest completeness | implemented | canonical projections, supported/active split, inactive reasons, startup registration coverage, and pinned-schema validation in CI |
| Retry and workflow safety | implemented classification | adapters perform one request attempt; explicit transient reads may retry; mutations never auto-retry; real mutation postcondition reconciliation remains operational evidence |
| Transport and lifecycle | implemented | stdio and authenticated loopback Streamable HTTP with shared kernel and capability-aware health |
| Deadlines and concurrency | implemented | capability/request/server deadline separation, cancellation, output bounds, rate limit, and keyed locks |
| Structured responses | implemented | structured results, MCP tool errors, provenance metadata, retry guidance, and final-envelope size enforcement |
| Server-side authorization | single-operator profile | hidden approvals bind normalized arguments and resolved target identity; multi-tenant resource policy remains out of scope |
| Filesystem write boundary | implemented structurally | component no-follow dir-fd traversal and atomic replacement; real filesystem race evidence remains required |
| Exact artifact | implemented structurally | exact wheel is smoked over advertised transports; image verifies application-wheel SHA and is built from that wheelhouse |
| AFDS documentation | implemented structurally | governed documents use AFDS schema v2 and the pinned authority validator |
| CI/CD | migration in progress | SHA-pinned actions, digest-pinned base image, exact-artifact gates, and hashed lock generation; final committed 3.12-3.14 dev/runtime graphs require provider-generated lock artifacts |

## Deferred external evidence

The following cannot be established by repository mocks or self-review:

- SSH fingerprint enrollment, rotation, and address-to-identity revalidation on real target classes;
- one execution and postcondition reconciliation for every real mikr.us mutation;
- remote filesystem symlink-swap behavior on each production filesystem/backend combination;
- published OCI digest smoke on every advertised platform;
- independent provider review required for production acceptance;
- deployment-specific audit sink, metrics/SLO definition, and recovery exercise.

The current container release profile advertises Linux/amd64 until a complete
multi-architecture promotion and platform-smoke chain exists.

## Acceptance gate

Production acceptance requires all of:

1. committed hashed runtime and development graphs for every declared supported Python lane;
2. provider execution of quality, compatibility, lock, wheel, official-client, container, and security jobs on the exact final SHA;
3. retained machine-readable evidence and artifact digests bound to that SHA;
4. completion or an owned expiring waiver for every applicable real-system control;
5. a schema-valid adoption assessment which does not fabricate provider or reviewer evidence;
6. independent review after the final code/evidence revision.

No local result, intermediate branch SHA, badge, or self-authored assessment is final AI
Skills adoption approval.
