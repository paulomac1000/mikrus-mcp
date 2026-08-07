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

## Verified locally

The credential-free suite verifies:

- transport-independent domain adapters and one invocation kernel;
- immutable configuration loaded before dependency construction;
- complete supported and active manifest coverage;
- capability and exact-target authorization before network resolution;
- no default-target fallback;
- operator write gates, no public approval-token parameter, and one-time approval binding;
- secure approval-file replacement reload, lock-before-consume, and target-connect-before-consume;
- mutation retry veto and manifest-driven bounded read retry with `Retry-After`;
- field-aware response redaction and bounded responses;
- SSH host-verification configuration and bounded process output;
- loopback Host, Origin, bearer authentication, and body controls;
- official-client-shaped tool listing and representative calls against mocked targets;
- cancellation propagation and deterministic target cleanup.

The current local candidate collects 65 tests. The observed result is
`59 passed, 9 skipped` for `python -m pytest -q`; branch coverage is 66.07% at the
repository's 65% gate. Skipped tests are explicit SDK, provider, dependency-lock, or
real-system evidence placeholders rather than hidden success. These numbers must be
recomputed from a clean checkout of the final published commit before merge.

Provider evidence is accepted only when its checked-out commit SHA equals the current
pull-request head. Results from an earlier local directory, generated staging tree, or
superseded commit are not evidence for the published branch.

## Rule summary

| Rule family | Current state | Evidence or gap |
| --- | --- | --- |
| MCP architecture boundaries | implemented | `config.py`, `manifests.py`, `kernel.py`, `client.py`, `server.py` and unit tests |
| Identity and target binding | implemented locally | authorization-before-connect and no-fallback tests; real SSH revalidation deferred |
| Manifest completeness | implemented | startup coverage validation and manifest tests |
| Retry and workflow safety | implemented for current synchronous operations | adapter performs one attempt; manifest-driven read retry and mutation veto tests; real ambiguous mutation reconciliation deferred |
| Transport and lifecycle | implemented structurally | stdio and Streamable HTTP composition; exact real SDK/network evidence required in provider CI |
| Deadlines and concurrency | implemented locally | timeout, cancellation, output, rate-limit, and keyed-lock controls |
| Structured responses | implemented | native structured tool results and protocol tool errors; exact SDK artifact smoke required |
| Server-side authorization | implemented for one trusted operator | loopback HTTP bearer boundary, process scopes, hidden approval records, and live secure reload; no public multi-tenant profile |
| Observability and operations | partial | request metadata and target status exist; SLO, metrics backend, durable audit, and recovery drill absent |
| Exact artifact | designed, not provider-approved | CI exports the tested wheelhouse and image archive; publish verifies and promotes that bundle without rebuilding; provider execution pending |
| AFDS documentation | implemented structurally | governed docs and immutable upstream validator in CI; factual review remains human work |
| AGENTS.md | implemented structurally | concise routes, modes, boundaries, commands, and exact revision pin |
| CI/CD | substantially implemented | SHA-pinned actions, pinned base-image digest, timeouts, exact artifact promotion; complete hashed dependency locks and provider execution pending |

## Deferred evidence

The following acceptance evidence cannot be produced by mocks or self-review and is
represented by skipped tests in `tests/real_system/test_deferred_evidence.py`:

- SSH fingerprint enrollment and address-to-identity revalidation on a real target;
- one execution and postcondition reconciliation for every real mikr.us mutation;
- remote filesystem symlink-swap and TOCTOU behavior;
- exact wheel tests on macOS arm64 and Windows x64;
- smoke of the published OCI digest on every advertised architecture;
- complete platform-specific transitive dependency locks with hashes.

The current release advertises one Linux container platform until a complete
multi-architecture promotion workflow and runtime evidence are available.

## Open compliance gaps

A production approval still requires:

1. complete platform-specific runtime and development lock graphs with hashes;
2. provider execution of lint, formatting, typing, security, dependency, wheel,
   official-client, and container jobs on the exact final SHA;
3. retained JUnit, wheel digest, image digest, and independent review evidence;
4. a deployment-specific audit sink, metrics/SLO definition, and recovery exercise;
5. completion or an owned expiring waiver for every deferred real-system test.

No local result, draft pull request, badge, or generated document should be described
as final AI Skills adoption approval until these conditions are met.
