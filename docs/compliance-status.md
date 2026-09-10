---
afds_schema_version: 2
assessed_revision: f5bdf7f8b1170a89eaec3aa557940cd21e1eb86f
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

This repository pins AI Skills `1.4.0` at revision
`435061ad67ee36d77e01a993bc4f9e4379a29666` — the current `main` of
`paulomac1000/ai-skills` and the sole contract authority for adoption claims. The pin is
recorded in `ai-skills.lock.yaml` with per-skill normative entrypoints and content
digests. The implementation targets the `mcp-server`, single-repository application
profile at maturity level L2.

At `1.4.0` the `mcp-server-architect` rule catalog expands from twelve stable rule
families to twenty-seven. All twelve families previously assessed against `1.2.0`
remain normative and unchanged in identifier; the fifteen additional families are
assessed in the rule summary below. `assessed_revision` in this document's frontmatter
binds the structural assessment to the exact branch revision whose locks and workflow
bindings were provider-verified; subsequent descendants may differ only in evidence
paths as enforced by `scripts/check_evidence_freshness.py`.

Some repository controls deliberately exceed what `main` requires; they are labeled
*local hardening* below and are never presented as upstream requirements. Candidate-only
contracts from an upstream hardening branch (skills-lock validator, canonical capability
schema, atomic child controls, AFDS document schema 2) were removed from authoritative
gates; where retained locally they are explicitly non-authoritative.

`assessed_revision` in this document's frontmatter names the exact 2.1.0 branch
revision whose implementation, lock, and workflow state this structural assessment
describes. The independent ChatGPT provider review of the capability delta in this
branch returned APPROVE at round 2 after the plan-record fix (session of 2026-09-10,
recorded below); additional provider review rounds are attached to the pull request
for the exact head. Any descendant used for the release may differ only in the
evidence paths allowed by `scripts/check_evidence_freshness.py`; any implementation,
dependency, configuration, or workflow change requires a new assessment binding.
Provider run IDs and artifact IDs are not treated as timeless approval: release
publication independently requires a successful ordinary CI run and the exact
non-expired release bundle for the tagged SHA. No document treats its own commit
hash, a badge, or self-authored evidence as independent production approval.

## Implemented contract changes

Measured against the twenty-seven stable `mcp-server-architect` rules at `1.4.0`
(`contracts/rule-catalog.yaml` at the pinned revision), the repository now provides:

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
| mcp.sdk.compatibility-isolation | implemented structurally | official SDK registration isolated in `server.py`; MCP-independent adapters in `client.py` |
| mcp.configuration.lifecycle | implemented structurally | frozen immutable settings snapshot; atomic reload path exists only for the approval registry, not the main configuration |
| mcp.components.public-contract | implemented | public schemas exclude internal authorization inputs; registration is manifest-derived and parity-tested |
| mcp.discovery.progressive | implemented structurally | capability catalog separates supported from active with machine-readable inactive reasons |
| mcp.transport.remote-hardening | not-applicable | remote/public HTTP exposure is deliberately unsupported; Streamable HTTP remains authenticated loopback-only |
| mcp.filesystem.containment | implemented | component-aware no-follow path validation, protected secret tree, symlink rejection; `file_patch_atomic` adds digest-CAS replacement anchored to the same opened descriptor |
| mcp.artifact.ownership | implemented structurally | build provenance stamping, exact-artifact smoke, durable-job output cursors keep artifacts owner-bound |
| mcp.task.supervision | implemented structurally | typed program jobs, durable remote jobs, and Docker/Compose recreate plans with receipts; bounded cleanup, PID identity validation, `lost`/`expired` states; cron projections guarded by `CONCURRENT_MODIFICATION` re-read checks |
| mcp.browser.profile-isolation | not-applicable | the server exposes no browser-automation capability |
| mcp.backends.identity | implemented | no target substitution on failure; resolved identity includes stable mikr.us server ID and SSH peer fingerprint |
| mcp.embedded.host-ownership | not-applicable | no embedded/hosted-device capability exists |
| mcp.authorization.resource-isolation | implemented structurally | per-resource digest scope axis with explicit `resource:*` wildcard profile; data-classification axis gates sensitive reads |
| mcp.abuse.controls | single-operator profile | bounded request/response/output/concurrency/deadline limits exist; multi-tenant abuse controls are not claimed |
| mcp.health.readiness | implemented | `health://ready` requires a connected default target; lazy startup is explicit |
| mcp.operations.recovery-drills | incomplete | deployment audit/metrics/SLO and recovery drills remain deferred external evidence |

The per-rule `1.4.0` assessment above is structural self-measurement, not an adoption
decision; the independent-review requirement in the acceptance gate continues to apply
to the exact final revision.

## Provider review of the capability delta

A provider review (ChatGPT, session of 2026-09-10) covered the durable remote-job,
`file_patch_atomic`, cron-profile, and Docker/Compose capability work implemented on top
of parent revision `1785719` as an uncommitted working tree. Round 1 returned
`REQUEST_CHANGES` with two findings on the Docker plan/apply contract (apply-time
desired-state parameters; invocation-derived rather than plan-derived drift
classification). The fix introduced expiring server-side plan records bound to the
receipt digest; round 2 returned `APPROVE` on the described contract. This review
addressed design conformance of the described delta, not the exact final commit: the
repository requirement that review bind to the exact final revision still applies once
the tree is committed, and it does not substitute for real-system deployment evidence
or final adoption approval.

## Deferred external evidence

The following cannot be established by repository mocks or self-review:

- SSH fingerprint enrollment, rotation, and address-to-identity revalidation on real target classes;
- one execution and postcondition reconciliation for every real mikr.us mutation;
- remote filesystem symlink-swap behavior on each deployed filesystem/backend combination;
- durable remote job disconnect/restart reconciliation (a longer-than-timeout job on a
  dedicated SSH target, with owner-scoped cancel and output-cursor continuity) — the local
  durable-job implementation is covered by credential-free gates only;
- a deployment receipt binding exact source SHA, package content digest, and image
  digest, verified by `scripts/verify_deployed_release.py` against a running instance —
  satisfied locally on 2026-09-10 for the exact stamped wheel/container of revision
  `d6204a2f` (binding and package integrity verified both inside the running container
  and from the host against the exact wheel); registry publication and promotion of the
  immutable image remain provider steps for any real release;
- published-image digest smoke for any release platform actually promoted;

## Real-system evidence recorded 2026-09-10

The following evidence was recorded against live systems with explicit operator
authorization; it is session evidence, not a durable CI gate:

- real mikr.us API (read-only): live `real_backend` suite passed 4/4 — `get_server_info`
  shape, `get_ports`, `list_servers` containing the configured identity, and sequential
  rate-limiter behavior against `https://api.mikr.us`;
- real mikr.us VPS via the operator-assigned SSH endpoint (`srv07.mikr.us:10359`,
  unprivileged user, verified ED25519 host fingerprint): the same full-kernel suite —
  durable remote jobs (start, idempotent reuse, bounded wait, output cursors returning
  the real remote hostname, owner-scoped cancel, completion with result),
  `file_patch_atomic` replace plus stale-digest `CONFLICT` without write, cron profile
  upsert/list/remove with the installed crontab byte-preserved, and Docker
  snapshot/plan/receipt-bound apply with observed container recreation and bounded
  `service_wait` — all passed on the actual VPS (Docker 26.1.3, Compose v2.32.4);
- exact-artifact behavior: the stamped wheel (`sha256:45070db2…`) passed transport
  smoke, the built container served authenticated loopback Streamable HTTP through the
  official MCP client (3/3 live instance tests: tool listing, sanitized
  `get_server_info`, unapproved write fail-closed), and the deployment receipt
  verified `binding=verified`, `package=verified` inside the running container and
  from the host against the exact wheel;
- SSH platform limitation recorded: the configured mikr.us VPS runs `sshd` on
  `0.0.0.0:22` internally, but the platform port-forward set does not expose TCP/22
  externally (all assigned forwards refused from two independent networks); SSH-backed
  real-system evidence was therefore collected on a dedicated operator-directed target;
- real SSH target, full kernel path with trusted-operator approvals bound to the
  verified ED25519 host fingerprint: durable remote jobs (start, cross-invocation
  idempotent reuse returning the same job id, bounded wait, output cursors,
  owner-scoped cancel to terminal `cancelled`, completion to `succeeded` with result
  retrieval); `file_patch_atomic` replace with matching digest plus a stale-digest
  attempt rejected `CONFLICT` without writing; cron profile upsert → `IN_SYNC`,
  exact-pair remove, and empty listing afterwards with the installed crontab otherwise
  byte-preserved; Docker `runtime_snapshot` (service-scoped, image digest evidence),
  `recreate_plan` receipt, receipt-bound `recreate_apply` (recreation observed via new
  container id), and bounded `service_wait` reaching `READY`;
- the deferred `TODO(real-system)` tests (symlink-swap race with a concurrent adversary,
  host-key rotation revalidation, mikr.us mutation reconciliation) and the deployment
  receipt remain open and still require dedicated evidence.
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
