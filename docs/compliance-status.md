---
description: Rule-level adoption status and residual evidence gaps for the pinned AI Skills release
doc_id: reference.compliance-status
type: reference
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Compare this document with `ai-skills.lock.yaml`, run `scripts/ci.py`, and require provider-backed evidence on the exact final revision before approval.
---
# Compliance status

## Assessment boundary

This repository pins AI Skills `1.2.0` at revision
`661ff01a5e70d58d6c94a12545b24647e52063ed`. The implementation targets the
`mcp-server`, single-repository application profile. This document is a diagnostic
self-assessment, not independent provider-backed approval.

A newer hardening branch is being evaluated separately. It must not replace the pinned
authority until its exact revision is provider-green and the required independent
provider review exists. Migration evidence must use real provider identifiers; it must
never synthesize a reviewer or review ID.

## Credential-free acceptance contract

The repository gates verify:

- transport-independent domain adapters and one invocation kernel;
- immutable configuration loaded before dependency construction;
- complete supported and active manifest coverage;
- capability and exact-target authorization before network resolution;
- no default-target fallback;
- operator write gates, no public approval-token parameter, and one-time approvals
  bound to the principal, capability, stable target identity, resource, and normalized
  operation arguments;
- secure approval-file replacement reload, lock-before-consume, and
  target-connect-before-consume;
- mutation retry veto and manifest-driven bounded read retry with `Retry-After`;
- field-aware response redaction and bounded responses;
- SSH host-verification configuration and bounded process output;
- loopback Host, Origin, bearer authentication, and body controls;
- official MCP client tool listing, schema inspection, and real stdio and Streamable HTTP
  calls from the installed exact wheel;
- cancellation propagation and deterministic target cleanup;
- exact-wheel installation and official-client smoke over every advertised transport;
- container build from the exact wheelhouse, official-client MCP invocation, and immutable
  release-bundle export;
- release-candidate ancestry validation and quarantine-to-production digest promotion
  without loading or running candidate code in the privileged publisher;
- lint, formatting, strict typing, security scan, dependency audit, and coverage gates.

Test counts, coverage percentages, artifact digests, and provider conclusions are not
stored in this document. They are per-revision evidence and are valid only when the
checked-out commit SHA equals the pull-request or release candidate SHA.

## Rule summary

| Rule family | Current state | Evidence or gap |
| --- | --- | --- |
| MCP architecture boundaries | implemented | `config.py`, `manifests.py`, `kernel.py`, `clients/`, `server.py` and unit tests |
| Identity and target binding | implemented for supported local transports | request-scoped HTTP principal, stable target-identity approvals, authorization-before-connect, and no fallback are covered; real SSH host-key identity evidence remains open |
| Manifest completeness | implemented locally | startup coverage validation and manifest tests; mapping to the newer canonical AI Skills schema remains migration work |
| Retry and workflow safety | implemented for current operations | adapter performs one attempt; manifest-driven read retry and mutation veto tests; real ambiguous mutation reconciliation deferred |
| Transport and lifecycle | implemented | stdio and authenticated loopback Streamable HTTP with official-client tests |
| Deadlines and concurrency | implemented locally | timeout, cancellation, output, rate-limit, and keyed-lock controls |
| Structured responses | implemented | native structured tool results and protocol tool errors; exact wheel is exercised by the official client |
| Server-side authorization | single-operator profile | stdio process identity and request-scoped bearer-derived HTTP identity feed hidden approvals bound to normalized arguments and stable target identity; resource-granular multi-tenant authorization remains out of scope |
| Observability and operations | partial | request metadata and target status exist; SLO, metrics backend, durable audit, and recovery drill absent |
| Exact artifact | implemented in CI | the installed exact wheel is exercised over real stdio and Streamable HTTP, the exact container receives an official-client MCP invocation, and release promotes the tested quarantined digest without executing candidate code in the privileged publisher |
| AFDS documentation | migration pending | current pinned validator governs authored docs; AFDS v2 migration waits for a green replacement authority and valid migration assessment |
| AGENTS.md | implemented structurally | routes, modes, boundaries, commands, and exact revision pin; factual drift remains reviewable |
| CI/CD | substantially implemented | SHA-pinned actions, digest-pinned base image, audited pip, release ancestry check, source-free digest promotion, and exact-artifact gates; complete hashed dependency locks remain open |

## Deferred evidence

The following acceptance evidence cannot be produced by mocks or self-review and is
represented by explicit real-system/provider gaps:

- SSH fingerprint enrollment and address-to-identity revalidation on a real target;
- one execution and postcondition reconciliation for every real mikr.us mutation;
- remote filesystem symlink-swap and TOCTOU behavior;
- exact wheel tests on macOS arm64 and Windows x64;
- smoke of the published OCI digest on every advertised architecture;
- complete platform-specific transitive dependency locks with hashes;
- independent provider review required by the newer migration-assessment contract.

The current release advertises one Linux container platform until a complete
multi-architecture promotion workflow and runtime evidence are available.

## Open compliance gaps

A production approval still requires:

1. complete platform-specific runtime and development lock graphs with hashes;
2. provider execution of lint, formatting, typing, security, dependency, wheel,
   official-client, and container jobs on the exact final SHA;
3. retained JUnit, wheel digest, image digest, and independent review evidence;
4. real SSH host-key identity evidence on production target classes;
5. a deployment-specific audit sink, metrics/SLO definition, and recovery exercise;
6. completion or an owned expiring waiver for every deferred real-system test;
7. migration to a provider-green newer AI Skills authority, including its canonical
   manifest, AFDS v2, atomic claims, and migration-assessment contracts.

No local result, draft pull request, badge, or generated document should be described
as final AI Skills adoption approval until these conditions are met.
